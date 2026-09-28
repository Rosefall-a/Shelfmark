# pylint: disable=duplicate-code
"""API routes for pulling a user's owned-games library + achievements from
Steam, PlayStation, and RetroAchievements straight into their library — a
different mechanism from `games.py`'s `/metadata/search`, which enriches one
already-added game by title. This creates/updates real `Game` rows and
`Achievement` rows in bulk from an account-wide library call.

Xbox is deliberately not here: a real library pull needs a full OAuth
consent redirect (Microsoft identity platform + Xbox Live XASU/XSTS token
exchange) that requires the user's own registered Azure AD app and a
redirect URI this server hosts — Settings only stores the client
id/secret today (see MetadataSourcesSection's Xbox card), it can't complete
that flow yet.
"""

# Pylint attributes imported model-field similarity to this route module.
# # The parallel model definitions are intentional.
# # pylint: disable=broad-exception-caught,too-many-locals,too-many-branches,chained-comparison,missing-function-docstring,too-many-statements,unused-variable,duplicate-code

from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.games import _scan_settings_to_preferences
from src.api.routes.settings import (
    get_or_create_app_integration_settings,
    get_or_create_scan_settings,
)
from src.core.auth import get_current_user
from src.core.config import settings as app_settings
from src.core.crypto import decrypt_secret
from src.core.integrations import resolve_integrations
from src.database.models.achievement import Achievement
from src.database.models.game import Game, GameStatus
from src.database.models.user import User
from src.database.session import get_db
from src.features.metadata.games import steam
from src.features.metadata.games.igdb import IGDBClient
from src.features.metadata.games.psn import PSNClient, PSNError
from src.features.metadata.games.retroachievements import (
    RetroAchievementsClient,
    RetroAchievementsError,
)
from src.features.metadata.games.search import search_game_metadata
from src.features.metadata.games.steam_grid_db import SteamGridDBClient
from src.helpers.save_game_asset import AssetKind, create_game_folder, save_game_asset

router = APIRouter(
    prefix="/api/library-sync", tags=["library-sync"], dependencies=[Depends(get_current_user)]
)

_SLUG_INVALID = re.compile(r"[^A-Za-z0-9_-]+")
_TITLE_NOISE = re.compile(r"[™®©]")


def _normalize_title(title: str) -> str:
    """A library-sync title (from Steam's owned-games list, etc.) and a
    metadata search result's title (from Steam's storefront search, which
    routinely includes ™/® in the marketing name, e.g. "Apex Legends™")
    refer to the same game but rarely compare equal as raw strings — that
    was silently failing the exact-match gate below for a large fraction of
    perfectly normal titles. Strip trademark/copyright marks and collapse
    whitespace/case before comparing; the original, unmodified title is
    still what gets applied to the game."""
    return _TITLE_NOISE.sub("", title).strip().lower()


_SYNC_CONCURRENCY = 5

# Steam's owned-games list includes non-game companion apps alongside real
# games — public playtests, test/staging servers, and Valve's own
# placeholder for a delisted/renamed app. None of these are things a user
# is tracking as a "game" to beat/master, so they're skipped entirely
# during sync rather than imported with (inevitably blank) metadata.
_JUNK_TITLE_PATTERN = re.compile(
    r"(playtest|public test\b|test server|testing branch|staging branch|dedicated server)"
    r"|^game migrated to another steam page$",
    re.IGNORECASE,
)


def _is_junk_title(title: str) -> bool:
    return bool(_JUNK_TITLE_PATTERN.search(title))


# Steam's CDN asset naming convention is stable and public (used by Playnite,
# LaunchBox, etc.) — since a Steam library sync already knows the exact
# appid, art can come straight from here instead of a text search that might
# match the wrong game. _download_asset silently no-ops on a 404, so trying
# a URL that doesn't exist for an older game is harmless.
def _steam_cdn_art_urls(app_id: int) -> dict[AssetKind, str]:
    base = f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}"
    return {
        "key_art": f"{base}/library_600x900.jpg",
        "banner": f"{base}/library_hero.jpg",
        "logo": f"{base}/logo.png",
    }


