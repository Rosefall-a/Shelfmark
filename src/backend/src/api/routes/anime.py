# pylint: disable=duplicate-code
# These modules intentionally keep domain/provider-specific logic separate; similar
# structures here represent parallel APIs rather than accidental copy/paste.

"""API routes for managing anime and their seasons."""

import asyncio
import logging
import re
import time
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.pagination import PaginatedResponse
from src.api.schemas.anime import (
    AnimeCreate,
    AnimeLibraryRead,
    AnimeRead,
    AnimeUpdate,
    EpisodesBulkWatched,
    EpisodeUpdate,
    SeasonCreate,
    SeasonUpdate,
)
from src.api.routes.media_extras import log_activity, status_change_detail
from src.core.app_integrations import get_or_create_app_integration_settings
from src.core.auth import get_current_user
from src.core.integrations import resolve_integrations
from src.core.titles import apply_alt_titles
from src.features.metadata.anime.alt_titles import fill_missing_titles
from src.database.models.anime import Anime, AnimeEpisode, AnimeSeason, AnimeStatus
from src.database.models.media_extras import ActivityEventType
from src.database.models.user import User
from src.database.session import SessionLocal, get_db
from src.features.metadata.anime.anilist import RELATIONS_CACHE_VERSION, AniListClient, AniListError
from src.features.metadata.anime.episode_sync import (
    backfill_from_tmdb,
    fetch_episodes_with_fallback,
    needs_tmdb_backfill,
    pad_to_known_total,
)
from src.features.metadata.anime.search import (
    get_anime_metadata_by_anilist_id,
    search_anime_metadata,
)
from src.features.episode_progress import apply_counter, counter_from_flags, materialize_progress
from src.features.metadata.locked_fields import apply_updates_with_locking
from src.features.notifications import record_sequel_announcements
from src.features.metadata.refresh import quick_check_anime_season, refresh_anime_season_now

router = APIRouter(prefix="/api/anime", tags=["anime"], dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

# fields the metadata search's "Apply" button can fill in — the only ones
# worth locking, since nothing else is ever set by that flow
_LOCKABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "first_air_date",
        "episode_runtime_minutes",
        "studios",
        "genres",
        "poster_url",
        "backdrop_url",
        "anilist_score",
        "mal_score",
    }
)


class AnimeMetadataSearchResponse(BaseModel):
    query: str
    providers: list[str]
    provider_errors: list[str] = []
    results: list[dict]


_LEADING_ARTICLE = re.compile(r"^(a|an|the)\s+", flags=re.IGNORECASE)


def _derive_sort_title(title: str) -> str:
    """'The Melancholy of Haruhi Suzumiya' -> 'melancholy of haruhi suzumiya'."""
    return _LEADING_ARTICLE.sub("", title).strip().lower()


async def _get_show_or_404(
    show_id: UUID, db: AsyncSession, user_id: UUID, include_deleted: bool = False
) -> Anime:
    # populate_existing: a show already in this session's identity map
    # (e.g. loaded earlier in the same request, before a season was just
    # added to it) would otherwise keep its stale, already-cached
    # `seasons` collection instead of picking up the new row
    stmt = (
        select(Anime)
        .where(Anime.id == show_id, Anime.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if not include_deleted:
        stmt = stmt.where(Anime.deleted_at.is_(None))
    show = await db.scalar(stmt)
    if show is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Anime {show_id} not found"
        )
    return show


async def _get_season_or_404(season_id: UUID, show_id: UUID, db: AsyncSession) -> AnimeSeason:
    season = await db.scalar(
        select(AnimeSeason).where(AnimeSeason.id == season_id, AnimeSeason.show_id == show_id)
    )
    if season is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Season {season_id} not found"
        )
    return season


class AniListImportRequest(BaseModel):
    username: str
    update_existing: bool = False


class AniListImportResult(BaseModel):
    fetched: int
    created: int
    updated: int
    skipped: int
    errors: list[str] = []


