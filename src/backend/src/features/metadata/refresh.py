# pylint: disable=missing-function-docstring,too-many-locals,too-many-positional-arguments,broad-exception-caught,import-outside-toplevel,cyclic-import
"""Daily background refresh of episode data for shows/anime that already
have episodes synced — catches newly aired episodes for shows still
airing. Same in-process asyncio loop pattern as the trash sweep
(features/trash/sweep.py) and automatic backups
(features/backup/scheduler.py): no new worker container, no new
dependency. Mostly appends episode numbers that aren't already stored
and enriches blank placeholders — a watched or rated episode is never
touched. The one exception: a still-blank placeholder beyond what the
source provider now says has actually aired gets pruned (see
_prune_unaired_episodes), since that only happens from a prior
miscalculation, never from a real episode disappearing."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Any

from sqlalchemy import or_, select

from src.core.app_integrations import get_or_create_app_integration_settings
from src.core.crypto import decrypt_secret
from src.database.models.anime import Anime, AnimeEpisode, AnimeSeason, AnimeStatus
from src.database.models.tv_show import TVEpisode, TVSeason, TVShow, TVShowStatus
from src.database.session import SessionLocal
from src.features.episode_progress import materialize_progress
from src.features.metadata.anime.anilist import AniListClient, AniListError
from src.features.metadata.anime.episode_sync import (
    backfill_from_tmdb,
    fetch_airing_status,
    fetch_episodes_with_fallback,
    needs_tmdb_backfill,
    pad_to_known_total,
)
from src.features.metadata.anime.anizip import AniZipClient, AniZipError
from src.features.metadata.tv.episode_sync import (
    fetch_is_airing,
    fetch_next_episode,
    fetch_season_episodes,
)

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 24 * 60 * 60

# an airing show with no announced next episode is looked at this often, and
# any airing show at least this often, in case its schedule moved
RECHECK_UNKNOWN_SECONDS = 6 * 60 * 60
RECHECK_SCHEDULED_SECONDS = 24 * 60 * 60
# when each show was last asked about (in memory: a restart checks everything once)
_last_checked: dict[str, float] = {}


def _add_episode(
    model: type[AnimeEpisode] | type[TVEpisode], season_id, entry: dict
) -> AnimeEpisode | TVEpisode:
    raw_air_date = entry.get("air_date")
    return model(
        season_id=season_id,
        episode_number=entry["episode_number"],
        title=entry.get("title"),
        description=entry.get("description"),
        air_date=date.fromisoformat(raw_air_date) if raw_air_date else None,
        runtime_minutes=entry.get("runtime_minutes"),
        still_url=entry.get("still_url"),
        air_at=entry.get("air_at"),
    )


def _enrich_episode(existing: AnimeEpisode | TVEpisode, entry: dict) -> bool:
    """Fill in whatever the placeholder row is still missing from a fresh
    fetch — title being the main gate (a row synced before a TMDB key
    existed stays a bare "Episode N" until this runs again), but any
    other still-blank field is picked up too. Never overwrites a field
    that's already set. Returns whether anything actually changed."""
    changed = False
    if existing.title is None and entry.get("title") is not None:
        existing.title = entry["title"]
        changed = True
    if existing.description is None and entry.get("description") is not None:
        existing.description = entry["description"]
        changed = True
    if existing.air_date is None and entry.get("air_date"):
        existing.air_date = date.fromisoformat(entry["air_date"])
        changed = True
    if existing.runtime_minutes is None and entry.get("runtime_minutes") is not None:
        existing.runtime_minutes = entry["runtime_minutes"]
        changed = True
    if existing.air_at is None and entry.get("air_at") is not None:
        existing.air_at = entry["air_at"]
        changed = True
    if existing.still_url is None and entry.get("still_url") is not None:
        existing.still_url = entry["still_url"]
        changed = True
    return changed