async def _fetch_key_art_from_steamgriddb(app_id: int, api_key: str | None) -> str | None:
    """SteamGridDB's "grids" are the portrait (~2:3) shape key_art actually
    needs — Steam's storefront API has no portrait art at all (header/
    capsule images are all wide), so using one of those as a key_art
    fallback (an earlier version of this function did, briefly) just
    force-crops a landscape image into a portrait slot and produces a
    mangled cover. Looked up by Steam appid, same as the rest of this
    function — no title-matching ambiguity. No-ops without a key."""
    if not api_key:
        return None
    try:
        client = SteamGridDBClient(api_key)
        sgdb_game = await asyncio.to_thread(client.get_game_by_steam_appid, app_id)
        if not sgdb_game or not sgdb_game.get("id"):
            return None
        images = await asyncio.to_thread(client.get_game_images, sgdb_game["id"], "grids")
    except Exception:
        return None
    return images[0].url if images else None


async def _enrich_steam_game_by_appid(
    game: Game, app_id: int, user: User, igdb_client_id: str | None, igdb_client_secret: str | None
) -> None:
    """Steam-sourced games already carry an authoritative Steam appid from
    the account's real owned-games list — no text matching needed at all,
    which is exactly what made the generic search-based `_enrich_new_game`
    occasionally attach one game's data/art to a different, similarly-named
    game. Pulls straight from Steam's own storefront API + CDN, both keyed
    by that exact id. Best-effort, like `_enrich_new_game`."""
    try:
        details = await asyncio.to_thread(steam.get_app_details, app_id)
    except Exception:
        details = None
    if details:
        if details.get("developers"):
            game.developer = ", ".join(details["developers"])
        if details.get("publishers"):
            game.publisher = ", ".join(details["publishers"])
        # "About This Game" (rich HTML, the dev's full writeup) over the
        # plain-text short_description blurb meant for search-result lists
        # — matches search.py's _steam_result, which this appid-anchored
        # path was inconsistent with (it was only using short_description)
        description = (
            details.get("about_the_game")
            or details.get("detailed_description")
            or details.get("short_description")
        )
        if description:
            game.description = description
        genres = details.get("genres") or []
        tags = [g["description"] for g in genres if g.get("description")]
        if tags:
            game.tags = tags
        categories = details.get("categories") or []
        features = [c["description"] for c in categories if c.get("description")]
        if features:
            game.features = features
        required_age = details.get("required_age")
        if required_age:
            game.age_rating = f"{required_age}+"
        release = (details.get("release_date") or {}).get("date")
        if release:
            for fmt in ("%b %d, %Y", "%d %b, %Y", "%Y"):
                try:
                    game.release_date = datetime.strptime(release, fmt).date()
                    break
                except ValueError:
                    continue

    series = await _fetch_series_from_igdb(game.title, igdb_client_id, igdb_client_secret)
    if series:
        game.series = series
        _add_to_series_collection(game, series)

    saved: dict[AssetKind, bool] = {}
    for asset_kind, url in _steam_cdn_art_urls(app_id).items():
        saved[asset_kind] = await _download_asset(url, game.id, asset_kind)

    # not every app has the "library" style art Steam generates for newer
    # titles (older/free/niche games often don't). header_image is wide
    # (~460x215) — a fine banner fallback, but forcing it into key_art's
    # portrait (~2:3) slot crops it into something unrecognizable, so
    # key_art falls back to SteamGridDB's actual portrait grids instead.
    header_image = (details or {}).get("header_image")
    if not saved.get("key_art"):
        sgdb_key_art = await _fetch_key_art_from_steamgriddb(app_id, user.steamgriddb_api_key)
        if sgdb_key_art:
            await _download_asset(sgdb_key_art, game.id, "key_art")
    if header_image and not saved.get("banner"):
        await _download_asset(header_image, game.id, "banner")