@router.post("/import/anilist", response_model=AniListImportResult)
async def import_anilist_library(
    payload: AniListImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AniListImportResult:
    """Import a public AniList anime list without modifying AniList."""
    from src.features.metadata.anime.anilist_import import AniListImportClient

    try:
        entries = await asyncio.to_thread(AniListImportClient().fetch_user_anime, payload.username)
    except AniListError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    created = updated = skipped = 0
    errors: list[str] = []
    for entry in entries:
        try:
            show = await db.scalar(
                select(Anime).where(
                    Anime.user_id == current_user.id,
                    Anime.anilist_id == entry["anilist_id"],
                    Anime.deleted_at.is_(None),
                )
            )
            if show is not None and not payload.update_existing:
                skipped += 1
                continue

            def parsed(key: str):
                value = entry[key]
                return date.fromisoformat(value) if value else None

            season: AnimeSeason | None = None
            if show is None:
                show = Anime(
                    user_id=current_user.id,
                    title=entry["title"],
                    sort_title=_derive_sort_title(entry["title"]),
                    description=entry["description"],
                    first_air_date=parsed("first_air_date"),
                    episode_runtime_minutes=entry["episode_runtime_minutes"],
                    studios=entry["studios"],
                    countries=entry["countries"],
                    languages=[],
                    genres=entry["genres"],
                    tags=[],
                    features=[],
                    format=entry["format"],
                    anilist_score=entry["anilist_score"],
                    anilist_id=entry["anilist_id"],
                    poster_url=entry["poster_url"],
                    backdrop_url=entry["backdrop_url"],
                    status=entry["status"],
                    priority=entry["priority"],
                    rewatches=entry["repeat"],
                    note=entry["note"],
                    start_date=parsed("start_date"),
                    end_date=parsed("end_date"),
                    rating_overall=entry["rating_overall"],
                )
                db.add(show)
                await db.flush()
                season = AnimeSeason(
                    show_id=show.id,
                    season_number=1,
                    episode_count=entry["episode_count"],
                    episodes_watched=entry["progress"],
                    status=entry["status"],
                )
                db.add(season)
                created += 1
            else:
                show.sort_title = _derive_sort_title(entry["title"])
                for field in (
                    "title",
                    "description",
                    "first_air_date",
                    "episode_runtime_minutes",
                    "studios",
                    "countries",
                    "genres",
                    "format",
                    "anilist_score",
                    "poster_url",
                    "backdrop_url",
                    "status",
                    "priority",
                    "rewatches",
                    "note",
                    "start_date",
                    "end_date",
                    "rating_overall",
                ):
                    setattr(
                        show,
                        field,
                        parsed(field)
                        if field in ("first_air_date", "start_date", "end_date")
                        else entry[field],
                    )
                season = show.seasons[0] if show.seasons else None
                if season is None:
                    season = AnimeSeason(show_id=show.id, season_number=1)
                    db.add(season)
                season.episode_count = entry["episode_count"]
                season.episodes_watched = entry["progress"]
                season.status = entry["status"]
                updated += 1
            await db.commit()
        except Exception as exc:
            await db.rollback()
            skipped += 1
            errors.append(f"{entry.get('title', 'Unknown title')}: {exc}")
    return AniListImportResult(
        fetched=len(entries), created=created, updated=updated, skipped=skipped, errors=errors[:20]
    )


@router.get("/metadata/search", response_model=AnimeMetadataSearchResponse)
async def search_metadata(
    query: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(default=8, ge=1, le=20),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Search AniList and Jikan (MyAnimeList) for data that can prefill a
    new entry. Both are public/keyless — no app-wide credentials needed,
    unlike Movies/TV's TMDB and OMDb."""
    del current_user
    try:
        result = await asyncio.to_thread(search_anime_metadata, query.strip(), limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Metadata providers could not be reached: {exc}",
        ) from exc
    return result


@router.post("/fill-titles")
async def fill_alternate_titles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Looks up the English, romaji and Japanese spelling of every anime of
    yours that has none stored yet (see alt_titles.fill_missing_titles). The
    media refresh does the same for everyone, so this is only needed to do it
    right now."""
    return await fill_missing_titles(db, current_user.id)


@router.get("/metadata/by-id/{anilist_id}", response_model=dict | None)
async def get_metadata_by_id(
    anilist_id: int,
    current_user: User = Depends(get_current_user),
) -> dict | None:
    """Looks up one exact AniList entry by id, in the same shape
    `/metadata/search` returns per result — used when adding a title from
    the Related/Recommended graph, which already carries a real AniList
    id and shouldn't need a fresh title search to find the same entry
    again (fragile for an unusual title, and wasted requests against an
    API with a real rate limit)."""
    del current_user
    try:
        result = await asyncio.to_thread(get_anime_metadata_by_anilist_id, anilist_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AniList could not be reached: {exc}",
        ) from exc
    return result


@router.post("/create", response_model=AnimeRead, status_code=status.HTTP_201_CREATED)
async def create_anime(
    payload: AnimeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    """Create an anime entry, optionally bulk-creating its seasons in the
    same transaction. If `seasons` is omitted entirely (not just an empty
    list), a default "Season 1" is created automatically — most anime
    never gets a second season added by hand, unlike TV shows."""
    data = payload.model_dump(exclude={"seasons"})
    if not data.get("sort_title"):
        data["sort_title"] = _derive_sort_title(data["title"])

    show = Anime(**data, user_id=current_user.id)
    db.add(show)
    await db.flush()

    # keep the English/romaji/Japanese spellings when the entry has an AniList
    # id; best-effort, a slow AniList never blocks creation
    if (
        show.anilist_id
        and show.anilist_id.isdigit()
        and not (show.title_english or show.title_romaji or show.title_native)
    ):
        try:
            found, _ = await asyncio.to_thread(AniListClient().get_by_ids, [int(show.anilist_id)])
            if meta := found.get(int(show.anilist_id)):
                apply_alt_titles(show, meta)
        except Exception:
            logger.exception("Alternate titles lookup failed for new anime %r", show.title)

    if payload.seasons is None:
        first_season = AnimeSeason(season_number=1, show_id=show.id)
        db.add(first_season)
    else:
        first_season = None
        for season_input in payload.seasons:
            season = AnimeSeason(**season_input.model_dump(), show_id=show.id)
            db.add(season)
            if first_season is None:
                first_season = season

    # Otherwise a freshly-added airing show shows no next-episode date
    # anywhere (countdown, calendar) until the next periodic airing-check
    # pass, up to one airing-check interval later — worth the one
    # extra AniList call at creation time so it's there immediately.
    # Best-effort: a slow/unreachable AniList never blocks creation.
    if show.anilist_id and first_season is not None:
        try:
            await quick_check_anime_season(show, first_season)
        except Exception:
            logger.exception("Immediate airing check failed for new anime %r", show.title)

    await db.commit()
    if show.anilist_id:
        # store its franchise graph now, off the request, so Seasons/Related
        # are ready the first time the title is opened
        asyncio.create_task(refresh_relations_in_background(show.id))
    return await _get_show_or_404(show.id, db, current_user.id)


@router.post("/{show_id}/refresh-airing", response_model=AnimeRead)
async def refresh_airing(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    """Runs the airing check for just this title right now (the background
    loop only comes around every 30 minutes) — updates the next-episode
    date/number and adds placeholder rows for anything newly aired."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    if not show.anilist_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This title has no AniList id, so its airing schedule can't be checked.",
        )
    if show.seasons:
        season = show.seasons[-1]
        await quick_check_anime_season(show, season)
        await refresh_anime_season_now(db, show, season)
        await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.get("/list", response_model=PaginatedResponse[AnimeLibraryRead])
async def list_anime(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: AnimeStatus | None = Query(default=None, alias="status"),
    favorite: bool | None = Query(default=None),
    search: str | None = Query(default=None, description="Case-insensitive title search"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
)-> PaginatedResponse[AnimeLibraryRead]:
    """Return one page of the current user's anime and the total matching it."""
    stmt = select(Anime).where(Anime.user_id == current_user.id, Anime.deleted_at.is_(None))

    if status_filter is not None:
        stmt = stmt.where(Anime.status == status_filter)
    if favorite is not None:
        stmt = stmt.where(Anime.favorite == favorite)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Anime.title.ilike(pattern),
                Anime.title_english.ilike(pattern),
                Anime.title_romaji.ilike(pattern),
                Anime.title_native.ilike(pattern),
            )
        )

    status_count_stmt = select(Anime.status, func.count()).where(
        Anime.user_id == current_user.id, Anime.deleted_at.is_(None)
    )
    if favorite is not None:
        status_count_stmt = status_count_stmt.where(Anime.favorite == favorite)
    if search:
        status_count_stmt = status_count_stmt.where(Anime.title.ilike(f"%{search}%"))
    status_counts_result = await db.execute(status_count_stmt.group_by(Anime.status))
    status_counts = {status.value: count for status, count in status_counts_result.all()}

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(Anime.sort_title).offset(skip).limit(limit)

    result = await db.execute(stmt)
    items = list(result.scalars().unique().all())
    return PaginatedResponse(
        items=items,
        total=total or 0,
        offset=skip,
        limit=limit,
        status_counts=status_counts,
    )


