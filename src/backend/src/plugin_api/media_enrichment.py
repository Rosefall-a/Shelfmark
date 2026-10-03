"""Opt-in, provider-neutral enrichment on the same media.sync capability.

Links and successful snapshots are committed with domain updates, so replay after
host downtime cannot create another record or duplicate a viewing session.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import date
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import extract, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models.anime import Anime, AnimeSeason
from src.database.models.media_provider import MediaPlaybackEvent, MediaProviderLink
from src.database.models.movies import Movie
from src.database.models.tv_show import TVSeason, TVShow
from src.plugin_api.media_sync import (
    MediaSyncInput,
    ResolvedSync,
    dispatch_media_sync,
    media_identity,
    watch_revision,
)

MODELS: dict[str, Any] = {"movie": Movie, "tv_show": TVShow, "anime": Anime}
IDENTITY_PROVIDERS = {
    "movie": {"imdb", "tmdb", "tmdb.movie"},
    "tv_show": {"imdb", "tmdb", "tmdb.tv", "tvdb", "tvmaze"},
    "anime": {"imdb", "tmdb.movie", "tmdb.tv", "tvdb", "anilist", "mal", "kitsu", "anidb"},
}
StringValue = Annotated[str, Field(max_length=256)]


class PlaybackInput(BaseModel):
    """Exact remote state; absence differs from a reported zero."""

    model_config = ConfigDict(extra="forbid", strict=True)
    position_ticks: int = Field(default=0, ge=0, le=10**16)
    runtime_ticks: int | None = Field(default=None, ge=0, le=10**16)
    percentage: float | int | None = Field(default=None, ge=0, le=100)
    play_count: int = Field(default=0, ge=0, le=10**9)
    last_played_at: int | None = Field(default=None, ge=0, le=10**12)


class PlaybackEventInput(BaseModel):
    """A stable event ID and truthful provenance, never invented earlier plays."""

    model_config = ConfigDict(extra="forbid", strict=True)
    external_id: str = Field(min_length=1, max_length=256)
    episode_external_id: str | None = Field(default=None, max_length=256)
    played_at: int = Field(ge=0, le=10**12)
    duration_seconds: int | None = Field(default=None, ge=0, le=10**9)
    provenance: Literal["reported_session", "observed_last_played"]


class EnrichmentInput(MediaSyncInput):
    """Additive v1 request, selected explicitly so existing plugins retain behavior."""

    sync_mode: Literal["enrich"]
    auto_merge: bool = True
    merge_title_year: bool = True
    release_year: int | None = Field(default=None, ge=1, le=9999)
    provider_ids: dict[Annotated[str, Field(pattern=r"^[a-z0-9._-]{1,50}$")], StringValue] = Field(
        default_factory=dict, max_length=32
    )
    target_id: str | None = Field(default=None, max_length=36)
    force_watch: bool = False
    available: bool = True
    availability_only: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=32)
    playback: PlaybackInput | None = None
    episode_progress: dict[StringValue, PlaybackInput] = Field(default_factory=dict, max_length=100)
    history: list[PlaybackEventInput] = Field(default_factory=list, max_length=100)

    @field_validator("metadata")
    @classmethod
    def bounded_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Metadata is retained as JSON, but is never code or an unbounded payload."""
        if len(json.dumps(value, allow_nan=False).encode()) > 64 * 1024:
            raise ValueError("metadata exceeded the 64 KiB limit")
        artwork = value.get("artwork")
        if artwork is not None:
            if not isinstance(artwork, dict) or len(artwork) > 8:
                raise ValueError("artwork must contain at most eight URLs")
            for url in artwork.values():
                if not isinstance(url, str) or len(url) > 8192:
                    raise ValueError("invalid artwork URL")
                parts = urlsplit(url)
                if (
                    parts.scheme not in {"http", "https"}
                    or not parts.hostname
                    or parts.username
                    or parts.password
                    or any(c.isspace() for c in url)
                ):
                    raise ValueError("artwork requires an HTTP(S) URL without credentials")
        return value