def _infer_status(
    *, playtime_seconds: int = 0, total_achievements: int = 0, unlocked_achievements: int = 0
) -> GameStatus:
    """A freshly-imported game has no manual status from the user yet — a
    library sync only sets one (never overwrites one on re-sync, see
    `_get_or_create_game`'s `created` flag). No playtime/achievement
    progress at all means untouched (Backlog); full achievement completion
    means Mastered; anything in between just means "played" — there's no
    reliable signal for "currently playing" vs. "played once and stopped"
    from a bulk library pull, so Played is the honest, non-presumptuous
    middle ground rather than guessing Playing."""
    has_progress = playtime_seconds > 0 or unlocked_achievements > 0
    if not has_progress:
        return GameStatus.BACKLOG
    if total_achievements > 0 and unlocked_achievements >= total_achievements:
        return GameStatus.MASTERED
    return GameStatus.PLAYED


def _apply_status(game: Game, new_status: GameStatus) -> None:
    """Sets game.status and, the first time it becomes Mastered, records
    when — same rule as the manual status-change routes in games.py."""
    game.status = new_status
    if new_status == GameStatus.MASTERED and game.completion_date is None:
        game.completion_date = int(time.time())


def _add_source_tag_and_collection(game: Game, source: str) -> None:
    """A newly-synced game is tagged with its source (Steam, PlayStation,
    RetroAchievements) and dropped into a same-named collection by default
    — so a library built from several accounts stays sortable by where
    each game actually came from without the user manually tagging
    hundreds of imported titles. Only runs for newly-created games (see
    each sync route's `if created:` guard), same rule as
    `_add_to_series_collection`: a user untagging/removing one later isn't
    silently re-added on the next re-sync."""
    if source not in game.tags:
        game.tags = [*game.tags, source]
    if source not in game.collections:
        game.collections = [*game.collections, source]


def _add_to_series_collection(game: Game, series: str) -> None:
    """Games in the same series get auto-grouped into a same-named
    collection — this is what the future card/set system will build on, so
    it needs to already be populated by the time that ships, not
    retrofitted later. Only ever adds; a user removing a game from this
    collection later isn't re-added on the next sync since this only runs
    for newly-created games (see `_enrich_new_game`/
    `_enrich_steam_game_by_appid`'s callers)."""
    if series not in game.collections:
        game.collections = [*game.collections, series]