@router.get("/get/{show_id}", response_model=AnimeRead)
async def get_anime(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    """Return one anime by ID, with its seasons."""
    return await _get_show_or_404(show_id, db, current_user.id)


@router.patch("/update/{show_id}", response_model=AnimeRead)
async def update_anime(
    show_id: UUID,
    payload: AnimeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    """Update an anime entry and keep its derived sort title synchronized."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    previous_status = show.status

    updates = payload.model_dump(exclude_unset=True)

    apply_updates_with_locking(show, updates, _LOCKABLE_FIELDS)

    if "title" in updates and "sort_title" not in updates:
        show.sort_title = _derive_sort_title(show.title)

    if "status" in updates and show.status != previous_status:
        change = status_change_detail(previous_status, show.status)
        if change:
            await log_activity(
                db,
                current_user.id,
                "anime",
                show.id,
                show.title,
                ActivityEventType.STATUS_CHANGED,
                date.today(),
                detail=change,
            )

    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.delete("/delete/{show_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_anime(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Soft-delete an anime entry by ID (its seasons stay attached, hidden along with it)."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    show.deleted_at = int(time.time())
    await db.commit()


@router.get("/trash")
async def list_anime_trash(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Deleted anime entries, most recently deleted first. No purge job
    runs against these — unlike Game's on-disk folders, an entry is just
    a row (plus its seasons/episodes), so there's nothing to clean up
    and it stays here until an admin either restores it or purges it."""
    result = await db.execute(
        select(Anime)
        .where(Anime.user_id == current_user.id, Anime.deleted_at.is_not(None))
        .order_by(Anime.deleted_at.desc())
    )
    trashed = []
    for show in result.scalars().all():
        assert show.deleted_at is not None  # guaranteed by the deleted_at.is_not(None) filter above
        trashed.append({"id": str(show.id), "title": show.title, "deleted_at": show.deleted_at})
    return trashed


@router.post("/{show_id}/restore", response_model=AnimeRead)
async def restore_anime(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    show = await _get_show_or_404(show_id, db, current_user.id, include_deleted=True)
    if show.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entry isn't deleted.")
    show.deleted_at = None
    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.delete("/{show_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_anime(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Permanently removes an already-deleted anime entry and its
    seasons/episodes. Only reachable from trash — an entry still active
    must be soft-deleted first."""
    show = await _get_show_or_404(show_id, db, current_user.id, include_deleted=True)
    if show.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entry isn't deleted.")
    await db.delete(show)
    await db.commit()


@router.post("/{show_id}/seasons", response_model=AnimeRead, status_code=status.HTTP_201_CREATED)
async def create_season(
    show_id: UUID,
    payload: SeasonCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    show = await _get_show_or_404(show_id, db, current_user.id)
    db.add(AnimeSeason(**payload.model_dump(), show_id=show.id))
    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.patch("/{show_id}/seasons/{season_id}", response_model=AnimeRead)
async def update_season(
    show_id: UUID,
    season_id: UUID,
    payload: SeasonUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    show = await _get_show_or_404(show_id, db, current_user.id)
    season = await _get_season_or_404(season_id, show_id, db)

    updates = payload.model_dump(exclude_unset=True)
    old_counter = season.episodes_watched or 0
    for field, value in updates.items():
        setattr(season, field, value)

    if "episodes_watched" in updates:
        new_counter = season.episodes_watched or 0
        apply_counter(season, new_counter)
        if new_counter > old_counter:
            # advancing from the library counts as watching, same as
            # checking episodes off on the title page
            await log_activity(
                db,
                current_user.id,
                "anime",
                show.id,
                show.title,
                ActivityEventType.EPISODES_WATCHED,
                date.today(),
                increment=new_counter - old_counter,
            )

    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.delete("/{show_id}/seasons/{season_id}", response_model=AnimeRead)
async def delete_season(
    show_id: UUID,
    season_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    await _get_show_or_404(show_id, db, current_user.id)
    season = await _get_season_or_404(season_id, show_id, db)
    await db.delete(season)
    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


async def _backfill_from_tmdb_if_configured(
    all_episodes: list[dict[str, Any]], show_title: str, db: AsyncSession
) -> None:
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    if app_integrations.tmdb_api_key:
        tmdb_api_key = app_integrations.tmdb_api_key
        await backfill_from_tmdb(all_episodes, show_title, tmdb_api_key)


async def _get_episode_or_404(episode_id: UUID, season_id: UUID, db: AsyncSession) -> AnimeEpisode:
    episode = await db.scalar(
        select(AnimeEpisode).where(
            AnimeEpisode.id == episode_id, AnimeEpisode.season_id == season_id
        )
    )
    if episode is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Episode {episode_id} not found"
        )
    return episode


@router.get("/{show_id}/seasons/{season_id}/episodes", response_model=AnimeRead)
async def list_episodes(
    show_id: UUID,
    season_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    """Return the season's episodes, syncing them in on the very first
    request. Fetches from every provider with a known id (Jikan, AniList,
    Kitsu) and merges their results per field rather than using one as a
    strict fallback for another — see `fetch_episodes_with_fallback`.
    Nothing to sync from if no id is set at all (added by hand, or found
    by no provider). Every later call reads straight from the table
    instead of re-fetching."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    season = await _get_season_or_404(season_id, show_id, db)

    if not season.episodes and (show.external_id or show.anilist_id or show.kitsu_id):
        fetch = await fetch_episodes_with_fallback(show.external_id, show.anilist_id, show.kitsu_id)
        all_episodes, errors = fetch.episodes, fetch.errors
        if fetch.kitsu_id and show.kitsu_id != fetch.kitsu_id:
            show.kitsu_id = fetch.kitsu_id
        if not all_episodes and errors:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not sync episodes: {'; '.join(errors)}",
            )
        # Pad gaps up to THIS fetch's own highest episode number, never
        # the season's stored total — feeding that back in would
        # re-inflate every fresh fetch back up to the same wrong number
        # forever (e.g. once padded to a confirmed-but-not-fully-aired
        # count before that bug was fixed).
        fresh_total = fetch.final_total or max(
            (e["episode_number"] for e in all_episodes), default=None
        )
        season.episode_count = pad_to_known_total(all_episodes, fresh_total)
        if needs_tmdb_backfill(all_episodes):
            await _backfill_from_tmdb_if_configured(all_episodes, show.title, db)
        created = []
        for entry in all_episodes:
            raw_air_date = entry.get("air_date")
            row = AnimeEpisode(
                season_id=season.id,
                episode_number=entry["episode_number"],
                title=entry.get("title"),
                description=entry.get("description"),
                air_date=date.fromisoformat(raw_air_date) if raw_air_date else None,
                runtime_minutes=entry.get("runtime_minutes"),
                still_url=entry.get("still_url"),
            )
            db.add(row)
            created.append(row)
        materialize_progress(season, created)
        await db.commit()

    return await _get_show_or_404(show_id, db, current_user.id)


@router.patch("/{show_id}/seasons/{season_id}/episodes/bulk-watched", response_model=AnimeRead)
async def bulk_set_episodes_watched(
    show_id: UUID,
    season_id: UUID,
    payload: EpisodesBulkWatched,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    """Sets `watched` on a whole batch of episodes in one request — a
    shift-click range select or "mark watched up to here" would
    otherwise cost one PATCH per episode, which gets genuinely slow on a
    500+ episode season. Silently ignores any id that isn't actually in
    this season rather than 404ing the whole batch over one bad id.
    Registered ahead of the single-episode PATCH below so the literal
    path segment "bulk-watched" is matched here rather than attempted as
    an `episode_id` UUID."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    season = await _get_season_or_404(season_id, show_id, db)
    ids = set(payload.episode_ids)
    newly_watched = 0
    # progress the counter already held is flagged first, so it is neither
    # lost nor logged again as new
    without_row = materialize_progress(season)
    for episode in season.episodes:
        if episode.id in ids:
            if payload.watched and not episode.watched:
                newly_watched += 1
            episode.watched = payload.watched
    counter_from_flags(season, without_row)
    if newly_watched:
        await log_activity(
            db,
            current_user.id,
            "anime",
            show.id,
            show.title,
            ActivityEventType.EPISODES_WATCHED,
            date.today(),
            increment=newly_watched,
        )
    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.patch("/{show_id}/seasons/{season_id}/episodes/{episode_id}", response_model=AnimeRead)
async def update_episode(
    show_id: UUID,
    season_id: UUID,
    episode_id: UUID,
    payload: EpisodeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Anime:
    show = await _get_show_or_404(show_id, db, current_user.id)
    season = await _get_season_or_404(season_id, show_id, db)
    episode = await _get_episode_or_404(episode_id, season_id, db)

    updates = payload.model_dump(exclude_unset=True)
    without_row = 0
    if "watched" in updates:
        # progress the counter already held is flagged first, so it is
        # neither lost nor logged again as new
        without_row = materialize_progress(season)
    newly_watched = updates.get("watched") is True and not episode.watched
    for field, value in updates.items():
        setattr(episode, field, value)
    if "watched" in updates:
        counter_from_flags(season, without_row)

    if newly_watched:
        await log_activity(
            db,
            current_user.id,
            "anime",
            show.id,
            show.title,
            ActivityEventType.EPISODES_WATCHED,
            date.today(),
        )

    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


# How long a cached Related/Recommended payload is served without
# re-asking AniList — a prequel/sequel chain or recommendation list
# changes rarely (only a genuine new-sequel announcement, or AniList
# recomputing its own recommendation scores), so most visits should cost
# zero AniList requests rather than a dozen+.
_RELATIONS_CACHE_TTL_SECONDS = 3 * 24 * 60 * 60


_relations_inflight: set[UUID] = set()


async def _fetch_and_store_relations(show: Anime, db: AsyncSession) -> dict:
    """Asks AniList (slow: a paced request per franchise entry), stores the
    result on the row, and notes any newly listed season for a title the
    user has completed."""
    old_chain = show.relations_cache.get("chain") if show.relations_cache else None
    result = await asyncio.to_thread(
        AniListClient().relations_chain_and_branches, show.title, show.anilist_id
    )
    show.relations_cache = result
    show.relations_cached_at = int(time.time())
    await db.commit()
    await record_sequel_announcements(db, show.user_id, show, old_chain, result["chain"])
    return result


async def refresh_relations_in_background(show_id: UUID) -> None:
    """Fetches and stores a franchise graph without making anyone wait for
    it. Used for a stale cache (the old one is served meanwhile) and to
    warm a title right after it is added, so its Seasons and Related tabs
    are already in the database by the time it is opened."""
    if show_id in _relations_inflight:
        return
    _relations_inflight.add(show_id)
    try:
        async with SessionLocal() as db:
            show = await db.scalar(select(Anime).where(Anime.id == show_id))
            if show is None or not show.anilist_id:
                return
            await _fetch_and_store_relations(show, db)
    except Exception:
        logger.exception("Background franchise refresh failed for %s", show_id)
    finally:
        _relations_inflight.discard(show_id)


async def _get_or_refresh_anime_relations(show: Anime, db: AsyncSession) -> dict:
    """Chain + branches + recommendations for one anime, straight from the
    database whenever anything is stored. A stale or older-layout copy is
    still served instantly and refreshed in the background, so opening a
    title never waits on AniList once it has been seen. Only a title with
    nothing stored yet has to wait for the first fetch."""
    cached = show.relations_cache
    if cached is not None:
        cache_age = (
            int(time.time()) - show.relations_cached_at if show.relations_cached_at else None
        )
        fresh = (
            cached.get("version") == RELATIONS_CACHE_VERSION
            and cache_age is not None
            and cache_age < _RELATIONS_CACHE_TTL_SECONDS
        )
        if not fresh:
            asyncio.create_task(refresh_relations_in_background(show.id))
        return cached
    return await _fetch_and_store_relations(show, db)


@router.get("/{show_id}/relations")
async def get_anime_relations(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """The full prequel/sequel chain this entry belongs to, plus every
    other relation (adaptation, side story, source manga/novel, etc.)
    attached to whichever chain entry it's actually connected to — not
    just this one entry's own direct relations, which for a 3+ season
    franchise would read as missing entries. Uses the stored AniList id
    when known (set at creation/sync) rather than re-searching by title,
    since a title search can match a different entry with a similar
    name. Keyless, so unlike TV/Movie there's no "not configured" state."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    try:
        result = await _get_or_refresh_anime_relations(show, db)
    except AniListError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AniList could not be reached: {exc}"
        ) from exc
    return {
        "chain": result["chain"],
        "branches": result["branches"],
        "configured": True,
    }


@router.get("/{show_id}/recommended")
async def get_anime_recommended(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Reuses the same cached fetch `/relations` populates — AniList
    returns both a title's relations and its recommendations in one
    request, so there's no reason for this tab to cost a second one."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    try:
        result = await _get_or_refresh_anime_relations(show, db)
    except AniListError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AniList could not be reached: {exc}"
        ) from exc
    return {"recommended": result.get("recommendations", []), "configured": True}
