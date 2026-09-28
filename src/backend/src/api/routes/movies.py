"""API routes for managing movies."""

import asyncio
import re
import time
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.media_extras import log_activity, status_change_detail
from src.api.schemas.pagination import PaginatedResponse
from src.api.schemas.movie import MovieCreate, MovieRead, MovieUpdate
from src.core.app_integrations import get_or_create_app_integration_settings
from src.core.auth import get_current_user
from src.core.integrations import resolve_integrations
from src.database.models.media_extras import ActivityEventType
from src.database.models.movies import Movie, MovieStatus
from src.database.models.user import User
from src.database.session import get_db
from src.features.metadata.locked_fields import apply_updates_with_locking
from src.features.metadata.movies.search import search_movie_metadata
from src.features.metadata.movies.tmdb import TMDBClient

router = APIRouter(prefix="/api/movie", tags=["movie"], dependencies=[Depends(get_current_user)])

# fields the metadata search's "Apply" button can fill in — the only ones
# worth locking, since nothing else is ever set by that flow
_LOCKABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "release_date",
        "runtime_minutes",
        "director",
        "writer",
        "studios",
        "genres",
        "poster_url",
        "backdrop_url",
        "tmdb_score",
    }
)


class MovieMetadataSearchResponse(BaseModel):
    query: str
    providers: list[str]
    provider_errors: list[str] = []
    results: list[dict]


_LEADING_ARTICLE = re.compile(r"^(a|an|the)\s+", flags=re.IGNORECASE)


def _derive_sort_title(title: str) -> str:
    """'The Matrix' -> 'matrix' so articles do not affect sort order."""
    return _LEADING_ARTICLE.sub("", title).strip().lower()


async def _get_movie_or_404(
    movie_id: UUID, db: AsyncSession, user_id: UUID, include_deleted: bool = False
) -> Movie:
    stmt = select(Movie).where(Movie.id == movie_id, Movie.user_id == user_id)
    if not include_deleted:
        stmt = stmt.where(Movie.deleted_at.is_(None))
    movie = await db.scalar(stmt)
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Movie {movie_id} not found",
        )
    return movie


