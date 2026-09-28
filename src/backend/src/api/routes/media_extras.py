# pylint: disable=too-many-arguments,too-many-positional-arguments,missing-function-docstring,too-many-locals,not-callable,unused-import,duplicate-code
"""Cross-media-type routes: rewatch history, custom lists, the activity
feed, and the airing calendar — all span movies, TV shows, and anime,
which live in three separate tables with nothing in common, so every
endpoint here takes an explicit `media_type` and resolves it against the
right table itself (see `_resolve_media`). The data export/backup
feature lives in api/routes/export_import.py, extended to cover these
three media types alongside the games it already covered rather than
duplicated here as a second export system."""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.media_extras import (
    ActivityEntryCreate,
    ActivityEntryRead,
    ActivityEntryUpdate,
    CalendarEntryRead,
    RewatchCreate,
    RewatchRead,
)
from src.core.auth import get_current_user
from src.core.preferences import load_preferences
from src.core.titles import display_title
from src.database.models.achievement import Achievement
from src.database.models.anime import Anime, AnimeStatus
from src.features.notifications import tracked_statuses
from src.database.models.media_extras import (
    ActivityEventType,
    ActivityLog,
    MediaType,
    RewatchLog,
)
from src.database.models.game import Game, GameStatus
from src.database.models.movies import Movie, MovieStatus
from src.database.models.tv_show import TVShow, TVShowStatus
from src.database.models.user import User
from src.database.session import get_db


# The app shows five statuses (Plan to Watch, On Hold, Watching, Completed,
# Dropped) over eight stored ones; history text uses the shown names.
_STATUS_LABELS = {
    "WISHLIST": "Plan to Watch",
    "WATCHLIST": "Plan to Watch",
    "BACKLOG": "On Hold",
    "IN_PROGRESS": "Watching",
    "REWATCH": "Watching",
    "WATCHED": "Completed",
    "FAVORITE": "Completed",
    "DROPPED": "Dropped",
}


def status_change_detail(previous: Any, current: Any) -> str | None:
    """ "Plan to Watch → Watching" for the history feed, or None when the
    two stored statuses are the same thing to the user (Wishlist to
    Watchlist), which is not worth a history line."""
    before = _STATUS_LABELS.get(getattr(previous, "value", str(previous)), str(previous))
    after = _STATUS_LABELS.get(getattr(current, "value", str(current)), str(current))
    return None if before == after else f"{before} → {after}"


# Safety cap on how many projected episodes one show can contribute to a
# single response — a show with a very high (or wrong) episode_count
# should never turn into an unbounded loop.
_MAX_PROJECTED_PER_SHOW = 52


def _calendar_entries_for_show(
    show: Any, media_type: str, window_end: int, language: str = "english"
) -> list[dict]:
    """The real next-episode entry (provider-confirmed), plus a weekly-
    cadence *guess* for every remaining episode up to the show's known
    episode_count — no provider hands over a full future schedule, only
    ever "here's the next one", so anything past that is an assumption,
    flagged via `is_projected` rather than presented as fact. Uses the
    last season's episode_count as the target total (the one currently
    airing, since new seasons are added by hand as they're announced)."""
    entries = [
        {
            "media_type": media_type,
            "media_id": show.id,
            "title": display_title(show, language),
            "poster_url": show.poster_url,
            "next_episode_number": show.next_episode_number,
            "air_at": show.next_episode_air_at,
            "kind": "episode",
            "is_projected": False,
        }
    ]
    if not show.next_episode_number:
        return entries
    season = show.seasons[-1] if show.seasons else None
    # A season's `episode_count` is a snapshot from whenever it was last
    # synced and routinely lags behind an ongoing show's real airing
    # count (a new episode gets scheduled — and next_episode_number
    # bumped — before the season's own total catches up). Only treat it
    # as a real ceiling when it reaches the confirmed next episode (a count
    # equal to it means that episode is the last one); below it there's
    # no known end, so keep projecting up to the window/safety-cap limits
    # instead of silently stopping at one.
    total = (
        season.episode_count
        if season and season.episode_count and season.episode_count >= show.next_episode_number
        else None
    )
    interval_seconds = (show.airing_interval_days or 7) * 24 * 60 * 60
    projected = 0
    n = show.next_episode_number + 1
    while total is None or n <= total:
        air_at = show.next_episode_air_at + interval_seconds * (n - show.next_episode_number)
        if air_at > window_end or projected >= _MAX_PROJECTED_PER_SHOW:
            break
        entries.append(
            {
                "media_type": media_type,
                "media_id": show.id,
                "title": display_title(show, language),
                "poster_url": show.poster_url,
                "next_episode_number": n,
                "air_at": air_at,
                "kind": "episode",
                "is_projected": True,
            }
        )
        projected += 1
        n += 1
    return entries


