# pylint: disable=missing-class-docstring,missing-function-docstring
"""Entries the user adds to the calendar by hand (see CalendarEvent)."""

import re
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user
from src.database.models.calendar_event import CalendarEvent
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(
    prefix="/api/calendar/events", tags=["calendar"], dependencies=[Depends(get_current_user)]
)
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check_time(value: str | None) -> str | None:
    if not value:
        return None
    if not _TIME.match(value):
        raise ValueError("Time must look like 19:30.")
    return value


class EventBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    event_date: date
    event_time: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    media_type: str | None = Field(default=None, pattern="^(movie|tv|anime|game)$")
    media_id: UUID | None = None

    @field_validator("event_time")
    @classmethod
    def valid_time(cls, value: str | None) -> str | None:
        return _check_time(value)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Give the entry a title.")
        return value


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    event_date: date | None = None
    event_time: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    media_type: str | None = Field(default=None, pattern="^(movie|tv|anime|game)$")
    media_id: UUID | None = None

    @field_validator("event_time")
    @classmethod
    def valid_time(cls, value: str | None) -> str | None:
        return _check_time(value)


def _read(e: CalendarEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "title": e.title,
        "event_date": e.event_date.isoformat(),
        "event_time": e.event_time,
        "note": e.note,
        "media_type": e.media_type,
        "media_id": e.media_id,
    }


async def _get_or_404(event_id: UUID, user_id: UUID, db: AsyncSession) -> CalendarEvent:
    event = await db.scalar(
        select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.user_id == user_id)
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Calendar entry not found."
        )
    return event


@router.get("")
async def list_events(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    stmt = select(CalendarEvent).where(CalendarEvent.user_id == current_user.id)
    if start:
        stmt = stmt.where(CalendarEvent.event_date >= start)
    if end:
        stmt = stmt.where(CalendarEvent.event_date <= end)
    rows = (
        (await db.execute(stmt.order_by(CalendarEvent.event_date, CalendarEvent.event_time)))
        .scalars()
        .all()
    )
    return [_read(e) for e in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if (payload.media_type is None) != (payload.media_id is None):
        raise HTTPException(
            status_code=400, detail="A linked title needs both its type and its id."
        )
    event = CalendarEvent(user_id=current_user.id, **payload.model_dump())
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return _read(event)


@router.patch("/{event_id}")
async def update_event(
    event_id: UUID,
    payload: EventUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    event = await _get_or_404(event_id, current_user.id, db)
    updates = payload.model_dump(exclude_unset=True)
    if "title" in updates:
        updates["title"] = (updates["title"] or "").strip()
        if not updates["title"]:
            raise HTTPException(status_code=400, detail="Give the entry a title.")
    if updates.get("event_date", True) is None:
        raise HTTPException(status_code=400, detail="An entry needs a date.")
    for field, value in updates.items():
        setattr(event, field, value)
    if (event.media_type is None) != (event.media_id is None):
        raise HTTPException(
            status_code=400, detail="A linked title needs both its type and its id."
        )
    await db.commit()
    await db.refresh(event)
    return _read(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    event = await _get_or_404(event_id, current_user.id, db)
    await db.delete(event)
    await db.commit()