def _prune_unaired_episodes(season: AnimeSeason, valid_numbers: set[int]) -> int:
    """Removes a still-blank placeholder row whose episode number the
    source provider no longer includes as aired — the only way that
    happens is a prior aired-count miscalculation created it too early
    (e.g. padding to a season's confirmed total instead of how many had
    actually aired). Never touches a watched or rated episode, and only
    called after a successful fetch, so a transient provider hiccup
    can't be mistaken for episodes disappearing."""
    removed = 0
    for episode in list(season.episodes):
        if episode.episode_number in valid_numbers:
            continue
        if episode.watched or episode.rating is not None:
            continue
        if episode.title is not None:
            continue
        season.episodes.remove(episode)
        removed += 1
    return removed


def _trim_beyond_total(season: AnimeSeason, total: int) -> int:
    """A season whose entry has finished airing with `total` episodes cannot
    have episode `total + 1`: rows numbered past it came from a provider that
    matched the wrong entry (season 1's list attached to season 2). They are
    removed unless the user watched or rated them, and the season's own count
    is set to the real total (or to the highest row that had to be kept)."""
    removed = 0
    for episode in list(season.episodes):
        if episode.episode_number <= total:
            continue
        if episode.watched or episode.rating is not None:
            continue
        season.episodes.remove(episode)
        removed += 1
    kept_top = max((e.episode_number for e in season.episodes), default=0)
    season.episode_count = max(total, kept_top)
    season.episodes_watched = min(season.episodes_watched or 0, season.episode_count)
    return removed


async def _refresh_anime_season(
    db,
    show: Anime,
    season: AnimeSeason,
    *,
    final_total: int | None = None,
    limit: int | None = None,
    total_known: bool = False,
) -> tuple[int, int]:
    """Returns (added, enriched) — added is brand-new episode numbers
    that didn't exist yet; enriched is existing bare placeholder rows
    that just got a real title/image now that better data is available
    (e.g. a TMDB key was added after the first sync). Also repairs a season
    a wrong provider match had inflated (see `_trim_beyond_total`)."""
    if not (show.external_id or show.anilist_id or show.kitsu_id):
        return 0, 0
    fetch = await fetch_episodes_with_fallback(
        show.external_id,
        show.anilist_id,
        show.kitsu_id,
        final_total=final_total,
        limit=limit,
        total_known=total_known,
    )
    all_episodes, errors = fetch.episodes, fetch.errors
    if fetch.kitsu_id and show.kitsu_id != fetch.kitsu_id:
        # ani.zip's exact id replaces one found by title search, which is how
        # season 2 ended up with season 1's Kitsu entry
        show.kitsu_id = fetch.kitsu_id
    if errors:
        logger.warning(
            "Anime refresh couldn't reach a provider for %r: %s", show.title, "; ".join(errors)
        )
    if not all_episodes:
        if fetch.limit:
            _trim_beyond_total(season, fetch.limit)
        return 0, 0
    # A finished entry is padded to its own total. Otherwise pad only up to
    # THIS fetch's highest episode number, never the stored total: feeding
    # that back in would re-inflate every fresh fetch to the same wrong number.
    target = fetch.final_total or max((e["episode_number"] for e in all_episodes), default=None)
    season.episode_count = pad_to_known_total(all_episodes, target)
    if needs_tmdb_backfill(all_episodes):
        app_integrations = await get_or_create_app_integration_settings(db)
        if app_integrations.tmdb_api_key:
            tmdb_api_key = decrypt_secret(app_integrations.tmdb_api_key)
            await backfill_from_tmdb(all_episodes, show.title, tmdb_api_key)
    existing_by_number = {e.episode_number: e for e in season.episodes}
    added = 0
    enriched = 0
    created: list[AnimeEpisode | TVEpisode] = []
    for entry in all_episodes:
        existing = existing_by_number.get(entry["episode_number"])
        if existing is None:
            row = _add_episode(AnimeEpisode, season.id, entry)
            db.add(row)
            created.append(row)
            added += 1
        elif _enrich_episode(existing, entry):
            enriched += 1
    materialize_progress(season, created)
    if fetch.limit:
        _trim_beyond_total(season, fetch.limit)
    # a show still airing has its rows kept in step by the airing check, which
    # adds up to what AniList says has aired; pruning here as well made the two
    # undo each other on every run
    if not errors and show.is_airing is not True:
        _prune_unaired_episodes(season, {e["episode_number"] for e in all_episodes})
    return added, enriched


