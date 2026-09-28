"""The media refresh as a job with progress.

It used to be one request that walked every show and season one at a time,
asking up to four providers each, so a big library took a very long time and
the button showed nothing until the end. Now:

- it only touches what needs it (`mode="needed"`): a show still airing, one
  with no episodes or with untitled ones, or one whose stored total disagrees
  with what AniList says it has. `mode="all"` checks everything;
- AniList is asked once per 50 shows for each one's status and final total,
  and that total is what repairs a season a wrong provider match had inflated;
- several shows are worked on at once (each provider is still paced by the
  shared throttle, so this only overlaps the waiting);
- progress is kept while it runs, so the screen can show it.

A run is started by someone asking for it (the Settings button) or by the
existing daily loop. Only one runs at a time."""
# pylint: disable=missing-class-docstring,too-many-instance-attributes,missing-function-docstring,broad-exception-caught,not-callable,global-statement

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from sqlalchemy import func, select

from src.database.models.anime import Anime, AnimeEpisode, AnimeSeason
from src.database.models.tv_show import TVSeason, TVShow
from src.database.session import SessionLocal
from src.features.metadata.anime.alt_titles import fill_missing_titles
from src.features.metadata.anime.anilist import AniListClient
from src.features.metadata.anime.episode_sync import episode_limit
from src.features.metadata.refresh import (
    _refresh_anime_season,
    _refresh_tv_season,
    heal_all_anime_metadata,
)

logger = logging.getLogger(__name__)

CONCURRENCY = 6
MODES = ("needed", "all")


@dataclass
class Progress:
    running: bool = False
    mode: str = "needed"
    phase: str = ""
    total: int = 0
    done: int = 0
    current: str = ""
    checked: int = 0
    skipped_up_to_date: int = 0
    anime_episodes_added: int = 0
    anime_episodes_updated: int = 0
    tv_episodes_added: int = 0
    tv_episodes_updated: int = 0
    counts_fixed: int = 0
    anime_metadata_healed: int = 0
    unreachable: list[str] = field(default_factory=list)
    started_at: int | None = None
    finished_at: int | None = None
    error: str | None = None


# called with the final progress whenever a run ends, however it was started
finish_hooks: list[Callable[[dict[str, Any]], None]] = []

_progress = Progress()
_task: asyncio.Task[dict[str, Any]] | None = None


def snapshot() -> dict[str, Any]:
    return asdict(_progress)


def is_running() -> bool:
    return _progress.running


def _anime_needs(show: Anime, season: AnimeSeason, info: dict[str, Any] | None) -> bool:
    if info and info.get("status") == "RELEASING":
        return True  # its rows are checked against what has aired
    if info is None and show.is_airing is not False:
        return True  # never checked, so it is unknown whether it is still airing
    rows = season.episodes
    if not rows or any(not e.title for e in rows):
        return True
    total = info.get("total") if info else None
    if total:
        top = max(e.episode_number for e in rows)
        return season.episode_count != total or top != total or len(rows) != total
    return False


def _tv_needs(show: TVShow, season: TVSeason) -> bool:
    if show.is_airing is not False:
        return True
    return not season.episodes or any(not e.title for e in season.episodes)


async def _refresh_one_anime(
    season_id: Any,
    show_id: Any,
    info: dict[str, Any] | None,
    total_known: bool,
    sem: asyncio.Semaphore,
) -> None:
    async with sem:
        async with SessionLocal() as db:
            season = await db.get(AnimeSeason, season_id)
            show = await db.get(Anime, show_id)
            if season is None or show is None:
                _progress.done += 1
                return
            _progress.current = show.title
            if info and info.get("status") is not None:
                show.is_airing = info["status"] == "RELEASING"
            if _progress.mode == "needed" and not _anime_needs(show, season, info):
                _progress.skipped_up_to_date += 1
                _progress.done += 1
                await db.commit()
                return
            before_count = season.episode_count or 0
            before_rows = len(season.episodes)
            try:
                added, enriched = await _refresh_anime_season(
                    db,
                    show,
                    season,
                    final_total=(info or {}).get("total"),
                    limit=episode_limit(info),
                    total_known=total_known,
                )
                _progress.anime_episodes_added += added
                _progress.anime_episodes_updated += enriched
                _progress.checked += 1
                await db.commit()
                # judged from what is stored now, not from the objects in memory
                stored = (
                    await db.execute(
                        select(AnimeSeason.episode_count, func.count(AnimeEpisode.id))
                        .outerjoin(AnimeEpisode, AnimeEpisode.season_id == AnimeSeason.id)
                        .where(AnimeSeason.id == season_id)
                        .group_by(AnimeSeason.id)
                    )
                ).one()
                if before_count > (stored[0] or 0) or stored[1] < before_rows:
                    _progress.counts_fixed += 1
            except Exception:
                logger.exception("Anime refresh failed for %s", show.title)
                _progress.unreachable.append(show.title)
                await db.rollback()
            _progress.done += 1


