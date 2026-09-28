# pylint: disable=missing-class-docstring,missing-function-docstring,too-many-instance-attributes,global-statement,broad-exception-caught
"""Cleanup jobs: recurring work an administrator can switch on, schedule and
run by hand.

Each job is described once in JOBS. Its schedule is stored in `job_settings`;
a job starts on or off as its spec says (the airing check is on because new
episodes should appear without anyone asking, the full refresh is off because
it is heavy). One loop (started in main.py) wakes every minute, and runs any
enabled job that is due. Running a job by hand, from a screen or from
the loop, goes through the same code and records the same last-run details.

Adding a job is one entry here plus whatever it does; the Tasks screen lists
whatever is registered."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.job_setting import JobSetting
from src.database.models.user import User
from src.database.models.user_preferences import UserPreferences
from src.database.session import SessionLocal
from src.features.imports.anilist import import_anilist_library
from src.features.metadata import refresh_job
from src.features.metadata.refresh import check_airing_episodes

logger = logging.getLogger(__name__)
TICK_SECONDS = 60
ANILIST_IMPORT_MAX_USERS_PER_TICK = 4


@dataclass(frozen=True)
class JobSpec:
    id: str
    name: str
    description: str
    min_interval_minutes: int
    max_interval_minutes: int
    default_interval_minutes: int
    default_enabled: bool
    start: Callable[[str], dict[str, Any]]
    is_running: Callable[[], bool]
    summarize: Callable[[dict[str, Any]], str]
    manual_mode: str = "needed"


def _summarize_refresh(r: dict[str, Any]) -> str:
    parts = [f"{r.get('checked') or 0} refreshed", f"{r.get('skipped_up_to_date') or 0} already fine"]
    if r.get("counts_fixed"):
        parts.append(f"{r['counts_fixed']} count(s) corrected")
    return ", ".join(parts)


def _summarize_airing(r: dict[str, Any]) -> str:
    added = (r.get("anime_episodes_added") or 0) + (r.get("tv_episodes_added") or 0)
    parts = [f"{r.get('checked') or 0} checked", f"{r.get('not_due') or 0} not due yet"]
    if added:
        parts.append(f"{added} new episode(s)")
    return ", ".join(parts)


_AIRING_RUNNING = False


def _airing_is_running() -> bool:
    return _AIRING_RUNNING


def _start_airing(mode: str) -> dict[str, Any]:
    """Runs one airing check in the background. Scheduled runs only ask about
    shows that are due; "Run now" (mode "all") asks about every airing show."""
    global _AIRING_RUNNING
    if not _AIRING_RUNNING:
        _AIRING_RUNNING = True
        asyncio.get_running_loop().create_task(_run_airing(force=mode == "all"))
    return {"running": True}


async def _run_airing(force: bool) -> None:
    global _AIRING_RUNNING
    try:
        await record_run("airing_check", await check_airing_episodes(force=force))
    except Exception:
        logger.exception("The airing check failed")
    finally:
        _AIRING_RUNNING = False


JOBS: dict[str, JobSpec] = {
    "airing_check": JobSpec(
        "airing_check", "Airing episode check", "Checks for newly aired episodes.",
        5, 24 * 60, 30, True, _start_airing, _airing_is_running,
        _summarize_airing, "all",
    ),
    "media_refresh": JobSpec(
        "media_refresh", "Media refresh",
        "Fills missing episode metadata and corrects stale media data.",
        60, 30 * 24 * 60, 24 * 60, False,
        refresh_job.start, refresh_job.is_running, _summarize_refresh,
    ),
}


def is_due(enabled: bool, last_run_at: int | None, interval_minutes: int, now: int) -> bool:
    if not enabled:
        return False
    return last_run_at is None or now - last_run_at >= interval_minutes * 60


async def get_setting(db: AsyncSession, spec: JobSpec) -> JobSetting:
    row = await db.get(JobSetting, spec.id)
    if row is None:
        row = JobSetting(
            job_id=spec.id,
            enabled=spec.default_enabled,
            interval_minutes=spec.default_interval_minutes,
        )
        db.add(row)
        await db.flush()
    return row


async def describe(db: AsyncSession, spec: JobSpec) -> dict[str, Any]:
    row = await get_setting(db, spec)
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "enabled": row.enabled,
        "interval_minutes": row.interval_minutes,
        "min_interval_minutes": spec.min_interval_minutes,
        "max_interval_minutes": spec.max_interval_minutes,
        "last_run_at": row.last_run_at,
        "last_result": row.last_result or {},
        "last_summary": spec.summarize(row.last_result or {}) if row.last_run_at else "",
        "running": spec.is_running(),
    }


async def record_run(job_id: str, result: dict[str, Any]) -> None:
    async with SessionLocal() as db:
        spec = JOBS[job_id]
        row = await get_setting(db, spec)
        row.last_run_at = int(time.time())
        row.last_result = {\n            k: v for k, v in result.items()\n            if isinstance(v, (int, float, str, bool)) or v is None\n        }
        await db.commit()


def _on_media_refresh_finished(progress: dict[str, Any]) -> None:
    asyncio.get_running_loop().create_task(record_run("media_refresh", progress))


refresh_job.finish_hooks.append(_on_media_refresh_finished)


async def _run_due_anilist_imports(now: int) -> None:
    """Run a small bounded batch so one deployment with many users cannot starve other jobs."""
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(UserPreferences, User)
                .join(User, User.id == UserPreferences.user_id)
                .where(UserPreferences.data["anilist_import_enabled"].as_boolean().is_(True))
                .limit(ANILIST_IMPORT_MAX_USERS_PER_TICK)
            )
        ).all()
    for pref_row, user in rows:
        data = pref_row.data
        username = str(data.get("anilist_import_username") or "").strip()
        interval = int(data.get("anilist_import_interval_minutes") or 24 * 60)
        last_run = data.get("anilist_import_last_run_at")
        if not username or not is_due(True, last_run, interval, now):
            continue
        try:
            async with SessionLocal() as db:
                result = await import_anilist_library(
            db, user.id, username, bool(data.get("anilist_import_update_existing"))
        )
                pref = await db.get(UserPreferences, pref_row.id)
                if pref is not None:
                    pref.data = {**pref.data, "anilist_import_last_run_at": now}
                    await db.commit()
            logger.info("Scheduled AniList import for user %s: %s", user.id, result)
        except Exception:
            logger.exception("Scheduled AniList import failed for user %s", user.id)


async def run_jobs_loop() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            now = int(time.time())
            await _run_due_anilist_imports(now)
            async with SessionLocal() as db:
                due = []
                for spec in JOBS.values():
                    row = await get_setting(db, spec)
                    if not spec.is_running() and is_due(
                        row.enabled, row.last_run_at, row.interval_minutes, now
                    ):
                        due.append(spec)
                await db.commit()
            for spec in due:
                logger.info("Starting the scheduled job %s", spec.id)
                spec.start("needed")
        except Exception:
            logger.exception("The jobs loop failed; it will try again")
