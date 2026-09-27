"""Regression coverage for the user-facing iCalendar subscription feed."""

from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.routes.calendar_feed import (
    _build_ics,
    _ics_escape,
    calendar_feed,
    get_feed_token,
    regenerate_feed_token,
)
from src.database.models.calendar_event import CalendarEvent
from src.database.models.user import User
from src.database.session import SessionLocal


def _entries():
    when = 1_800_000_000
    return [
        {
            "media_type": "movie", "media_id": uuid4(),
            "title": "A, release; special", "next_episode_number": None,
            "air_at": when, "kind": "release",
        },
        {
            "media_type": "tv", "media_id": uuid4(),
            "title": "Episode show", "next_episode_number": 4,
            "air_at": when + 3600, "kind": "episode", "is_projected": False,
        },
        {
            "media_type": "anime", "media_id": uuid4(),
            "title": "Projected show", "next_episode_number": 5,
            "air_at": when + 7200, "kind": "episode", "is_projected": True,
        },
    ]


def _uids(ics: str) -> list[str]:
    return [line.removeprefix("UID:") for line in ics.splitlines() if line.startswith("UID:")]


def test_ics_escape_cannot_inject_properties_and_escapes_ical_text():
    value = "Title, with; slash\\ and\nnew line\rbare return"
    escaped = _ics_escape(value)
    assert escaped == "Title\\, with\\; slash\\\\ and\\nnew linebare return"
    assert "\r" not in escaped


def test_build_ics_contains_valid_core_properties_for_release_episode_and_manual_events():
    manual = CalendarEvent(
        id=uuid4(), user_id=uuid4(), title="Manual, reminder; party",
        event_date=date(2026, 10, 3), event_time=None, note="Bring snacks, please; thanks",
    )
    timed_manual = CalendarEvent(
        id=uuid4(), user_id=manual.user_id, title="Timed meeting",
        event_date=date(2026, 10, 4), event_time="19:30",
    )
    ics = _build_ics(_entries(), [manual, timed_manual])
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "BEGIN:VCALENDAR\r\n" in ics
    assert "VERSION:2.0\r\n" in ics
    assert "CALSCALE:GREGORIAN\r\n" in ics
    assert "DTSTART;VALUE=DATE:20260911" in ics
    assert "DTEND;VALUE=DATE:20260912" in ics
    assert "DTSTART:20260911T175320Z" in ics
    assert "DTEND:20260911T182320Z" in ics
    assert "DTSTART;VALUE=DATE:20261003" in ics
    assert "DTEND;VALUE=DATE:20261004" in ics
    assert "DTSTART:20261004T193000" in ics
    assert "SUMMARY:A\\, release\\; special (release)" in ics
    assert "DESCRIPTION:Bring snacks\\, please\\; thanks" in ics
    assert all("UID:" in event for event in ics.split("BEGIN:VEVENT")[1:])
    assert len(_uids(ics)) == 5
    assert len(set(_uids(ics))) == 5


def test_ics_uids_are_stable_for_the_same_source_entries():
    entries = _entries()
    first = _build_ics(entries)
    second = _build_ics(entries)
    assert _uids(first) == _uids(second)


@pytest.mark.asyncio
async def test_feed_token_creation_and_regeneration_invalidate_the_old_secret():
    async with SessionLocal() as db:
        user = User(username=f"ics_{uuid4().hex[:10]}", email=f"{uuid4().hex[:10]}@example.test", password_hash="x")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        try:
            first = await get_feed_token(db, user)
            old = first["path"].split("/feed/", 1)[1].removesuffix(".ics")
            assert len(old) >= 40
            assert await get_feed_token(db, user) == first
            regenerated = await regenerate_feed_token(db, user)
            new = regenerated["path"].split("/feed/", 1)[1].removesuffix(".ics")
            assert new != old
            with pytest.raises(HTTPException) as exc:
                await calendar_feed(old, db)
            assert exc.value.status_code == 404
            response = await calendar_feed(new, db)
            assert response.status_code == 200
            assert response.media_type == "text/calendar"
            assert "BEGIN:VCALENDAR" in response.body.decode()
        finally:
            await db.delete(user)
            await db.commit()


@pytest.mark.asyncio
async def test_unknown_and_inactive_feed_tokens_are_rejected():
    async with SessionLocal() as db:
        user = User(username=f"ics_{uuid4().hex[:10]}", email=f"{uuid4().hex[:10]}@example.test", password_hash="x", calendar_token=uuid4().hex)
        db.add(user)
        await db.commit()
        token = user.calendar_token
        try:
            with pytest.raises(HTTPException) as unknown:
                await calendar_feed("not-a-real-token", db)
            assert unknown.value.status_code == 404
            user.is_active = False
            await db.commit()
            with pytest.raises(HTTPException) as inactive:
                await calendar_feed(token, db)
            assert inactive.value.status_code == 404
        finally:
            await db.delete(user)
            await db.commit()


@pytest.mark.asyncio
async def test_feed_includes_only_the_owner_manual_events():
    async with SessionLocal() as db:
        owner = User(username=f"ics_{uuid4().hex[:10]}", email=f"{uuid4().hex[:10]}@example.test", password_hash="x", calendar_token=uuid4().hex)
        other = User(username=f"ics_{uuid4().hex[:10]}", email=f"{uuid4().hex[:10]}@example.test", password_hash="x", calendar_token=uuid4().hex)
        db.add_all([owner, other])
        await db.flush()
        db.add(CalendarEvent(user_id=owner.id, title="Owner event", event_date=date.today()))
        db.add(CalendarEvent(user_id=other.id, title="Other user event", event_date=date.today()))
        await db.commit()
        try:
            body = (await calendar_feed(owner.calendar_token, db)).body.decode()
            assert "Owner event" in body
            assert "Other user event" not in body
        finally:
            await db.delete(owner)
            await db.delete(other)
            await db.commit()