async def _refresh_one_tv(season_id: Any, show_id: Any, sem: asyncio.Semaphore) -> None:
    async with sem:
        async with SessionLocal() as db:
            season = await db.get(TVSeason, season_id)
            show = await db.get(TVShow, show_id)
            if season is None or show is None:
                _progress.done += 1
                return
            _progress.current = show.title
            if _progress.mode == "needed" and not _tv_needs(show, season):
                _progress.skipped_up_to_date += 1
                _progress.done += 1
                return
            try:
                added, enriched = await _refresh_tv_season(show, season, db)
                _progress.tv_episodes_added += added
                _progress.tv_episodes_updated += enriched
                _progress.checked += 1
                await db.commit()
            except Exception:
                logger.exception("TV refresh failed for %s", show.title)
                _progress.unreachable.append(show.title)
                await db.rollback()
            _progress.done += 1


def _begin(mode: str) -> bool:
    """Marks a run as started. False if one is already running."""
    global _progress
    if _progress.running:
        return False
    _progress = Progress(
        running=True,
        mode=mode if mode in MODES else "needed",
        phase="Starting",
        started_at=int(time.time()),
    )
    return True


async def _execute() -> dict[str, Any]:
    try:
        _progress.phase = "Filling in missing titles"
        try:
            async with SessionLocal() as db:
                await fill_missing_titles(db)
        except Exception:
            logger.exception("Alternate title lookup failed")
        _progress.phase = "Filling in missing details"
        try:
            _progress.anime_metadata_healed = await heal_all_anime_metadata()
        except Exception:
            logger.exception("Anime metadata heal pass failed")

        async with SessionLocal() as db:
            anime_rows = (
                await db.execute(
                    select(AnimeSeason.id, AnimeSeason.show_id, Anime.anilist_id)
                    .join(Anime, Anime.id == AnimeSeason.show_id)
                    .where(Anime.deleted_at.is_(None))
                )
            ).all()
            tv_rows = (
                await db.execute(
                    select(TVSeason.id, TVSeason.show_id)
                    .join(TVShow, TVShow.id == TVSeason.show_id)
                    .where(TVShow.deleted_at.is_(None))
                )
            ).all()
        _progress.total = len(anime_rows) + len(tv_rows)

        _progress.phase = "Asking AniList which titles have finished airing"
        ids = sorted({int(a) for _, _, a in anime_rows if a and str(a).isdigit()})
        totals: dict[int, dict[str, Any]] = {}
        if ids:
            totals = await asyncio.to_thread(AniListClient().final_totals, ids)

        _progress.phase = "Checking episodes"
        sem = asyncio.Semaphore(CONCURRENCY)
        jobs = []
        for season_id, show_id, anilist_id in anime_rows:
            info = totals.get(int(anilist_id)) if anilist_id and str(anilist_id).isdigit() else None
            # a show AniList did not answer for is left to look the total up itself
            total_known = info is not None
            jobs.append(_refresh_one_anime(season_id, show_id, info, total_known, sem))
        for season_id, show_id in tv_rows:
            jobs.append(_refresh_one_tv(season_id, show_id, sem))
        await asyncio.gather(*jobs)
    except Exception as exc:  # noqa: BLE001, the job reports a failure instead of vanishing
        logger.exception("Media refresh failed")
        _progress.error = str(exc)
    finally:
        _progress.running = False
        _progress.phase = "Done"
        _progress.current = ""
        _progress.finished_at = int(time.time())
        for hook in finish_hooks:
            try:
                hook(snapshot())
            except Exception:
                logger.exception("A media refresh finish hook failed")
    return snapshot()


async def run(mode: str = "needed") -> dict[str, Any]:
    """Runs one refresh to the end and returns its final progress. Does
    nothing (and returns the running one's progress) if one is already
    running."""
    if not _begin(mode):
        return snapshot()
    return await _execute()


def start(mode: str = "needed") -> dict[str, Any]:
    """Starts a run in the background and returns at once. If one is already
    running, returns its progress instead of starting a second."""
    global _task
    if not _begin(mode):
        return snapshot()
    _task = asyncio.create_task(_execute())
    return snapshot()
