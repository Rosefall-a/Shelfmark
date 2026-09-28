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

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.job_setting import JobSetting
from src.database.session import SessionLocal
from src.features.metadata import refresh_job
from src.features.metadata.refresh import check_airing_episodes

logger = logging.getLogger(__name__)

TICK_SECONDS = 60


@dataclass(frozen=True)
class JobSpec:
    id: str
    name: str
    description: str
    # how often it may be scheduled, in minutes: any whole number in this range
    min_interval_minutes: int
    max_interval_minutes: int
    default_interval_minutes: int
    default_enabled: bool
    # starts one run in the background and returns its progress at once; the
    # mode is "needed" from the schedule and `manual_mode` from "Run now"
    start: Callable[[str], dict[str, Any]]
    is_running: Callable[[], bool]
    summarize: Callable[[dict[str, Any]], str]
    manual_mode: str = "needed"


def _summarize_refresh(r: dict[str, Any]) -> str:
    parts = [
        f"{r.get('checked') or 0} refreshed",
        f"{r.get('skipped_up_to_date') or 0} already fine",
    ]
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
        result = await check_airing_episodes(force=force)
        await record_run("airing_check", result)
    except Exception:
        logger.exception("The airing check failed")
    finally:
        _AIRING_RUNNING = False


JOBS: dict[str, JobSpec] = {
    "airing_check": JobSpec(
        id="airing_check",
        name="Airing episode check",
        description=(
            "Looks for newly aired episodes of shows you are following and adds a numbered "
            "row for each so you can check it off. It only asks about a show once its next "
            "episode is due (plus a daily look for schedule changes), so most runs do almost "
            "nothing. Real titles and images arrive with the media refresh."
        ),
        min_interval_minutes=5,
        max_interval_minutes=24 * 60,
        default_interval_minutes=30,
        default_enabled=True,
        start=_start_airing,
        is_running=_airing_is_running,
        summarize=_summarize_airing,
        manual_mode="all",
    ),
    "media_refresh": JobSpec(
        id="media_refresh",
        name="Media refresh",
        description=(
            "Picks up newly aired episodes, fills in missing episode titles and images, "
            "and corrects a show whose episode count is wrong. It only touches titles that "
            "need it, so a run over a library that is already fine is quick. Its progress "
            "shows under Metadata > Refresh Media."
        ),
        min_interval_minutes=60,
        max_interval_minutes=30 * 24 * 60,
        default_interval_minutes=24 * 60,
        default_enabled=False,
        start=refresh_job.start,
        is_running=refresh_job.is_running,
        summarize=_summarize_refresh,
    ),
}


def is_due(enabled: bool, last_run_at: int | None, interval_minutes: int, now: int) -> bool:
    """Whether a scheduled run should start now: it is switched on, and it has
    either never run or its interval has passed."""
    if not enabled:
        return False
    if last_run_at is None:
        return True
    return now - last_run_at >= interval_minutes * 60


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
    """Called when a run of the job ends, however it was started."""
    async with SessionLocal() as db:
        spec = JOBS[job_id]
        row = await get_setting(db, spec)
        row.last_run_at = int(time.time())
        row.last_result = {
            k: v for k, v in result.items() if isinstance(v, (int, float, str, bool)) or v is None
        }
        await db.commit()


def _on_media_refresh_finished(progress: dict[str, Any]) -> None:
    asyncio.get_running_loop().create_task(record_run("media_refresh", progress))


refresh_job.finish_hooks.append(_on_media_refresh_finished)


async def run_jobs_loop() -> None:
    """Wakes every minute and starts any enabled job that is due."""
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            now = int(time.time())
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