async def quick_check_anime_season(show: Anime, season: AnimeSeason) -> int:
    """The cheap check for one anime: asks AniList how many episodes have
    aired (and whether it is still airing at all), and if the count has gone
    up, adds bare numbered placeholder rows (no title or thumbnail yet) so
    there is something to check off right away. The full refresh fills in real
    titles and images later. Only works for anime: MyAnimeList/Jikan has no
    comparably cheap endpoint."""
    if not show.anilist_id:
        return 0
    aired_total, is_airing, air_at, next_number, errors = await fetch_airing_status(show.anilist_id)
    if errors:
        logger.warning(
            "Airing check couldn't reach AniList for %r: %s", show.title, "; ".join(errors)
        )
        return 0
    return await _apply_airing(show, season, aired_total, is_airing, air_at, next_number)


async def _apply_airing(
    show: Anime,
    season: AnimeSeason,
    aired_total: int | None,
    is_airing: bool,
    air_at: int | None,
    next_number: int | None,
) -> int:
    """Stores what AniList says about a show (persisting `is_airing` either way,
    so a finished show is left alone from then on) and adds the placeholder
    rows for episodes that have aired. Returns how many rows were added."""
    show.is_airing = is_airing
    show.next_episode_air_at = air_at
    show.next_episode_number = next_number
    if not aired_total:
        return 0
    known_max = max((e.episode_number for e in season.episodes), default=0)
    added = 0
    if aired_total > known_max:
        for n in range(known_max + 1, aired_total + 1):
            season.episodes.append(AnimeEpisode(season_id=season.id, episode_number=n))
            added += 1
        materialize_progress(season)
        if season.episode_count is None or season.episode_count < aired_total:
            season.episode_count = aired_total
    if is_airing and show.anilist_id:
        await _fill_recent_from_anizip(season, show.anilist_id)
    return added


async def _fill_recent_from_anizip(season: AnimeSeason, anilist_id: str) -> None:
    """One ani.zip call fills the title, screenshot, synopsis and exact
    air time of the newest episodes, which is what makes a freshly aired
    episode look finished within a check cycle instead of staying a bare
    "Episode N" until the daily full refresh. Only runs when one of the
    newest few episodes is actually missing something."""
    recent = sorted(season.episodes, key=lambda e: e.episode_number)[-4:]
    if not any(e.title is None or e.still_url is None or e.air_at is None for e in recent):
        return
    try:
        entries = await asyncio.to_thread(AniZipClient().episodes, anilist_id)
    except AniZipError as exc:
        logger.warning("ani.zip unavailable while filling recent episodes: %s", exc)
        return
    by_number = {e["episode_number"]: e for e in entries}
    for episode in recent:
        entry = by_number.get(episode.episode_number)
        if entry:
            _enrich_episode(episode, entry)


async def refresh_anime_season_now(db, show: Anime, season: AnimeSeason) -> tuple[int, int]:
    """The full episode refresh for one season on demand (the Check airing
    button), not only the cheap airing-count check."""
    return await _refresh_anime_season(db, show, season)


async def refresh_tv_season_now(show: TVShow, season: TVSeason, db) -> tuple[int, int]:
    return await _refresh_tv_season(show, season, db)


async def quick_check_tv_season(show: TVShow, season: TVSeason, db) -> int:
    """The frequent, cheap check for TV: first asks TVmaze just the
    show's status (a single small object) and persists `show.is_airing`
    from it. Only when it's actually still running does it bother with
    the (still cheap, but heavier) full episode fetch — a finished show
    gets excluded from the query entirely on the next pass instead of
    being re-fetched every cycle forever."""
    if not show.external_id:
        return 0
    is_airing, errors = await fetch_is_airing(show.external_id)
    if errors:
        logger.warning(
            "Airing check couldn't reach TVmaze for %r: %s", show.title, "; ".join(errors)
        )
        return 0
    if is_airing is not None:
        show.is_airing = is_airing
    if is_airing is False:
        show.next_episode_air_at = None
        show.next_episode_number = None
        return 0
    air_at, next_number, next_errors = await fetch_next_episode(show.external_id)
    if not next_errors:
        show.next_episode_air_at = air_at
        show.next_episode_number = next_number
    added, _enriched = await _refresh_tv_season(show, season, db)
    return added


