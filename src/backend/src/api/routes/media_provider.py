"""Authenticated provider state/history for native media detail pages."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.media_extras import _resolve_media
from src.core.auth import get_current_user
from src.database.models.media_provider import MediaPlaybackEvent, MediaProviderLink
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(prefix="/api/media", tags=["media-providers"])


@router.get("/provider-state")
async def provider_state(
    media_type: str,
    media_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    """Read only the authenticated user's owned media, with bounded history."""
    media = await _resolve_media(media_type, media_id, current_user.id, db)
    kind = "tv_show" if media_type == "tv" else media_type
    links = list(
        (
            await db.scalars(
                select(MediaProviderLink)
                .where(
                    MediaProviderLink.user_id == current_user.id,
                    MediaProviderLink.media_id == media_id,
                    MediaProviderLink.media_type == kind,
                )
                .order_by(MediaProviderLink.updated_at.desc())
                .limit(100)
            )
        ).all()
    )
    events = list(
        (
            await db.scalars(
                select(MediaPlaybackEvent)
                .where(
                    MediaPlaybackEvent.user_id == current_user.id,
                    MediaPlaybackEvent.media_id == media_id,
                )
                .order_by(MediaPlaybackEvent.played_at.desc(), MediaPlaybackEvent.id)
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
    )
    return {
        "provider_ids": media.provider_ids,
        "sources": [
            {
                "source": link.source,
                "account_scope": link.source_scope,
                "available": link.available,
                "updated_at": link.updated_at,
                "playback": link.data.get("playback"),
                "metadata": link.data.get("metadata", {}),
                "episode_progress": {
                    key: {**value, **link.data.get("watch", {}).get("episodes", {}).get(key, {})}
                    for key, value in list(link.data.get("episode_progress", {}).items())[
                        offset : offset + limit
                    ]
                },
            }
            for link in links
        ],
        "history": [
            {
                "id": str(event.id),
                "played_at": event.played_at,
                "duration_seconds": event.duration_seconds,
                "episode_external_id": event.episode_external_id,
                "provenance": event.provenance,
            }
            for event in events[:limit]
        ],
        "has_more": len(events) > limit
        or any(len(link.data.get("episode_progress", {})) > offset + limit for link in links),
    }