async def _download_asset(url: str, game_id: UUID, asset_kind: AssetKind) -> bool:
    """Best-effort — mirrors games.py's download_game_asset route but never
    raises, since one bad art URL must not fail an entire library sync.
    Returns whether it actually saved something, so callers can fall back
    to a different URL."""
    try:
        response = await asyncio.to_thread(requests.get, url, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        return False
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if not content_type.startswith("image/"):
        return False
    if len(response.content) > app_settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        return False
    try:
        await save_game_asset(response.content, game_id, asset_kind)
        return True
    except (OSError, ValueError):
        return False


async def _fetch_series_from_igdb(
    title: str, igdb_client_id: str | None, igdb_client_secret: str | None
) -> str | None:
    """Steam's own storefront API has no franchise/series concept at all,
    so appid-anchored enrichment (which never text-searches, by design —
    see `_enrich_steam_game_by_appid`) would otherwise never fill `series`.
    IGDB is the one configured provider that actually has this data
    (`collection`/`franchises`), so it gets one extra, exact-match-gated
    lookup here. No-ops if this deployment has no IGDB app credentials
    (admin-entered, see AppIntegrationSettings — not an env var)."""
    if not (igdb_client_id and igdb_client_secret):
        return None
    try:
        client = IGDBClient(client_id=igdb_client_id, client_secret=igdb_client_secret)
        results = await asyncio.to_thread(client.search, title, 3)
    except Exception:
        return None
    target = _normalize_title(title)
    match = next((r for r in results if _normalize_title(r.get("name") or "") == target), None)
    return match.get("series") if match else None


async def _enrich_new_game(
    game: Game,
    user: User,
    preferences: dict,
    igdb_client_id: str | None,
    igdb_client_secret: str | None,
) -> None:
    """A library sync only knows a title + playtime/achievements — it says
    nothing about developer, publisher, description, art, etc. Run one
    metadata search per newly-added game (never on an existing/re-synced
    one) and apply whatever the user's scan settings allow, exactly like a
    manual "Refresh Metadata" would. Best-effort: any failure here must
    never fail the sync that's already committed the game itself."""
    try:
        response = await asyncio.to_thread(
            search_game_metadata,
            game.title,
            1,
            user.steamgriddb_api_key,
            preferences,
            user,
            igdb_client_id,
            igdb_client_secret,
        )
    except Exception:
        return
    results = response.get("results") or []
    # only ever apply an exact title match — same rule the manual "Refresh
    # Metadata" flow uses (services/games.ts's refreshGameMetadata). Falling
    # back to the top/best-guess result here was wrong: unrelated titles
    # that merely rank first (e.g. a loose GOG catalog match) were getting
    # applied to the wrong game, producing bogus developer/publisher data.
    target = _normalize_title(game.title)
    match = next((r for r in results if _normalize_title(r.get("title") or "") == target), None)
    if match is None:
        return
    for field in (
        "description",
        "developer",
        "publisher",
        "series",
        "age_rating",
        "tags",
        "features",
        "time_to_beat_hours",
    ):
        value = match.get(field)
        if value:
            setattr(game, field, value)
    if match.get("series"):
        _add_to_series_collection(game, match["series"])
    release_date = match.get("release_date")
    if release_date:
        try:
            game.release_date = date.fromisoformat(release_date)
        except ValueError:
            pass
    asset_fields: list[tuple[AssetKind, str]] = [
        ("key_art", "key_art_url"),
        ("banner", "banner_url"),
        ("logo", "logo_url"),
        ("icon", "icon_url"),
    ]
    for asset_kind, field in asset_fields:
        url = match.get(field)
        if url:
            await _download_asset(url, game.id, asset_kind)


def _slugify(title: str) -> str:
    slug = _SLUG_INVALID.sub("-", title).strip("-")
    return slug or "game"


async def _unique_folder_location(db: AsyncSession, title: str) -> str:
    base = _slugify(title)
    candidate = base
    suffix = 2
    while await db.scalar(select(Game.id).where(Game.folder_location == candidate)) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


async def _get_or_create_game(
    db: AsyncSession, user_id: UUID, title: str, source: str, external_id: str | None = None
) -> tuple[Game, bool]:
    """Match by (user, source, external_id) when the provider gives a
    stable id — a title alone drifts (Steam has reported a different
    display name for the same appid between calls, e.g. briefly appending
    "- GOTY Edition"), which was creating duplicate rows for one real game.
    Falls back to matching by (user, source, title) when no id is given."""
    existing: Game | None = None
    if external_id:
        existing = await db.scalar(
            select(Game).where(
                Game.user_id == user_id,
                Game.source == source,
                Game.external_id == external_id,
                Game.deleted_at.is_(None),
            )
        )
    if existing is None:
        existing = await db.scalar(
            select(Game).where(
                Game.user_id == user_id,
                Game.source == source,
                Game.title == title,
                Game.deleted_at.is_(None),
            )
        )
    if existing:
        if existing.title != title:
            existing.title = title
            existing.sort_title = title.lower()
        if external_id and not existing.external_id:
            existing.external_id = external_id
        # this sync just saw it again — clear any earlier "missing from your
        # library" flag (see _flag_stale_games)
        existing.stale_since = None
        return existing, False

    folder_location = await _unique_folder_location(db, title)
    game = Game(
        user_id=user_id,
        title=title,
        sort_title=title.lower(),
        folder_location=folder_location,
        source=source,
        external_id=external_id,
        status=GameStatus.BACKLOG,
    )
    db.add(game)
    await db.flush()
    create_game_folder(user_id, folder_location)
    return game, True


async def _flag_stale_games(
    db: AsyncSession, user_id: UUID, source: str, touched_ids: set[UUID]
) -> int:
    """After a full sync pass, any active game from this source that wasn't
    touched this time has disappeared from the account's owned-games pull
    (uninstalled, refunded, family-shared game removed, etc.) — flag it
    rather than removing or overwriting anything, since the API alone can't
    tell "gone for good" from "temporarily delisted." A game that reappears
    on a later sync has its flag cleared in _get_or_create_game."""
    result = await db.execute(
        select(Game).where(
            Game.user_id == user_id, Game.source == source, Game.deleted_at.is_(None)
        )
    )
    now = int(time.time())
    newly_flagged = 0
    for game in result.scalars().all():
        if game.id in touched_ids:
            continue
        if game.stale_since is None:
            game.stale_since = now
            newly_flagged += 1
    return newly_flagged


async def _replace_achievements(
    db: AsyncSession, game_id: UUID, provider: str, rows: list[dict]
) -> None:
    """Upserts by (game_id, provider, external_id) rather than delete +
    reinsert — a media item can link to a specific achievement
    (MediaItem.linked_achievement_id), and that FK is ON DELETE SET NULL,
    so wiping every row on each re-sync was silently unlinking every
    screenshot/clip tagged to an achievement the next time the game synced."""
    existing = {
        a.external_id: a
        for a in (
            await db.execute(
                select(Achievement).where(
                    Achievement.game_id == game_id, Achievement.provider == provider
                )
            )
        )
        .scalars()
        .all()
    }
    now = int(time.time())
    seen_ids: set[str] = set()
    for row in rows:
        seen_ids.add(row["external_id"])
        current = existing.get(row["external_id"])
        if current is not None:
            for field, value in row.items():
                setattr(current, field, value)
        else:
            db.add(Achievement(game_id=game_id, provider=provider, created_at=now, **row))
    for external_id, achievement in existing.items():
        if external_id not in seen_ids:
            await db.delete(achievement)


@router.post("/steam")
async def sync_steam_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not current_user.steam_id or not current_user.steam_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Save your Steam ID and API key first."
        )

    scan_settings = await get_or_create_scan_settings(current_user.id, db)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    igdb_client_id = app_integrations.igdb_client_id
    igdb_client_secret = app_integrations.igdb_client_secret
    api_key = current_user.steam_api_key
    try:
        # cheap no-op once the credentials-save flow has already resolved
        # this to a numeric SteamID64 — stays here so a sync never breaks
        # even if the stored value is still a vanity name/profile URL
        steam_id = await asyncio.to_thread(steam.resolve_steam_id, current_user.steam_id, api_key)
        owned_games = await asyncio.to_thread(steam.get_owned_games, steam_id, api_key)
    except steam.SteamLibraryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    # drop playtests/test servers/Valve's delisted-app placeholder before
    # any further work — they're companion apps, not games to track
    owned_games = [e for e in owned_games if e.get("name") and not _is_junk_title(e["name"])]

    semaphore = asyncio.Semaphore(_SYNC_CONCURRENCY)

    async def _fetch_achievements(app_id: int) -> tuple[dict[str, dict], list[dict]]:
        async with semaphore:
            try:
                schema = await asyncio.to_thread(steam.get_schema_for_game, api_key, app_id)
                unlocked = await asyncio.to_thread(
                    steam.get_player_achievements, steam_id, api_key, app_id
                )
            except steam.SteamLibraryError:
                return {}, []
            return schema, unlocked

    fetches = await asyncio.gather(
        *(
            _fetch_achievements(entry["appid"])
            for entry in owned_games
            if entry.get("appid") and entry.get("name")
        )
    )

    games_added = games_updated = achievements_synced = 0
    newly_created: list[tuple[Game, int]] = []
    synced_titles: list[str] = []
    touched_ids: set[UUID] = set()
    fetch_index = 0
    for entry in owned_games:
        title, app_id = entry.get("name"), entry.get("appid")
        if not title or not app_id:
            continue
        schema, unlocked = fetches[fetch_index]
        fetch_index += 1

        game, created = await _get_or_create_game(
            db, current_user.id, title, "Steam", external_id=str(app_id)
        )
        touched_ids.add(game.id)
        game.playtime_seconds = int(entry.get("playtime_forever", 0)) * 60
        if entry.get("rtime_last_played"):
            game.last_played_at = int(entry["rtime_last_played"])
        games_added += created
        games_updated += not created
        synced_titles.append(title)

        total_achievements = unlocked_count = 0
        if schema:
            unlocked_by_name = {a["apiname"]: a for a in unlocked if a.get("apiname")}
            rows = [
                {
                    "external_id": api_name,
                    "name": defn.get("displayName") or api_name,
                    "description": defn.get("description"),
                    "icon_url": defn.get("icon")
                    if unlocked_by_name.get(api_name, {}).get("achieved")
                    else defn.get("icongray"),
                    "unlocked": bool(unlocked_by_name.get(api_name, {}).get("achieved")),
                    "unlocked_at": unlocked_by_name.get(api_name, {}).get("unlocktime") or None,
                }
                for api_name, defn in schema.items()
            ]
            await _replace_achievements(db, game.id, "Steam", rows)
            achievements_synced += len(rows)
            total_achievements = len(rows)
            unlocked_count = sum(1 for r in rows if r["unlocked"])

        if created:
            _apply_status(
                game,
                _infer_status(
                    playtime_seconds=game.playtime_seconds,
                    total_achievements=total_achievements,
                    unlocked_achievements=unlocked_count,
                ),
            )
            _add_source_tag_and_collection(game, "Steam")
            newly_created.append((game, app_id))

    async def _enrich(game: Game, app_id: int) -> None:
        async with semaphore:
            # appid-anchored — no text matching, so no risk of attaching a
            # different game's data/art the way the generic search-based
            # _enrich_new_game occasionally did
            await _enrich_steam_game_by_appid(
                game, app_id, current_user, igdb_client_id, igdb_client_secret
            )

    await asyncio.gather(*(_enrich(g, app_id) for g, app_id in newly_created))

    games_flagged_stale = await _flag_stale_games(db, current_user.id, "Steam", touched_ids)
    current_user.steam_library_synced_at = int(time.time())
    await db.commit()
    return {
        "games_added": games_added,
        "games_updated": games_updated,
        "achievements_synced": achievements_synced,
        "games_flagged_stale": games_flagged_stale,
        "games": synced_titles,
    }