def _date_to_unix(d: date | None) -> int:
    # the caller always filters on `.isnot(None)` first; the `| None` is
    # only here because SQLAlchemy's own column type stays Optional.
    # Encoded at NOON UTC rather than midnight: a release date has no
    # real time-of-day, and the frontend reads it back via the viewer's
    # local timezone, so midnight UTC rolls back to the previous local
    # day for anyone west of UTC. Noon keeps the calendar date correct
    # for every real-world timezone (UTC-11 through UTC+12).
    assert d is not None
    return (
        int(datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc).timestamp()) + 12 * 3600
    )


router = APIRouter(prefix="/api", tags=["media-extras"], dependencies=[Depends(get_current_user)])

_MODEL_BY_TYPE: dict[str, Any] = {"movie": Movie, "tv": TVShow, "anime": Anime}


async def _resolve_media(media_type: str, media_id: UUID, user_id: UUID, db: AsyncSession) -> Any:
    model = _MODEL_BY_TYPE.get(media_type)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid media_type {media_type!r}"
        )
    row = await db.scalar(
        select(model).where(
            model.id == media_id, model.user_id == user_id, model.deleted_at.is_(None)
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{media_type} {media_id} not found"
        )
    return row


async def log_activity(
    db: AsyncSession,
    user_id: UUID,
    media_type: str,
    media_id: UUID,
    media_title: str,
    event_type: ActivityEventType,
    event_date: date,
    *,
    increment: int = 1,
    detail: str | None = None,
) -> None:
    """Upserts today's bucket for this (user, media, event type) instead
    of inserting a new row per action — checking off ten episodes in one
    sitting reads back as one "12 episodes watched" line, not ten
    separate timestamped rows. Shared by the anime/TV routes (episode
    watched, status changed) and this module's own rewatch endpoint."""
    existing = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.user_id == user_id,
            ActivityLog.media_type == media_type,
            ActivityLog.media_id == media_id,
            ActivityLog.event_type == event_type,
            ActivityLog.event_date == event_date,
        )
    )
    if existing:
        existing.count += increment
        if detail:
            existing.detail = detail
        return
    db.add(
        ActivityLog(
            user_id=user_id,
            media_type=media_type,
            media_id=media_id,
            media_title=media_title,
            event_type=event_type,
            event_date=event_date,
            count=increment,
            detail=detail,
        )
    )


