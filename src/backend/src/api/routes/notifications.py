# pylint: disable=missing-function-docstring,not-callable
"""In-app notifications. The bell polls `/unread-count`, which also
generates anything newly due (see features/notifications.py), so there is
no background job behind this."""

import time
from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user
from src.core.preferences import load_preferences
from src.core.titles import display_title
from src.database.models.anime import Anime
from src.database.models.notification import Notification
from src.database.models.user import User
from src.database.session import get_db
from src.features.notifications import generate_for_user

router = APIRouter(
    prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)]
)


def _read(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "media_type": n.media_type,
        "media_id": n.media_id,
        "title": n.title,
        "body": n.body,
        "poster_url": n.poster_url,
        "event_at": n.event_at,
        "read": n.read_at is not None,
    }


async def _display_titles(
    db: AsyncSession, user_id: UUID, rows: Sequence[Notification]
) -> dict[UUID, str]:
    """A notification stores the title as it was when it was created. Anime
    titles are shown in the spelling the user picked now, so changing the
    setting also changes the ones already in the list."""
    anime_ids = {n.media_id for n in rows if n.media_type == "anime" and n.media_id}
    if not anime_ids:
        return {}
    language = str((await load_preferences(db, user_id))["title_language"])
    shows = (
        (await db.execute(select(Anime).where(Anime.id.in_(anime_ids), Anime.user_id == user_id)))
        .scalars()
        .all()
    )
    by_id = {s.id: display_title(s, language) for s in shows}
    return {
        n.id: by_id[n.media_id] for n in rows if n.media_type == "anime" and n.media_id in by_id
    }


@router.get("/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict:
    await generate_for_user(db, current_user.id)
    count = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
    )
    return {"unread": count or 0}


@router.get("")
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await generate_for_user(db, current_user.id)
    stmt = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = (
        (await db.execute(stmt.order_by(Notification.event_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    unread = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
    )
    titles = await _display_titles(db, current_user.id, rows)
    return {
        "items": [{**_read(n), "title": titles.get(n.id, n.title)} for n in rows],
        "unread": unread or 0,
    }


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def mark_all_read(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .values(read_at=int(time.time()))
    )
    await db.commit()


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def mark_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == current_user.id)
        .values(read_at=int(time.time()))
    )
    if not result.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    await db.commit()


@router.post(
    "/{notification_id}/unread", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def mark_unread(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == current_user.id)
        .values(read_at=None)
    )
    if not result.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    await db.commit()


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await db.execute(
        delete(Notification).where(
            Notification.id == notification_id, Notification.user_id == current_user.id
        )
    )
    await db.commit()
