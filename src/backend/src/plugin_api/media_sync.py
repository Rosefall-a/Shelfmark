"""Provider-neutral, user-scoped media upserts with optimistic watch-state checks.

Identity uses existing media primary keys, not a second provider database. The
plugin retains its external IDs and the returned revision in durable storage.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models.anime import Anime, AnimeEpisode, AnimeSeason, AnimeStatus
from src.database.models.movies import Movie, MovieStatus
from src.database.models.tv_show import TVEpisode, TVSeason, TVShow, TVShowStatus


class EpisodeInput(BaseModel):
    """One numbered remote episode and its authoritative watched state."""

    model_config = ConfigDict(extra="forbid", strict=True)
    external_id: str = Field(min_length=1, max_length=256)
    season: int = Field(ge=0, le=10000)
    number: int = Field(ge=1, le=100000)
    title: str = Field(default="", max_length=500)
    watched: bool
    removed: bool = False


class MediaSyncInput(BaseModel):
    """A bounded provider identity, metadata and conflict-checked state update."""

    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9._-]+$")
    source_scope: str = Field(min_length=1, max_length=512)
    external_id: str = Field(min_length=1, max_length=256)
    media_type: Literal["movie", "tv_show", "anime"]
    title: str = Field(min_length=1, max_length=500)
    genres: list[Annotated[str, Field(max_length=128)]] = Field(default_factory=list, max_length=50)
    runtime_minutes: int | None = Field(default=None, ge=0, le=100000)
    poster_url: str | None = Field(default=None, max_length=8192)
    played: bool = False
    in_progress: bool = False
    episodes: list[EpisodeInput] = Field(default_factory=list, max_length=100)
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    # A full episode inventory must be finalized before deriving show completion.
    inventory_complete: bool = False


def media_identity(plugin_id: str, user_id: UUID, item: MediaSyncInput) -> UUID:
    """Resolve stable identity without title matching or a parallel mapping table."""
    return uuid5(
        NAMESPACE_URL,
        json.dumps(
            [
                "plugin-media-v1",
                plugin_id,
                str(user_id),
                item.source,
                item.source_scope,
                item.external_id,
            ],
            separators=(",", ":"),
        ),
    )


def watch_revision(item: Any, kind: str) -> str:
    """Hash actual local completion, including independently edited episode flags."""
    status = item.status.value if hasattr(item.status, "value") else item.status
    state: list[Any] = [status]
    if kind != "movie":
        state.append(
            sorted(
                (
                    s.season_number,
                    s.episode_count,
                    s.episodes_watched,
                    sorted((e.episode_number, e.watched) for e in s.episodes),
                )
                for s in item.seasons
            )
        )
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


async def dispatch_media_sync(
    db: AsyncSession, *, plugin_id: str, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Upsert only the caller's media and reject stale watch-state revisions."""
    item = MediaSyncInput.model_validate(payload)
    identity = media_identity(plugin_id, user_id, item)
    # These independent SQLAlchemy media tables expose the same domain fields;
    # validated media_type selects their concrete model/status/episode classes.
    models: dict[str, tuple[Any, Any, Any, Any]] = {
        "movie": (Movie, MovieStatus, None, None),
        "tv_show": (TVShow, TVShowStatus, TVSeason, TVEpisode),
        "anime": (Anime, AnimeStatus, AnimeSeason, AnimeEpisode),
    }
    model, status_type, season_model, episode_model = models[item.media_type]
    # Serialize same-identity upserts, including concurrent first creation.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(identity.bytes[:8], "big", signed=True)},
    )
    # A remap must never create another media row or discard local notes/lists.
    for other in (Movie, TVShow, Anime):
        if other is model:
            continue
        if await db.scalar(select(other.id).where(other.id == identity, other.user_id == user_id)):
            return {"id": str(identity), "conflict": "category_changed"}
    statement = select(model).where(model.id == identity, model.user_id == user_id)
    if season_model is not None:
        statement = statement.options(
            selectinload(model.seasons).selectinload(season_model.episodes)
        )
    media: Any = await db.scalar(statement.with_for_update())
    created = media is None
    if created:
        media = model(
            id=identity,
            user_id=user_id,
            title=item.title,
            sort_title=item.title.casefold(),
            source=item.source,
            status=status_type.WATCHLIST,
        )
        if season_model is not None:
            media.seasons = []
        db.add(media)
    elif media.deleted_at is not None:
        return {"id": str(identity), "conflict": "locally_deleted"}
    elif item.expected_revision != watch_revision(media, item.media_type):
        return {
            "id": str(identity),
            "conflict": "local_watch_state_changed",
            "revision": watch_revision(media, item.media_type),
        }
    for field, value in (
        ("title", item.title),
        ("sort_title", item.title.casefold()),
        ("genres", item.genres),
        ("poster_url", item.poster_url),
    ):
        if field not in (media.locked_fields or []):
            setattr(media, field, value)
    if item.media_type == "movie":
        if "runtime_minutes" not in (media.locked_fields or []):
            media.runtime_minutes = item.runtime_minutes
        media.status = (
            status_type.WATCHED
            if item.played
            else status_type.IN_PROGRESS
            if item.in_progress
            else status_type.WATCHLIST
        )
    else:
        for remote in item.episodes:
            season = next((s for s in media.seasons if s.season_number == remote.season), None)
            if season is None:
                season = season_model(
                    id=uuid5(identity, f"season:{remote.season}"),
                    season_number=remote.season,
                    status=status_type.WATCHLIST,
                    episode_count=0,
                    episodes_watched=0,
                )
                season.episodes = []
                media.seasons.append(season)
            episode_id = uuid5(identity, f"episode:{remote.external_id}")
            episode = next(
                (e for s in media.seasons for e in s.episodes if e.id == episode_id), None
            )
            occupied = next(
                (
                    e
                    for e in season.episodes
                    if e.episode_number == remote.number and e is not episode
                ),
                None,
            )
            if not remote.removed and occupied is not None:
                raise ValueError("episode number conflicts with another external identity")
            if episode is not None:
                origin = next(s for s in media.seasons if episode in s.episodes)
                if not remote.removed:
                    if origin is not season:
                        origin.episodes.remove(episode)
                        season.episodes.append(episode)
                    episode.episode_number = remote.number
            if remote.removed:
                if episode is not None:
                    origin.episodes.remove(episode)
            else:
                if episode is None:
                    episode = episode_model(
                        id=uuid5(identity, f"episode:{remote.external_id}"),
                        episode_number=remote.number,
                    )
                    season.episodes.append(episode)
                episode.title, episode.watched = remote.title, remote.watched
        for season in media.seasons:
            season.episode_count = len(season.episodes)
            season.episodes_watched = sum(e.watched for e in season.episodes)
            season.status = (
                status_type.WATCHED
                if item.inventory_complete
                and season.episode_count > 0
                and season.episodes_watched == season.episode_count
                else status_type.IN_PROGRESS
                if season.episodes_watched
                else status_type.WATCHLIST
            )
        episodes = [e for s in media.seasons for e in s.episodes]
        media.status = (
            status_type.WATCHED
            if item.inventory_complete and episodes and all(e.watched for e in episodes)
            else status_type.IN_PROGRESS
            if any(e.watched for e in episodes) or item.in_progress
            else status_type.WATCHLIST
        )
    await db.flush()
    result = {
        "id": str(identity),
        "created": created,
        "revision": watch_revision(media, item.media_type),
        "status": media.status.value,
    }
    await db.commit()
    return result
