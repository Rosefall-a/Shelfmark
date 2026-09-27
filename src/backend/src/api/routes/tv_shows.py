# pylint: disable=duplicate-code
# These modules intentionally keep domain/provider-specific logic separate; similar
# structures here represent parallel APIs rather than accidental copy/paste.

"""API routes for managing TV shows and their seasons."""

import asyncio
import logging
import re
import time
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.pagination import PaginatedResponse
from src.api.schemas.tv_show import (
    EpisodesBulkWatched,
    EpisodeUpdate,
    SeasonCreate,
    SeasonUpdate,
    TVShowCreate,
    TVShowLibraryRead,
    TVShowRead,
    TVShowUpdate,
)
from src.api.routes.media_extras import log_activity, status_change_detail
from src.core.app_integrations import get_or_create_app_integration_settings
from src.core.auth import get_current_user
from src.core.integrations import resolve_integrations
from src.database.models.media_extras import ActivityEventType
from src.database.models.tv_show import TVEpisode, TVSeason, TVShow, TVShowStatus
from src.database.models.user import User
from src.database.session import get_db
from src.features.episode_progress import apply_counter, counter_from_flags, materialize_progress
from src.features.metadata.locked_fields import apply_updates_with_locking
from src.features.tv_seasons import check_in_background, is_due
from src.features.metadata.movies.tmdb import TMDBClient
from src.features.metadata.refresh import quick_check_tv_season
from src.features.metadata.tv.episode_sync import fetch_season_episodes
from src.features.metadata.tv.search import search_tv_metadata
from src.features.metadata.tv.tvdb import TVDBClient

router = APIRouter(prefix="/api/tv", tags=["tv"], dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

# fields the metadata search's "Apply" button can fill in — the only ones
# worth locking, since nothing else is ever set by that flow
_LOCKABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "first_air_date",
        "episode_runtime_minutes",
        "creators",
        "genres",
        "poster_url",
        "backdrop_url",
        "tmdb_score",
    }
)


class TVMetadataSearchResponse(BaseModel):
    query: str
    providers: list[str]
    provider_errors: list[str] = []
    results: list[dict]


_LEADING_ARTICLE = re.compile(r"^(a|an|the)\s+", flags=re.IGNORECASE)


def _derive_sort_title(title: str) -> str:
    """'The Wire' -> 'wire' so articles do not affect sort order."""
    return _LEADING_ARTICLE.sub("", title).strip().lower()


async def _get_show_or_404(
    show_id: UUID, db: AsyncSession, user_id: UUID, include_deleted: bool = False
) -> TVShow:
    # populate_existing: a show already in this session's identity map
    # (e.g. loaded earlier in the same request, before a season was just
    # added to it) would otherwise keep its stale, already-cached
    # `seasons` collection instead of picking up the new row
    stmt = (
        select(TVShow)
        .where(TVShow.id == show_id, TVShow.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if not include_deleted:
        stmt = stmt.where(TVShow.deleted_at.is_(None))
    show = await db.scalar(stmt)
    if show is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Show {show_id} not found"
        )
    return show


async def _get_season_or_404(season_id: UUID, show_id: UUID, db: AsyncSession) -> TVSeason:
    season = await db.scalar(
        select(TVSeason).where(TVSeason.id == season_id, TVSeason.show_id == show_id)
    )
    if season is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Season {season_id} not found"
        )
    return season