def _watch_data(item: EnrichmentInput, previous: dict[str, Any]) -> dict[str, Any]:
    episodes = dict(previous.get("episodes", {}))
    for episode in item.episodes:
        episodes[episode.external_id] = {
            "season": episode.season,
            "number": episode.number,
            "watched": episode.watched,
            "removed": episode.removed,
        }
    return {"played": item.played, "in_progress": item.in_progress, "episodes": episodes}


async def _load_media(db: AsyncSession, kind: str, identity: UUID, user_id: UUID) -> Any:
    model = MODELS[kind]
    query = select(model).where(model.id == identity, model.user_id == user_id)
    if kind != "movie":
        season = TVSeason if kind == "tv_show" else AnimeSeason
        query = query.options(selectinload(model.seasons).selectinload(season.episodes))
    return await db.scalar(query.with_for_update())


async def _matches(
    db: AsyncSession, item: EnrichmentInput, user_id: UUID
) -> tuple[list[Any], bool]:
    model = MODELS[item.media_type]
    conditions = [
        model.provider_ids[key].astext == value
        for key, value in item.provider_ids.items()
        if value and key in IDENTITY_PROVIDERS[item.media_type]
    ]
    if item.media_type == "anime":
        for provider, column in (
            ("anilist", Anime.anilist_id),
            ("mal", Anime.external_id),
            ("kitsu", Anime.kitsu_id),
        ):
            if item.provider_ids.get(provider):
                conditions.append(column == item.provider_ids[provider])
    elif item.media_type == "tv_show" and item.provider_ids.get("tvmaze"):
        conditions.append(model.external_id == item.provider_ids["tvmaze"])
    base = select(model).where(model.user_id == user_id, model.deleted_at.is_(None))
    candidates = (
        list((await db.scalars(base.where(or_(*conditions)).limit(21))).all()) if conditions else []
    )
    if candidates:
        return candidates, True
    date_column = model.release_date if item.media_type == "movie" else model.first_air_date
    title = func.lower(func.trim(model.title)) == item.title.strip().lower()
    if item.merge_title_year and item.release_year:
        candidates = list(
            (
                await db.scalars(
                    base.where(title, extract("year", date_column) == item.release_year).limit(21)
                )
            ).all()
        )
        if candidates:
            return candidates, True
    candidates = list((await db.scalars(base.where(title, date_column.is_(None)).limit(21))).all())
    return candidates, False


def _apply_metadata(media: Any, item: EnrichmentInput) -> None:
    locked = set(media.locked_fields or [])
    for key in (
        "description",
        "director",
        "writer",
        "studios",
        "countries",
        "languages",
        "tags",
        "creators",
        "age_rating",
        "backdrop_url",
        "format",
    ):
        value = item.metadata.get(key)
        if not hasattr(media, key) or key in locked or value is None or value == "":
            continue
        if key in {"studios", "countries", "languages", "tags", "creators"}:
            if (
                isinstance(value, list)
                and len(value) <= 50
                and all(isinstance(v, str) and len(v) <= 256 for v in value)
            ):
                setattr(media, key, list(dict.fromkeys([*(getattr(media, key) or []), *value])))
        elif isinstance(value, str) and len(value) <= (
            20000
            if key == "description"
            else 8192
            if key == "backdrop_url"
            else 20
            if key in {"age_rating", "format"}
            else 200
        ):
            if key == "backdrop_url":
                parts = urlsplit(value)
                if parts.scheme not in {"http", "https"} or parts.username or parts.password:
                    continue
            setattr(media, key, value)
    date_key = "release_date" if item.media_type == "movie" else "first_air_date"
    date_value = item.metadata.get("premiere_date")
    if isinstance(date_value, str) and date_key not in locked:
        try:
            setattr(media, date_key, date.fromisoformat(date_value))
        except ValueError:
            pass
    score = item.metadata.get("rating_overall")
    if (
        media.rating_overall is None
        and isinstance(score, (int, float))
        and not isinstance(score, bool)
        and math.isfinite(score)
        and 0 <= score <= 10
    ):
        media.rating_overall = score
    if item.media_type != "movie" and item.runtime_minutes is not None:
        if "episode_runtime_minutes" not in locked:
            media.episode_runtime_minutes = item.runtime_minutes
    media.provider_ids = {**(media.provider_ids or {}), **item.provider_ids}