async def _refresh_tv_season(show: TVShow, season: TVSeason, db) -> tuple[int, int]:
    """Returns (added, enriched) — TV rarely has bare placeholders (no
    padding step for TV, unlike anime), but the same enrich pass runs
    anyway so a row TVmaze had gaps in the first time still gets picked
    up if the gap closes later."""
    if not show.external_id:
        return 0, 0
    all_episodes, errors = await fetch_season_episodes(show.external_id, season.season_number)
    if errors:
        logger.warning("TV refresh couldn't reach TVmaze for %r: %s", show.title, "; ".join(errors))
    existing_by_number = {e.episode_number: e for e in season.episodes}
    added = 0
    enriched = 0
    created: list[AnimeEpisode | TVEpisode] = []
    for entry in all_episodes:
        existing = existing_by_number.get(entry["episode_number"])
        if existing is None:
            row = _add_episode(TVEpisode, season.id, entry)
            db.add(row)
            created.append(row)
            added += 1
        elif _enrich_episode(existing, entry):
            enriched += 1
    materialize_progress(season, created)
    return added, enriched


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def _find_by_exact_title(
    client: AniListClient, title: str, year: int | None = None
) -> dict[str, Any] | None:
    """A show with neither id at all (added by hand, or added while both
    AniList and Jikan were unreachable) has nothing to look up BY —
    the only way to recover an id for one is a fresh title search, which
    is exactly the kind of lookup that created these gaps elsewhere (a
    loose match can land on the wrong entry). The risk is contained here
    by requiring an EXACT title match (case/whitespace-insensitive) among
    the search results and refusing anything looser — a real title, not
    a guess, or nothing at all.

    Title alone still isn't always enough: an early OVA/movie and a much
    later TV series in the same franchise can share the exact same
    display title (confirmed for real on Kitsu — see `KitsuClient.
    find_exact`'s docstring — and the same shape of ambiguity can happen
    here), so a title-only match can silently pick the wrong decades-
    apart entry. When `year` is known, a candidate more than a year off
    is rejected even though its title matched."""
    try:
        results = client.search(title, limit=5)
    except AniListError:
        return None
    target = _normalize_title(title)
    for entry in results:
        if _normalize_title(entry.get("title") or "") != target:
            continue
        if year is not None:
            release_date = entry.get("release_date") or ""
            entry_year = int(release_date[:4]) if release_date[:4].isdigit() else None
            if entry_year is None or abs(entry_year - year) > 1:
                continue
        return entry
    return None


def _find_anime_entry(client: AniListClient, show: Anime) -> dict[str, Any] | None:
    """Looks up the one AniList entry to heal `show` from — a known id
    over a fresh title search, since a title search is what creates these
    gaps in the first place (an unusual title can miss or match the wrong
    entry), so it's not trustworthy once a real id is already on hand.
    Prefers the stored AniList id; when only a MyAnimeList id is known
    (added while AniList itself was unreachable/rate-limited, so only
    Jikan matched), looks it up by that instead. A show with NEITHER id
    falls back to an exact-title-match search rather than being left
    permanently unhealable — this is the common case for anything added
    by hand or added while both providers were down."""
    if show.anilist_id:
        try:
            return client.get_by_id(int(show.anilist_id))
        except (AniListError, ValueError):
            return None
    if show.external_id:
        try:
            return client.get_by_mal_id(int(show.external_id))
        except (AniListError, ValueError):
            return None
    year = show.first_air_date.year if show.first_air_date else None
    return _find_by_exact_title(client, show.title, year)


# (show attribute, entry key) pairs backfilled only when the show's own
# field is still blank — id fields are handled separately since they
# need str(...) conversion and the season episode count lives one level
# down, not a plain attribute of `show` itself.
_HEALABLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("format", "format"),
    ("poster_url", "poster_url"),
    ("backdrop_url", "backdrop_url"),
    ("description", "overview"),
    ("studios", "studios"),
    ("genres", "genres"),
    ("episode_runtime_minutes", "episode_runtime_minutes"),
)