@router.post("/retroachievements")
async def sync_retroachievements_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not current_user.retroachievements_username or not current_user.retroachievements_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Save your RetroAchievements username and API key first.",
        )

    scan_settings = await get_or_create_scan_settings(current_user.id, db)
    preferences = _scan_settings_to_preferences(scan_settings)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    igdb_client_id = app_integrations.igdb_client_id
    igdb_client_secret = app_integrations.igdb_client_secret
    client = RetroAchievementsClient(api_key=current_user.retroachievements_api_key)
    username = current_user.retroachievements_username

    try:
        owned_games = await asyncio.to_thread(client.get_user_games, username)
    except RetroAchievementsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    semaphore = asyncio.Semaphore(_SYNC_CONCURRENCY)

    async def _fetch_progress(game_id: str) -> dict:
        async with semaphore:
            try:
                return await asyncio.to_thread(client.get_game_progress, username, game_id)
            except RetroAchievementsError:
                return {}

    game_ids = [str(entry.get("GameID")) for entry in owned_games if entry.get("GameID")]
    progress_results = await asyncio.gather(*(_fetch_progress(gid) for gid in game_ids))

    games_added = games_updated = achievements_synced = 0
    newly_created: list[Game] = []
    synced_titles: list[str] = []
    touched_ids: set[UUID] = set()
    for entry, progress in zip(owned_games, progress_results):
        title = entry.get("Title")
        if not title:
            continue
        game, created = await _get_or_create_game(
            db,
            current_user.id,
            title,
            "RetroAchievements",
            external_id=str(entry.get("GameID") or "") or None,
        )
        touched_ids.add(game.id)
        games_added += created
        games_updated += not created
        synced_titles.append(title)

        achievements = (progress or {}).get("Achievements") or {}
        rows = [
            {
                "external_id": str(ach_id),
                "name": ach.get("Title") or str(ach_id),
                "description": ach.get("Description"),
                "icon_url": f"https://media.retroachievements.org/Badge/{ach['BadgeName']}.png"
                if ach.get("BadgeName")
                else None,
                "unlocked": bool(ach.get("DateEarned") or ach.get("DateEarnedHardcore")),
                "unlocked_at": None,
                # RA's classic API's exact casing for this field isn't
                # documented as clearly as the newer v1 API's — check both
                "tier": (ach.get("Type") or ach.get("type") or "").lower() or None,
            }
            for ach_id, ach in achievements.items()
        ]
        await _replace_achievements(db, game.id, "RetroAchievements", rows)
        achievements_synced += len(rows)

        if created:
            unlocked_count = sum(1 for r in rows if r["unlocked"])
            _apply_status(
                game,
                _infer_status(total_achievements=len(rows), unlocked_achievements=unlocked_count),
            )
            _add_source_tag_and_collection(game, "RetroAchievements")
            newly_created.append(game)

    async def _enrich(game: Game) -> None:
        async with semaphore:
            await _enrich_new_game(
                game, current_user, preferences, igdb_client_id, igdb_client_secret
            )

    await asyncio.gather(*(_enrich(g) for g in newly_created))

    games_flagged_stale = await _flag_stale_games(
        db, current_user.id, "RetroAchievements", touched_ids
    )
    current_user.retroachievements_library_synced_at = int(time.time())
    await db.commit()
    return {
        "games_added": games_added,
        "games_updated": games_updated,
        "achievements_synced": achievements_synced,
        "games_flagged_stale": games_flagged_stale,
        "games": synced_titles,
    }