async def dispatch_enrichment(
    db: AsyncSession, *, plugin_id: str, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Serialize matching per user; apply a replay-safe provider transaction."""
    item = EnrichmentInput.model_validate(payload)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(hashlib.sha256(user_id.bytes).digest()[:8], "big", signed=True)},
    )
    link = await db.scalar(
        select(MediaProviderLink)
        .where(
            MediaProviderLink.user_id == user_id,
            MediaProviderLink.plugin_id == plugin_id,
            MediaProviderLink.source == item.source,
            MediaProviderLink.source_scope == item.source_scope,
            MediaProviderLink.external_id == item.external_id,
        )
        .with_for_update()
    )
    identity = media_identity(plugin_id, user_id, item)
    if item.availability_only:
        if link is None:
            return {"conflict": "unknown_identity"}
        link.available = item.available
        link.updated_at = int(time.time())
        await db.commit()
        return {"id": str(link.media_id), "created": False, "revision": link.applied_revision}
    if link:
        if link.media_type != item.media_type:
            return {
                "id": str(link.media_id),
                "conflict": "category_changed",
                "media_type": link.media_type,
            }
        identity = link.media_id
        if item.target_id and UUID(item.target_id) != identity:
            return {"id": str(identity), "conflict": "already_mapped"}
    elif item.target_id:
        identity = UUID(item.target_id)
        if await _load_media(db, item.media_type, identity, user_id) is None:
            raise LookupError("owned target media not found")
    elif item.auto_merge:
        candidates, strong = await _matches(db, item, user_id)
        if len(candidates) > 1 or candidates and not strong:
            return {
                "conflict": "ambiguous_match" if strong else "incomplete_match",
                "candidates": [
                    {"id": str(candidate.id), "title": candidate.title}
                    for candidate in candidates[:20]
                ],
            }
        if candidates:
            candidate = candidates[0]
            contradictory = any(
                key in (candidate.provider_ids or {}) and candidate.provider_ids[key] != value
                for key, value in item.provider_ids.items()
                if key in IDENTITY_PROVIDERS[item.media_type]
            )
            if contradictory:
                return {
                    "conflict": "provider_id_mismatch",
                    "candidates": [{"id": str(candidate.id), "title": candidate.title}],
                }
            identity = candidate.id
    media = await _load_media(db, item.media_type, identity, user_id)
    if media is not None and media.deleted_at is not None:
        return {"id": str(identity), "conflict": "locally_deleted"}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if link and link.data.get("digest") == digest:
        return {
            "id": str(identity),
            "created": False,
            "replayed": True,
            "revision": link.applied_revision,
        }
    previous = link.data if link else {}
    watch = _watch_data(item, previous.get("watch", {}))
    all_progress = {
        **previous.get("episode_progress", {}),
        **{key: value.model_dump() for key, value in item.episode_progress.items()},
    }
    watch["in_progress"] |= any(v.get("position_ticks", 0) > 0 for v in all_progress.values())
    watch_digest = hashlib.sha256(json.dumps(watch, sort_keys=True).encode()).hexdigest()
    update_watch = (
        media is None
        or link is None
        or previous.get("watch") != watch
        or item.inventory_complete
        and previous.get("finalized_watch") != watch_digest
    )
    expected = (
        link.applied_revision if link else watch_revision(media, item.media_type) if media else None
    )
    if item.force_watch:
        expected = watch_revision(media, item.media_type) if media else None
    core_payload = {
        key: value for key, value in item.model_dump().items() if key in MediaSyncInput.model_fields
    }
    core_payload["expected_revision"] = expected
    before_revision = watch_revision(media, item.media_type) if media else None
    related = list(
        (
            await db.scalars(
                select(MediaProviderLink).where(
                    MediaProviderLink.user_id == user_id,
                    MediaProviderLink.media_id == identity,
                    MediaProviderLink.media_type == item.media_type,
                )
            )
        ).all()
    )
    core_payload["in_progress"] = watch["in_progress"]
    for other in related:
        if other is link or not other.available:
            continue
        other_watch = other.data.get("watch", {})
        core_payload["played"] |= other_watch.get("played", False)
        core_payload["in_progress"] |= other_watch.get("in_progress", False)
        numbered = {
            (v["season"], v["number"]): v.get("watched", False)
            for v in other_watch.get("episodes", {}).values()
            if not v.get("removed")
        }
        for episode in core_payload["episodes"]:
            episode["watched"] |= numbered.get((episode["season"], episode["number"]), False)
    # Linking another provider must not turn a locally watched item into unwatched.
    if media is not None and link is None:
        core_payload["played"] |= getattr(media.status, "value", media.status) in {
            "WATCHED",
            "FAVORITE",
        }
        if item.media_type != "movie":
            watched = {
                (s.season_number, e.episode_number): e.watched
                for s in media.seasons
                for e in s.episodes
            }
            for episode in core_payload["episodes"]:
                episode["watched"] |= watched.get((episode["season"], episode["number"]), False)
    result = await dispatch_media_sync(
        db,
        plugin_id=plugin_id,
        user_id=user_id,
        payload=core_payload,
        options=ResolvedSync(
            identity=identity,
            enrich=True,
            update_watch=update_watch,
            commit=False,
            episode_ids={
                key: UUID(value) for key, value in previous.get("episode_ids", {}).items()
            },
        ),
    )
    if result.get("conflict"):
        return result
    media = await _load_media(db, item.media_type, identity, user_id)
    if update_watch and core_payload["in_progress"]:
        media.status = type(media.status).IN_PROGRESS
        result["status"] = media.status.value
        result["revision"] = watch_revision(media, item.media_type)
    for other in related:
        if update_watch and other is not link and other.applied_revision == before_revision:
            other.applied_revision = result["revision"]
    _apply_metadata(media, item)
    if link is None:
        link = MediaProviderLink(
            user_id=user_id,
            plugin_id=plugin_id,
            source=item.source,
            source_scope=item.source_scope,
            external_id=item.external_id,
            media_type=item.media_type,
            media_id=identity,
            updated_at=int(time.time()),
        )
        db.add(link)
        await db.flush()
    link.available = item.available
    previous_episodes = (link.data or {}).get("episode_progress", {})
    episode_ids = dict(previous.get("episode_ids", {}))
    if item.media_type != "movie":
        numbered = {
            (s.season_number, e.episode_number): str(e.id)
            for s in media.seasons
            for e in s.episodes
        }
        for episode in item.episodes:
            if (episode.season, episode.number) in numbered:
                episode_ids[episode.external_id] = numbered[(episode.season, episode.number)]
    link.data = {
        "digest": digest,
        "watch": watch,
        "metadata": item.metadata,
        "playback": item.playback.model_dump() if item.playback else None,
        "episode_progress": {
            **previous_episodes,
            **{key: value.model_dump() for key, value in item.episode_progress.items()},
        },
        "provider_ids": item.provider_ids,
        "episode_ids": episode_ids,
        "title": item.title,
    }
    if item.inventory_complete:
        link.data = {**link.data, "finalized_watch": watch_digest}
    elif previous.get("finalized_watch"):
        link.data = {**link.data, "finalized_watch": previous["finalized_watch"]}
    link.updated_at = int(time.time())
    if update_watch:
        link.applied_revision = result["revision"]
    if item.playback and item.media_type == "movie":
        media.rewatches = max(media.rewatches or 0, max(0, item.playback.play_count - 1))
    for event in item.history:
        stored = await db.scalar(
            select(MediaPlaybackEvent).where(
                MediaPlaybackEvent.link_id == link.id,
                MediaPlaybackEvent.external_id == event.external_id,
            )
        )
        if stored is None:
            stored = MediaPlaybackEvent(
                user_id=user_id, link_id=link.id, media_id=identity, **event.model_dump()
            )
            db.add(stored)
        else:
            stored.duration_seconds = event.duration_seconds
    await db.commit()
    return result