@router.get("/metadata/search", response_model=MovieMetadataSearchResponse)
async def search_metadata(
    query: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(default=8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Search TMDB and OMDb for data that can prefill a new movie. Two
    sources on purpose — redundancy, so a missing/rate-limited source
    doesn't leave the search empty."""
    del current_user
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    try:
        result = await asyncio.to_thread(
            search_movie_metadata,
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


@router.post(
    "/create",
    response_model=MovieRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_movie(
    payload: MovieCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Movie:
    """Create a movie entry."""
    data = payload.model_dump()
    if not data.get("sort_title"):
        data["sort_title"] = _derive_sort_title(data["title"])

    movie = Movie(**data, user_id=current_user.id)
    db.add(movie)
    await db.commit()
    await db.refresh(movie)
    return movie


@router.get("/list", response_model=PaginatedResponse[MovieRead])
async def list_movies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: MovieStatus | None = Query(default=None, alias="status"),
    favorite: bool | None = Query(default=None),
    search: str | None = Query(default=None, description="Case-insensitive title search"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> PaginatedResponse[MovieRead]:
    """Return one page of the current user's movies and the total matching it."""
    stmt = select(Movie).where(Movie.user_id == current_user.id, Movie.deleted_at.is_(None))

    if status_filter is not None:
        stmt = stmt.where(Movie.status == status_filter)
    if favorite is not None:
        stmt = stmt.where(Movie.favorite == favorite)
    if search:
        stmt = stmt.where(Movie.title.ilike(f"%{search}%"))

    status_count_stmt = select(Movie.status, func.count()).where(
        Movie.user_id == current_user.id, Movie.deleted_at.is_(None)
    )
    if favorite is not None:
        status_count_stmt = status_count_stmt.where(Movie.favorite == favorite)
    if search:
        status_count_stmt = status_count_stmt.where(Movie.title.ilike(f"%{search}%"))
    status_counts_result = await db.execute(status_count_stmt.group_by(Movie.status))
    status_counts = {status.value: count for status, count in status_counts_result.all()}

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(Movie.sort_title).offset(skip).limit(limit)

    result = await db.execute(stmt)
    items = list(result.scalars().all())
    return PaginatedResponse(
        items=items,
        total=total or 0,
        offset=skip,
        limit=limit,
        status_counts=status_counts,
    )


@router.get("/get/{movie_id}", response_model=MovieRead)
async def get_movie(
    movie_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Movie:
    """Return one movie by ID."""
    return await _get_movie_or_404(movie_id, db, current_user.id)


# statuses that mean "not started yet" (the UI's Plan to Watch): recording
# where you left off moves a movie out of these into In progress. BACKLOG is
# the UI's On Hold, a paused watch, so it keeps its status.
_NOT_STARTED_STATUSES = {MovieStatus.WISHLIST, MovieStatus.WATCHLIST}
_FINISHED_STATUSES = {MovieStatus.WATCHED, MovieStatus.FAVORITE}


def _sync_watch_progress(movie: Movie, updates: dict) -> None:
    """Keep the left-off point and the status telling the same story (#191):
    saving a position in a movie you hadn't started means you're watching
    it, and finishing it (Watched) means there's no position to resume."""
    progress_set = bool(updates.get("progress_minutes"))
    if progress_set and "status" not in updates and movie.status in _NOT_STARTED_STATUSES:
        movie.status = MovieStatus.IN_PROGRESS
    if "status" in updates and movie.status in _FINISHED_STATUSES and not progress_set:
        movie.progress_minutes = None


@router.patch("/update/{movie_id}", response_model=MovieRead)
async def update_movie(
    movie_id: UUID,
    payload: MovieUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Movie:
    """Update a movie and keep its derived sort title synchronized."""
    movie = await _get_movie_or_404(movie_id, db, current_user.id)
    previous_status = movie.status

    updates = payload.model_dump(exclude_unset=True)

    apply_updates_with_locking(movie, updates, _LOCKABLE_FIELDS)
    _sync_watch_progress(movie, updates)

    if "title" in updates and "sort_title" not in updates:
        movie.sort_title = _derive_sort_title(movie.title)

    if "status" in updates and movie.status != previous_status:
        change = status_change_detail(previous_status, movie.status)
        if change:
            await log_activity(
                db,
                current_user.id,
                "movie",
                movie.id,
                movie.title,
                ActivityEventType.STATUS_CHANGED,
                date.today(),
                detail=change,
            )

    await db.commit()
    await db.refresh(movie)
    return movie


@router.delete("/delete/{movie_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_movie(
    movie_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Soft-delete a movie by ID."""
    movie = await _get_movie_or_404(movie_id, db, current_user.id)
    movie.deleted_at = int(time.time())
    await db.commit()


@router.get("/trash")
async def list_movie_trash(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Deleted movies, most recently deleted first. No purge job runs
    against these — unlike Game's on-disk folders, a movie is just a
    row, so there's nothing to clean up and it stays here until an
    admin either restores it or deletes it again to purge it for good."""
    result = await db.execute(
        select(Movie)
        .where(Movie.user_id == current_user.id, Movie.deleted_at.is_not(None))
        .order_by(Movie.deleted_at.desc())
    )
    trashed = []
    for movie in result.scalars().all():
        assert (
            movie.deleted_at is not None
        )  # guaranteed by the deleted_at.is_not(None) filter above
        trashed.append({"id": str(movie.id), "title": movie.title, "deleted_at": movie.deleted_at})
    return trashed


@router.post("/{movie_id}/restore", response_model=MovieRead)
async def restore_movie(
    movie_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Movie:
    movie = await _get_movie_or_404(movie_id, db, current_user.id, include_deleted=True)
    if movie.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Movie isn't deleted.")
    movie.deleted_at = None
    await db.commit()
    await db.refresh(movie)
    return movie


@router.delete("/{movie_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_movie(
    movie_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Permanently removes an already-deleted movie. Only reachable from
    trash — a movie still active must be soft-deleted first."""
    movie = await _get_movie_or_404(movie_id, db, current_user.id, include_deleted=True)
    if movie.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Movie isn't deleted.")
    await db.delete(movie)
    await db.commit()


@router.get("/{movie_id}/relations")
async def get_movie_relations(
    movie_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """TMDB's only real franchise concept for movies: the collection a
    title belongs to (e.g. every Mad Max film). Most movies aren't in
    one — that's a normal empty result, not an error."""
    movie = await _get_movie_or_404(movie_id, db, current_user.id)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    if not app_integrations.tmdb_api_key:
        return {"collection_name": None, "related": [], "configured": False}
    tmdb_api_key = app_integrations.tmdb_api_key
    try:
        result = await asyncio.to_thread(
            lambda: TMDBClient(tmdb_api_key).movie_relations(movie.title)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"TMDB could not be reached: {exc}"
        ) from exc
    return {**result, "configured": True}


@router.get("/{movie_id}/recommended")
async def get_movie_recommended(
    movie_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    movie = await _get_movie_or_404(movie_id, db, current_user.id)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    if not app_integrations.tmdb_api_key:
        return {"recommended": [], "configured": False}
    tmdb_api_key = app_integrations.tmdb_api_key
    try:
        recommended = await asyncio.to_thread(
            lambda: TMDBClient(tmdb_api_key).movie_recommendations(movie.title)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"TMDB could not be reached: {exc}"
        ) from exc
    return {"recommended": recommended, "configured": True}