@router.post("/psn")
async def sync_psn_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not current_user.psn_npsso_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect your PlayStation account first.",
        )

    scan_settings = await get_or_create_scan_settings(current_user.id, db)
    preferences = _scan_settings_to_preferences(scan_settings)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    igdb_client_id = app_integrations.igdb_client_id
    igdb_client_secret = app_integrations.igdb_client_secret
    npsso = decrypt_secret(current_user.psn_npsso_token)
    client = PSNClient(npsso)

    try:
        titles = await asyncio.to_thread(client.get_owned_titles)
    except PSNError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    semaphore = asyncio.Semaphore(_SYNC_CONCURRENCY)

    async def _fetch_trophies(np_communication_id: str, platform: str) -> list[dict]:
        async with semaphore:
            service_name = "trophy2" if "PS5" in (platform or "") else "trophy"
            try:
                return await asyncio.to_thread(
                    client.get_trophies_for_title, np_communication_id, service_name
                )
            except PSNError:
                return []

    trophy_results = await asyncio.gather(
        *(
            _fetch_trophies(t.get("npCommunicationId", ""), t.get("trophyTitlePlatform", ""))
            for t in titles
            if t.get("npCommunicationId")
        )
    )

    games_added = games_updated = achievements_synced = 0
    newly_created: list[Game] = []
    synced_titles: list[str] = []
    touched_ids: set[UUID] = set()
    result_index = 0
    for entry in titles:
        title = entry.get("trophyTitleName")
        if not title or not entry.get("npCommunicationId"):
            continue
        trophies = trophy_results[result_index]
        result_index += 1

        game, created = await _get_or_create_game(
            db, current_user.id, title, "PlayStation", external_id=entry.get("npCommunicationId")
        )
        touched_ids.add(game.id)
        games_added += created
        games_updated += not created
        synced_titles.append(title)

        rows = [
            {
                "external_id": str(t.get("trophyId")),
                "name": t.get("trophyName") or "Trophy",
                "description": t.get("trophyDetail"),
                "icon_url": t.get("trophyIconUrl"),
                "unlocked": bool(t.get("earned")),
                "unlocked_at": None,
            }
            for t in trophies
            if t.get("trophyId") is not None
        ]
        await _replace_achievements(db, game.id, "PlayStation", rows)
        achievements_synced += len(rows)

        if created:
            unlocked_count = sum(1 for r in rows if r["unlocked"])
            _apply_status(
                game,
                _infer_status(total_achievements=len(rows), unlocked_achievements=unlocked_count),
            )
            _add_source_tag_and_collection(game, "PlayStation")
            newly_created.append(game)

    async def _enrich(game: Game) -> None:
        async with semaphore:
            await _enrich_new_game(
                game, current_user, preferences, igdb_client_id, igdb_client_secret
            )

    await asyncio.gather(*(_enrich(g) for g in newly_created))

    games_flagged_stale = await _flag_stale_games(db, current_user.id, "PlayStation", touched_ids)
    current_user.psn_library_synced_at = int(time.time())
    await db.commit()
    return {
        "games_added": games_added,
        "games_updated": games_updated,
        "achievements_synced": achievements_synced,
        "games_flagged_stale": games_flagged_stale,
        "games": synced_titles,
    }