@router.get("/metadata/search", response_model=TVMetadataSearchResponse)
async def search_metadata(
    query: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(default=8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Search TMDB and OMDb for data that can prefill a new show,
    including its full season list where TMDB has it."""
    del current_user
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    try:
        result = await asyncio.to_thread(
            search_tv_metadata,
            query.strip(),
            limit,
            app_integrations.tmdb_api_key,
            app_integrations.omdb_api_key,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Metadata providers could not be reached: {exc}",
        ) from exc
    return result


@router.post("/create", response_model=TVShowRead, status_code=status.HTTP_201_CREATED)
async def create_show(
    payload: TVShowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    """Create a show, optionally bulk-creating its seasons in the same
    transaction if the caller already has a season list (e.g. from a
    metadata search result)."""
    data = payload.model_dump(exclude={"seasons"})
    if not data.get("sort_title"):
        data["sort_title"] = _derive_sort_title(data["title"])

    show = TVShow(**data, user_id=current_user.id)
    db.add(show)
    await db.flush()

    first_season = None
    for season_input in payload.seasons:
        season = TVSeason(**season_input.model_dump(), show_id=show.id)
        db.add(season)
        if first_season is None:
            first_season = season

    # Otherwise a freshly-added airing show shows no next-episode date
    # anywhere (countdown, calendar) until the next periodic airing-check
    # pass, up to one airing-check interval later — worth the one
    # extra TVmaze call at creation time so it's there immediately.
    # Best-effort: a slow/unreachable TVmaze never blocks creation.
    if show.external_id and first_season is not None:
        try:
            await quick_check_tv_season(show, first_season, db)
        except Exception:
            logger.exception("Immediate airing check failed for new show %r", show.title)

    await db.commit()
    return await _get_show_or_404(show.id, db, current_user.id)


@router.post("/{show_id}/refresh-airing", response_model=TVShowRead)
async def refresh_airing(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    """Runs the airing check for just this show right now (the background
    loop only comes around every 30 minutes)."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    if not show.external_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This show has no TVmaze id, so its airing schedule can't be checked.",
        )
    if show.seasons:
        await quick_check_tv_season(show, show.seasons[-1], db)
        await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.get("/list", response_model=PaginatedResponse[TVShowLibraryRead])
async def list_shows(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: TVShowStatus | None = Query(default=None, alias="status"),
    favorite: bool | None = Query(default=None),
    search: str | None = Query(default=None, description="Case-insensitive title search"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> PaginatedResponse[TVShowLibraryRead]:
    """Return one page of the current user's shows and the total matching it."""
    stmt = select(TVShow).where(TVShow.user_id == current_user.id, TVShow.deleted_at.is_(None))

    if status_filter is not None:
        stmt = stmt.where(TVShow.status == status_filter)
    if favorite is not None:
        stmt = stmt.where(TVShow.favorite == favorite)
    if search:
        stmt = stmt.where(TVShow.title.ilike(f"%{search}%"))

    status_count_stmt = select(TVShow.status, func.count()).where(
        TVShow.user_id == current_user.id, TVShow.deleted_at.is_(None)
    )
    if favorite is not None:
        status_count_stmt = status_count_stmt.where(TVShow.favorite == favorite)
    if search:
        status_count_stmt = status_count_stmt.where(TVShow.title.ilike(f"%{search}%"))
    status_counts_result = await db.execute(status_count_stmt.group_by(TVShow.status))
    status_counts = {status.value: count for status, count in status_counts_result.all()}

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(TVShow.sort_title).offset(skip).limit(limit)

    result = await db.execute(stmt)
    items = list(result.scalars().unique().all())
    return PaginatedResponse(
        items=items,
        total=total or 0,
        offset=skip,
        limit=limit,
        status_counts=status_counts,
    )

@router.get("/get/{show_id}", response_model=TVShowRead)
async def get_show(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    """Return one show by ID, with its seasons. If it has been a while,
    also asks TVmaze in the background whether the show has a new season
    (see features/tv_seasons.py), which shows up the next time it's opened."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    if is_due(show):
        asyncio.create_task(check_in_background(show.id))
    return show


@router.patch("/update/{show_id}", response_model=TVShowRead)
async def update_show(
    show_id: UUID,
    payload: TVShowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    """Update a show and keep its derived sort title synchronized."""
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
                "tv",
                show.id,
                show.title,
                ActivityEventType.STATUS_CHANGED,
                date.today(),
                detail=change,
            )

    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.delete("/delete/{show_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_show(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Soft-delete a show by ID (its seasons stay attached, hidden along with it)."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    show.deleted_at = int(time.time())
    await db.commit()


@router.get("/trash")
async def list_show_trash(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Deleted shows, most recently deleted first. No purge job runs
    against these — unlike Game's on-disk folders, a show is just a row
    (plus its seasons/episodes), so there's nothing to clean up and it
    stays here until an admin either restores it or purges it for good."""
    result = await db.execute(
        select(TVShow)
        .where(TVShow.user_id == current_user.id, TVShow.deleted_at.is_not(None))
        .order_by(TVShow.deleted_at.desc())
    )
    trashed = []
    for show in result.scalars().all():
        assert show.deleted_at is not None  # guaranteed by the deleted_at.is_not(None) filter above
        trashed.append({"id": str(show.id), "title": show.title, "deleted_at": show.deleted_at})
    return trashed


@router.post("/{show_id}/restore", response_model=TVShowRead)
async def restore_show(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    show = await _get_show_or_404(show_id, db, current_user.id, include_deleted=True)
    if show.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Show isn't deleted.")
    show.deleted_at = None
    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.delete("/{show_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_show(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Permanently removes an already-deleted show and its seasons/
    episodes. Only reachable from trash — a show still active must be
    soft-deleted first."""
    show = await _get_show_or_404(show_id, db, current_user.id, include_deleted=True)
    if show.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Show isn't deleted.")
    await db.delete(show)
    await db.commit()


@router.post("/{show_id}/seasons", response_model=TVShowRead, status_code=status.HTTP_201_CREATED)
async def create_season(
    show_id: UUID,
    payload: SeasonCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    show = await _get_show_or_404(show_id, db, current_user.id)
    db.add(TVSeason(**payload.model_dump(), show_id=show.id))
    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.patch("/{show_id}/seasons/{season_id}", response_model=TVShowRead)
async def update_season(
    show_id: UUID,
    season_id: UUID,
    payload: SeasonUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
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
                "tv",
                show.id,
                show.title,
                ActivityEventType.EPISODES_WATCHED,
                date.today(),
                increment=new_counter - old_counter,
            )

    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.delete("/{show_id}/seasons/{season_id}", response_model=TVShowRead)
async def delete_season(
    show_id: UUID,
    season_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    await _get_show_or_404(show_id, db, current_user.id)
    season = await _get_season_or_404(season_id, show_id, db)
    await db.delete(season)
    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


async def _get_episode_or_404(episode_id: UUID, season_id: UUID, db: AsyncSession) -> TVEpisode:
    episode = await db.scalar(
        select(TVEpisode).where(TVEpisode.id == episode_id, TVEpisode.season_id == season_id)
    )
    if episode is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Episode {episode_id} not found"
        )
    return episode


@router.get("/{show_id}/seasons/{season_id}/episodes", response_model=TVShowRead)
async def list_episodes(
    show_id: UUID,
    season_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    """Return the season's episodes, syncing them in from TVmaze on the
    very first request (nothing to sync from if the show has no
    `external_id` — it wasn't found via TVmaze, e.g. added by hand).
    Every later call reads straight from the table instead of
    re-fetching."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    season = await _get_season_or_404(season_id, show_id, db)

    if not season.episodes and show.external_id:
        all_episodes, errors = await fetch_season_episodes(show.external_id, season.season_number)
        if not all_episodes and errors:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not sync episodes: {'; '.join(errors)}",
            )
        created = []
        for entry in all_episodes:
            raw_air_date = entry.get("air_date")
            row = TVEpisode(
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


@router.patch("/{show_id}/seasons/{season_id}/episodes/bulk-watched", response_model=TVShowRead)
async def bulk_set_episodes_watched(
    show_id: UUID,
    season_id: UUID,
    payload: EpisodesBulkWatched,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
    """Sets `watched` on a whole batch of episodes in one request — see
    the anime version of this route for why. Registered ahead of the
    single-episode PATCH below so the literal path segment
    "bulk-watched" is matched here rather than attempted as an
    `episode_id` UUID."""
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
            "tv",
            show.id,
            show.title,
            ActivityEventType.EPISODES_WATCHED,
            date.today(),
            increment=newly_watched,
        )
    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.patch("/{show_id}/seasons/{season_id}/episodes/{episode_id}", response_model=TVShowRead)
async def update_episode(
    show_id: UUID,
    season_id: UUID,
    episode_id: UUID,
    payload: EpisodeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TVShow:
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
            "tv",
            show.id,
            show.title,
            ActivityEventType.EPISODES_WATCHED,
            date.today(),
        )

    await db.commit()
    return await _get_show_or_404(show_id, db, current_user.id)


@router.get("/{show_id}/relations")
async def get_show_relations(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """TheTVDB is the only real franchise/relations source for TV shows —
    TMDB has no collection concept outside of movies. Requires its own
    API key (Settings > Metadata Sources); returns an empty, clearly
    unconfigured result rather than an error when it's not set up yet."""
    show = await _get_show_or_404(show_id, db, current_user.id)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    if not app_integrations.tvdb_api_key:
        return {"listName": None, "related": [], "configured": False}
    tvdb_api_key = app_integrations.tvdb_api_key
    try:
        result = await asyncio.to_thread(lambda: TVDBClient(tvdb_api_key).relations(show.title))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"TheTVDB could not be reached: {exc}"
        ) from exc
    return {**result, "configured": True}


@router.get("/{show_id}/recommended")
async def get_show_recommended(
    show_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    show = await _get_show_or_404(show_id, db, current_user.id)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    if not app_integrations.tmdb_api_key:
        return {"recommended": [], "configured": False}
    tmdb_api_key = app_integrations.tmdb_api_key
    try:
        recommended = await asyncio.to_thread(
            lambda: TMDBClient(tmdb_api_key).tv_recommendations(show.title)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"TMDB could not be reached: {exc}"
        ) from exc
    return {"recommended": recommended, "configured": True}