def _heal_anime_metadata(client: AniListClient, show: Anime) -> bool:
    """Backfills whichever of format/poster/backdrop/description/studios/
    genres/runtime/score/anilist_id/external_id/kitsu_id are still null.
    Recovers whichever of the AniList/MyAnimeList ids was still missing
    from `_find_anime_entry` — AniList's own data carries MyAnimeList's
    id for the same entry (`idMal`), and a show missing that id can only
    ever get Jikan's richer per-episode data (titles/synopses/air-dates)
    once it's recovered. Kitsu has no such cross-reference, so its id is
    recovered separately via its own exact-title search. Returns whether
    anything actually changed."""
    changed = False

    entry = _find_anime_entry(client, show)
    if entry:
        if show.anilist_id is None and entry.get("id"):
            show.anilist_id = str(entry["id"])
            changed = True
        if show.external_id is None and entry.get("id_mal"):
            show.external_id = str(entry["id_mal"])
            changed = True
        for attr, key in _HEALABLE_FIELDS:
            if not getattr(show, attr) and entry.get(key):
                setattr(show, attr, entry[key])
                changed = True
        if show.anilist_score is None and entry.get("score") is not None:
            show.anilist_score = entry["score"]
            changed = True
        if entry.get("episode_count") and show.seasons and show.seasons[0].episode_count is None:
            show.seasons[0].episode_count = entry["episode_count"]
            changed = True

    # A Kitsu id is never guessed from the title here: a title search matched
    # season 1's entry for season 2. ani.zip gives the exact id when episodes
    # are refreshed (see `_refresh_anime_season`).
    return changed