@router.post("/rewatches", response_model=RewatchRead, status_code=status.HTTP_201_CREATED)
async def create_rewatch(
    payload: RewatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RewatchLog:
    media = await _resolve_media(payload.media_type, payload.media_id, current_user.id, db)
    finished_on = payload.finished_on or date.today()
    log = RewatchLog(
        user_id=current_user.id,
        media_type=MediaType(payload.media_type),
        media_id=payload.media_id,
        finished_on=finished_on,
        note=payload.note,
    )
    db.add(log)
    media.rewatches = (media.rewatches or 0) + 1
    await log_activity(
        db,
        current_user.id,
        payload.media_type,
        payload.media_id,
        media.title,
        ActivityEventType.REWATCHED,
        finished_on,
    )
    await db.commit()
    await db.refresh(log)
    return log


@router.get("/rewatches", response_model=list[RewatchRead])
async def list_rewatches(
    media_type: str = Query(...),
    media_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RewatchLog]:
    await _resolve_media(media_type, media_id, current_user.id, db)
    rows = (
        (
            await db.execute(
                select(RewatchLog)
                .where(
                    RewatchLog.user_id == current_user.id,
                    RewatchLog.media_type == media_type,
                    RewatchLog.media_id == media_id,
                )
                .order_by(RewatchLog.finished_on.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.delete(
    "/rewatches/{rewatch_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_rewatch(
    rewatch_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    log = await db.scalar(
        select(RewatchLog).where(RewatchLog.id == rewatch_id, RewatchLog.user_id == current_user.id)
    )
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Rewatch {rewatch_id} not found"
        )
    media = await _resolve_media(log.media_type, log.media_id, current_user.id, db)
    media.rewatches = max(0, (media.rewatches or 0) - 1)
    # the History line for that day counted this rewatch too
    day = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.user_id == current_user.id,
            ActivityLog.media_type == log.media_type,
            ActivityLog.media_id == log.media_id,
            ActivityLog.event_type == ActivityEventType.REWATCHED,
            ActivityLog.event_date == log.finished_on,
        )
    )
    if day is not None:
        if day.count <= 1:
            await db.delete(day)
        else:
            day.count -= 1
    await db.delete(log)
    await db.commit()


@router.get("/activity", response_model=list[ActivityEntryRead])
async def get_activity(
    days: int = Query(default=30, ge=1, le=36500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    since = date.today() - timedelta(days=days)
    rows = (
        (
            await db.execute(
                select(ActivityLog)
                .where(ActivityLog.user_id == current_user.id, ActivityLog.event_date >= since)
                .order_by(ActivityLog.event_date.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post("/activity", response_model=ActivityEntryRead, status_code=status.HTTP_201_CREATED)
async def create_activity_entry(
    payload: ActivityEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActivityLog:
    """Manually logs a history entry — for anything the app didn't catch
    automatically (watch history from before this title was tracked
    here, an import, etc). Goes through the same day-bucket upsert
    `log_activity` already uses for automatic entries."""
    media = await _resolve_media(payload.media_type, payload.media_id, current_user.id, db)
    await log_activity(
        db,
        current_user.id,
        payload.media_type,
        payload.media_id,
        media.title,
        ActivityEventType(payload.event_type),
        payload.event_date,
        increment=payload.count,
        detail=payload.detail,
    )
    await db.commit()
    row = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.user_id == current_user.id,
            ActivityLog.media_type == payload.media_type,
            ActivityLog.media_id == payload.media_id,
            ActivityLog.event_type == payload.event_type,
            ActivityLog.event_date == payload.event_date,
        )
    )
    assert row is not None  # just upserted above
    return row


@router.patch("/activity/{entry_id}", response_model=ActivityEntryRead)
async def update_activity_entry(
    entry_id: UUID,
    payload: ActivityEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActivityLog:
    """Every field is editable, including which title and event type the
    entry belongs to — moving it onto a bucket key that already has a
    row merges into that row (counts added) instead of hitting the
    unique constraint, same "one line per bucket" rule log_activity
    already enforces for automatic entries."""
    entry = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.id == entry_id, ActivityLog.user_id == current_user.id
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Activity entry {entry_id} not found"
        )

    updates = payload.model_dump(exclude_unset=True)
    key_changed = any(f in updates for f in ("media_type", "media_id", "event_type", "event_date"))
    new_media_type = updates.get("media_type", entry.media_type)
    new_media_id = updates.get("media_id", entry.media_id)
    new_event_type = updates.get("event_type", entry.event_type)
    new_event_date = updates.get("event_date", entry.event_date)

    if "media_type" in updates or "media_id" in updates:
        media = await _resolve_media(new_media_type, new_media_id, current_user.id, db)
        updates["media_title"] = media.title

    for field, value in updates.items():
        setattr(entry, field, value)

    if key_changed:
        existing = await db.scalar(
            select(ActivityLog).where(
                ActivityLog.user_id == current_user.id,
                ActivityLog.media_type == new_media_type,
                ActivityLog.media_id == new_media_id,
                ActivityLog.event_type == new_event_type,
                ActivityLog.event_date == new_event_date,
                ActivityLog.id != entry.id,
            )
        )
        if existing is not None:
            existing.count += entry.count
            if entry.detail:
                existing.detail = entry.detail
            await db.delete(entry)
            await db.commit()
            return existing

    await db.commit()
    return entry


@router.delete("/activity/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_activity_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    entry = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.id == entry_id, ActivityLog.user_id == current_user.id
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Activity entry {entry_id} not found"
        )
    await db.delete(entry)
    await db.commit()


async def build_calendar_entries(
    db: AsyncSession, user_id: UUID, days: int, game_releases: bool = False
) -> list[dict]:
    """Two kinds of entry, both media the real-calendar view groups by
    day: "episode" entries are anime/TV already airing with a known
    next-episode date, and "release" entries are anything on Plan to
    Watch (Wishlist/Watchlist — not Backlog, which the frontend buckets
    as On Hold instead) whose release/premiere date is still ahead —
    a movie you're waiting on, or a show whose first season hasn't
    started yet. `days` windows both directions loosely — something that
    just aired/released stays visible for a day so "today" doesn't look
    empty the moment it passes."""
    prefs = await load_preferences(db, user_id)
    language = str(prefs["title_language"])
    airing = prefs["calendar_airing_statuses"]
    now = int(time.time())
    window_end = now + days * 86400
    window_start = now - 86400
    today = date.today()
    date_window_end = today + timedelta(days=days)
    date_window_start = today - timedelta(days=1)

    result: list[dict] = []

    anime_rows = (
        (
            await db.execute(
                select(Anime).where(
                    Anime.user_id == user_id,
                    Anime.deleted_at.is_(None),
                    Anime.status.in_(tracked_statuses(AnimeStatus, airing)),
                    Anime.next_episode_air_at.isnot(None),
                    Anime.next_episode_air_at >= window_start,
                    Anime.next_episode_air_at <= window_end,
                )
            )
        )
        .scalars()
        .all()
    )

    for a in anime_rows:
        result.extend(_calendar_entries_for_show(a, "anime", window_end, language))

    tv_rows = (
        (
            await db.execute(
                select(TVShow).where(
                    TVShow.user_id == user_id,
                    TVShow.deleted_at.is_(None),
                    TVShow.status.in_(tracked_statuses(TVShowStatus, airing)),
                    TVShow.next_episode_air_at.isnot(None),
                    TVShow.next_episode_air_at >= window_start,
                    TVShow.next_episode_air_at <= window_end,
                )
            )
        )
        .scalars()
        .all()
    )

    for t in tv_rows:
        result.extend(_calendar_entries_for_show(t, "tv", window_end, language))

    movie_rows = (
        (
            await db.execute(
                select(Movie).where(
                    Movie.user_id == user_id,
                    Movie.deleted_at.is_(None),
                    Movie.status.in_([MovieStatus.WISHLIST, MovieStatus.WATCHLIST]),
                    Movie.release_date.isnot(None),
                    Movie.release_date >= date_window_start,
                    Movie.release_date <= date_window_end,
                )
            )
        )
        .scalars()
        .all()
    )
    for m in movie_rows:
        result.append(
            {
                "media_type": "movie",
                "media_id": m.id,
                "title": m.title,
                "poster_url": m.poster_url,
                "next_episode_number": None,
                "air_at": _date_to_unix(m.release_date),
                "kind": "release",
            }
        )
    upcoming_tv_rows = (
        (
            await db.execute(
                select(TVShow).where(
                    TVShow.user_id == user_id,
                    TVShow.deleted_at.is_(None),
                    TVShow.status.in_([TVShowStatus.WISHLIST, TVShowStatus.WATCHLIST]),
                    TVShow.first_air_date.isnot(None),
                    TVShow.first_air_date >= date_window_start,
                    TVShow.first_air_date <= date_window_end,
                )
            )
        )
        .scalars()
        .all()
    )
    for t in upcoming_tv_rows:
        result.append(
            {
                "media_type": "tv",
                "media_id": t.id,
                "title": t.title,
                "poster_url": t.poster_url,
                "next_episode_number": None,
                "air_at": _date_to_unix(t.first_air_date),
                "kind": "release",
            }
        )
    upcoming_anime_rows = (
        (
            await db.execute(
                select(Anime).where(
                    Anime.user_id == user_id,
                    Anime.deleted_at.is_(None),
                    Anime.status.in_([AnimeStatus.WISHLIST, AnimeStatus.WATCHLIST]),
                    Anime.first_air_date.isnot(None),
                    Anime.first_air_date >= date_window_start,
                    Anime.first_air_date <= date_window_end,
                )
            )
        )
        .scalars()
        .all()
    )
    for a in upcoming_anime_rows:
        result.append(
            {
                "media_type": "anime",
                "media_id": a.id,
                "title": a.title,
                "poster_url": a.poster_url,
                "next_episode_number": None,
                "air_at": _date_to_unix(a.first_air_date),
                "kind": "release",
            }
        )

    if game_releases:
        game_rows = (
            (
                await db.execute(
                    select(Game).where(
                        Game.user_id == user_id,
                        Game.deleted_at.is_(None),
                        Game.release_date.isnot(None),
                        Game.release_date >= date_window_start,
                        Game.release_date <= date_window_end,
                    )
                )
            )
            .scalars()
            .all()
        )

        for g in game_rows:
            result.append(
                {
                    "media_type": "game",
                    "media_id": g.id,
                    "title": g.title,
                    "poster_url": f"/api/game/{g.id}/assets/key_art",
                    "next_episode_number": None,
                    "air_at": _date_to_unix(g.release_date),
                    "kind": "release",
                }
            )

    result.sort(key=lambda r: r["air_at"])
    return result


@router.get("/calendar", response_model=list[CalendarEntryRead])
async def get_calendar(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    prefs = await load_preferences(db, current_user.id)
    return await build_calendar_entries(
        db,
        current_user.id,
        days,
        game_releases=bool(prefs["calendar_game_releases"]) and not prefs["calendar_hide_games"],
    )


@router.get("/calendar/games")
async def get_calendar_games(
    days: int = Query(default=36500, ge=1, le=36500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """The past side of Games on the calendar. With "Game releases" on, the
    release date of every game in the library from before yesterday (the
    calendar's own feed carries today and everything ahead). With "Games
    history" on, the day each game was finished and bought and how many
    achievements were unlocked on a day. Empty when Games are hidden."""
    prefs = await load_preferences(db, current_user.id)
    if prefs["calendar_hide_games"]:
        return []
    entries: list[dict] = []
    if prefs["calendar_game_releases"]:
        released = (
            (
                await db.execute(
                    select(Game).where(
                        Game.user_id == current_user.id,
                        Game.deleted_at.is_(None),
                        Game.release_date.isnot(None),
                        Game.release_date < date.today() - timedelta(days=1),
                        Game.release_date >= date.today() - timedelta(days=days),
                    )
                )
            )
            .scalars()
            .all()
        )
        for g in released:
            if g.release_date is None:
                continue
            entries.append(
                {
                    "kind": "game_released",
                    "game_id": g.id,
                    "title": g.title,
                    "date": g.release_date.isoformat(),
                    "count": 1,
                    "poster_url": f"/api/game/{g.id}/assets/key_art",
                }
            )
    if not prefs["calendar_game_history"]:
        entries.sort(key=lambda e: e["date"])
        return entries
    since = int(time.time()) - days * 86400
    finished = (
        (
            await db.execute(
                select(Game).where(
                    Game.user_id == current_user.id,
                    Game.deleted_at.is_(None),
                    Game.completion_date.isnot(None),
                    Game.completion_date >= since,
                )
            )
        )
        .scalars()
        .all()
    )
    for g in finished:
        if g.completion_date is None:
            continue
        entries.append(
            {
                "kind": "game_finished",
                "game_id": g.id,
                "title": g.title,
                "date": datetime.fromtimestamp(g.completion_date, tz=timezone.utc)
                .date()
                .isoformat(),
                "count": 1,
                "poster_url": f"/api/game/{g.id}/assets/key_art",
            }
        )
    bought = (
        (
            await db.execute(
                select(Game).where(
                    Game.user_id == current_user.id,
                    Game.deleted_at.is_(None),
                    Game.purchase_date.isnot(None),
                    Game.purchase_date >= since,
                )
            )
        )
        .scalars()
        .all()
    )
    for g in bought:
        if g.purchase_date is None:
            continue
        entries.append(
            {
                "kind": "game_purchased",
                "game_id": g.id,
                "title": g.title,
                "date": datetime.fromtimestamp(g.purchase_date, tz=timezone.utc).date().isoformat(),
                "count": 1,
                "poster_url": f"/api/game/{g.id}/assets/key_art",
            }
        )
    day = func.date(func.to_timestamp(Achievement.unlocked_at))
    rows = (
        await db.execute(
            select(Game.id, Game.title, day, func.count())
            .join(Game, Game.id == Achievement.game_id)
            .where(
                Game.user_id == current_user.id,
                Game.deleted_at.is_(None),
                Achievement.unlocked.is_(True),
                Achievement.unlocked_at.isnot(None),
                Achievement.unlocked_at >= since,
            )
            .group_by(Game.id, Game.title, day)
        )
    ).all()
    for game_id, title, d, count in rows:
        entries.append(
            {
                "kind": "game_achievements",
                "game_id": game_id,
                "title": title,
                "date": d.isoformat(),
                "count": count,
                "poster_url": f"/api/game/{game_id}/assets/key_art",
            }
        )
    entries.sort(key=lambda e: e["date"])
    return entries
