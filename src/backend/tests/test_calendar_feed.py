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



class _FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _FakeDb:
    def __init__(self, user, events=None):
        self.user = user
        self.events = events or []

    async def scalar(self, _statement):
        return self.user

    async def execute(self, _statement):
        return _FakeResult(self.events)


@pytest.mark.asyncio
async def test_feed_preferences_match_calendar_semantics(monkeypatch):
    from src.api.routes import calendar_feed as feed_module

    user = User(id=uuid4(), username="calendar-test", email="calendar@example.test", password_hash="x")
    captured = {}

    async def fake_preferences(_db, _user_id):
        return {
            "calendar_game_releases": True,
            "calendar_hide_games": True,
            "calendar_show_estimated": False,
        }

    async def fake_entries(_db, _user_id, days, game_releases=False):
        captured["days"] = days
        captured["game_releases"] = game_releases
        return [
            {"media_type": "game", "media_id": uuid4(), "title": "Game", "next_episode_number": None, "air_at": 1, "kind": "release"},
            {"media_type": "tv", "media_id": uuid4(), "title": "Confirmed", "next_episode_number": 1, "air_at": 1, "kind": "episode", "is_projected": False},
            {"media_type": "tv", "media_id": uuid4(), "title": "Estimated", "next_episode_number": 2, "air_at": 2, "kind": "episode", "is_projected": True},
        ]

    monkeypatch.setattr(feed_module, "load_preferences", fake_preferences)
    monkeypatch.setattr(feed_module, "build_calendar_entries", fake_entries)
    response = await feed_module.calendar_feed("token", _FakeDb(user))
    body = response.body.decode()
    assert captured == {"days": 90, "game_releases": False}
    assert "Confirmed" in body
    assert "Estimated" not in body
    assert "Game" in body


@pytest.mark.asyncio
async def test_feed_keeps_estimated_entries_when_preference_is_enabled(monkeypatch):
    from src.api.routes import calendar_feed as feed_module

    user = User(id=uuid4(), username="calendar-test", email="calendar@example.test", password_hash="x")

    async def fake_preferences(_db, _user_id):
        return {
            "calendar_game_releases": False,
            "calendar_hide_games": False,
            "calendar_show_estimated": True,
        }

    async def fake_entries(_db, _user_id, days, game_releases=False):
        return [
            {"media_type": "tv", "media_id": uuid4(), "title": "Estimated", "next_episode_number": 2, "air_at": 2, "kind": "episode", "is_projected": True},
        ]

    monkeypatch.setattr(feed_module, "load_preferences", fake_preferences)
    monkeypatch.setattr(feed_module, "build_calendar_entries", fake_entries)
    response = await feed_module.calendar_feed("token", _FakeDb(user))
    assert "Estimated" in response.body.decode()


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
    assert "DTSTART;VALUE=DATE:20270115" in ics
    assert "DTEND;VALUE=DATE:20270116" in ics
    assert "DTSTART:20270115T090000Z" in ics
    assert "DTEND:20270115T093000Z" in ics
    assert "DTSTART;VALUE=DATE:20261003" in ics
    assert "DTEND;VALUE=DATE:20261004" in ics
    assert "DTSTART:20261004T193000" in ics
    assert "SUMMARY:A\\, release\\; special (release)" in ics
    assert "DESCRIPTION:Bring snacks\\, please\\; thanks" in ics
    assert all("UID:" in event for event in ics.split("BEGIN:VEVENT")[1:])
    assert len(_uids(ics)) == 5
    assert len(set(_uids(ics))) == 5



def test_ics_fixture_has_well_formed_vcalendar_and_vevent_boundaries():
    ics = _build_ics(_entries())
    assert "\\r\\n" in ics
    assert "\\n" not in ics.replace("\\r\\n", "")
    assert ics.count("BEGIN:VCALENDAR\r\n") == 1
    assert ics.count("END:VCALENDAR\r\n") == 1
    assert ics.count("BEGIN:VEVENT\r\n") == 3
    assert ics.count("END:VEVENT\r\n") == 3
    for block in ics.split("BEGIN:VEVENT\r\n")[1:]:
        event = block.split("END:VEVENT\r\n", 1)[0]
        assert any(line.startswith("UID:") for line in event.split("\r\n"))
        assert any(line.startswith("DTSTART") for line in event.split("\\r\\n"))
        assert any(line.startswith("SUMMARY:") for line in event.split("\\r\\n"))


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
            assert response.headers["content-type"].startswith("text/calendar")
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