async def heal_all_anime_metadata() -> int:
    """Sweeps every non-deleted anime row for one missing enough to be
    worth a lookup (no format, poster, AniList id, MyAnimeList id, or
    Kitsu id yet) and backfills it — the self-healing counterpart to the
    manual "delete and re-add" fix a title with a failed metadata match
    used to need. Missing `external_id`/`kitsu_id` are included because
    they silently cap episode quality forever otherwise: without them,
    episode sync can only ever use whichever provider's id it does have,
    never merge in the other two's data. A show with NEITHER AniList nor
    MyAnimeList id (added by hand, or added while both providers were
    unreachable) is not skipped either — `_heal_anime_metadata` falls
    back to an exact-title search for those, which is the majority of
    what's actually stuck with zero episode data, since episode sync has
    nothing to look up at all without at least one real id. A small
    pause between rows paces requests the same way the relations chain
    walk does, so a large backlog doesn't burn through AniList's rate
    limit in one burst."""
    healed = 0
    client = AniListClient()
    async with SessionLocal() as db:
        shows = (
            (
                await db.execute(
                    select(Anime).where(
                        Anime.deleted_at.is_(None),
                        or_(
                            Anime.format.is_(None),
                            Anime.poster_url.is_(None),
                            Anime.anilist_id.is_(None),
                            Anime.external_id.is_(None),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for show in shows:
            await asyncio.sleep(0.3)
            try:
                if _heal_anime_metadata(client, show):
                    healed += 1
            except Exception:
                logger.exception("Anime metadata heal failed for %s", show.title)
        await db.commit()
    if healed:
        logger.info("Metadata heal: backfilled %d anime row(s)", healed)
    return healed


async def refresh_all_episode_metadata() -> dict[str, int]:
    """The full refresh, run to the end (the daily loop uses this). It only
    touches what needs it; see refresh_job for the details and for the version
    the Settings button starts with progress. If a run is already going, this
    returns that run's progress instead of starting another."""
    from src.features.metadata import refresh_job

    progress = await refresh_job.run("needed")
    return {
        "anime_episodes_added": progress["anime_episodes_added"],
        "anime_episodes_updated": progress["anime_episodes_updated"],
        "tv_episodes_added": progress["tv_episodes_added"],
        "tv_episodes_updated": progress["tv_episodes_updated"],
        "anime_metadata_healed": progress["anime_metadata_healed"],
        "counts_fixed": progress["counts_fixed"],
    }


def airing_due(
    is_airing: bool | None, next_air_at: int | None, last_checked: float | None, now: float
) -> bool:
    """Whether a show is worth asking a provider about right now. A new
    episode can only appear once the scheduled one has aired, so a show whose
    next episode is still in the future is left alone, except for an occasional
    look in case the schedule moved. One never checked is always due."""
    if is_airing is None:
        return True
    if next_air_at and next_air_at <= now:
        return True
    limit = RECHECK_SCHEDULED_SECONDS if next_air_at else RECHECK_UNKNOWN_SECONDS
    return last_checked is None or now - last_checked >= limit


async def check_airing_episodes(force: bool = False) -> dict[str, int]:
    """The frequent, lightweight pass over shows that are airing or not yet
    checked (`is_airing` true or null); one known to have finished, or a
    dropped one, is skipped entirely. Only the shows that are due (see
    `airing_due`, or all of them with `force`) are asked about: anime in one
    AniList request per 50 shows, TV one show at a time. Their episodes are
    loaded only then, not for every airing show on every pass. Neither does the
    TMDB backfill, which stays on the slower full refresh."""
    now = time.time()
    anime_added = tv_added = checked = candidates = 0
    async with SessionLocal() as db:
        anime_rows = (
            await db.execute(
                select(
                    Anime.id, Anime.anilist_id, Anime.is_airing, Anime.next_episode_air_at
                ).where(
                    Anime.deleted_at.is_(None),
                    Anime.status != AnimeStatus.DROPPED,
                    or_(Anime.is_airing.is_(True), Anime.is_airing.is_(None)),
                )
            )
        ).all()
        candidates += len(anime_rows)
        due = {
            r.id: int(r.anilist_id)
            for r in anime_rows
            if r.anilist_id
            and str(r.anilist_id).isdigit()
            and (
                force
                or airing_due(r.is_airing, r.next_episode_air_at, _last_checked.get(str(r.id)), now)
            )
        }
        if due:
            infos = await asyncio.to_thread(AniListClient().final_totals, sorted(set(due.values())))
            shows = (await db.execute(select(Anime).where(Anime.id.in_(list(due))))).scalars().all()
            for anime_show in shows:
                info = infos.get(due[anime_show.id])
                season = anime_show.seasons[-1] if anime_show.seasons else None
                if info is None or season is None or not season.episodes:
                    continue
                upcoming = info.get("next")
                aired_total = upcoming - 1 if upcoming else info.get("episodes")
                try:
                    anime_added += await _apply_airing(
                        anime_show,
                        season,
                        aired_total,
                        bool(upcoming),
                        info.get("air_at"),
                        upcoming,
                    )
                    _last_checked[str(anime_show.id)] = now
                    checked += 1
                except Exception:
                    logger.exception("Airing check failed for anime %s", anime_show.title)

        tv_rows = (
            await db.execute(
                select(TVShow.id, TVShow.is_airing, TVShow.next_episode_air_at).where(
                    TVShow.deleted_at.is_(None),
                    TVShow.status != TVShowStatus.DROPPED,
                    or_(TVShow.is_airing.is_(True), TVShow.is_airing.is_(None)),
                )
            )
        ).all()
        candidates += len(tv_rows)
        tv_due = [
            r.id
            for r in tv_rows
            if force
            or airing_due(r.is_airing, r.next_episode_air_at, _last_checked.get(str(r.id)), now)
        ]
        if tv_due:
            tv_shows = (
                (await db.execute(select(TVShow).where(TVShow.id.in_(tv_due)))).scalars().all()
            )
            for tv_show in tv_shows:
                tv_season = tv_show.seasons[-1] if tv_show.seasons else None
                if tv_season is None or not tv_season.episodes:
                    continue
                try:
                    tv_added += await quick_check_tv_season(tv_show, tv_season, db)
                    _last_checked[str(tv_show.id)] = now
                    checked += 1
                except Exception:
                    logger.exception("Airing check failed for TV show %s", tv_show.title)

        await db.commit()

    if anime_added or tv_added:
        logger.info(
            "Airing check added %d anime episode(s), %d TV episode(s)", anime_added, tv_added
        )
    return {
        "anime_episodes_added": anime_added,
        "tv_episodes_added": tv_added,
        "checked": checked,
        "not_due": max(0, candidates - checked),
    }
