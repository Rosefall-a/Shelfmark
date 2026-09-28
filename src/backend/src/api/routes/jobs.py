# pylint: disable=missing-class-docstring,missing-function-docstring,duplicate-code,duplicate-code
"""The Tasks screen's cleanup jobs: list them, change a schedule, run one now."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_admin
from src.database.session import get_db
from src.features.jobs import JOBS, JobSpec, describe, get_setting

router = APIRouter(
    prefix="/api/settings/jobs", tags=["settings"], dependencies=[Depends(get_current_admin)]
)


class JobUpdate(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


def _spec(job_id: str) -> JobSpec:
    spec = JOBS.get(job_id)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such job.")
    return spec


@router.get("")
async def list_jobs(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    out = [await describe(db, spec) for spec in JOBS.values()]
    await db.commit()
    return out


@router.put("/{job_id}")
async def update_job(
    job_id: str, payload: JobUpdate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    spec = _spec(job_id)
    row = await get_setting(db, spec)
    if payload.interval_minutes is not None:
        if not spec.min_interval_minutes <= payload.interval_minutes <= spec.max_interval_minutes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Choose between {spec.min_interval_minutes} and {spec.max_interval_minutes} minutes."
                ),
            )
        row.interval_minutes = payload.interval_minutes
    if payload.enabled is not None:
        row.enabled = payload.enabled
    await db.commit()
    return await describe(db, spec)


@router.post("/{job_id}/run")
async def run_job(
    job_id: str,
    mode: str | None = Query(default=None, pattern="^(needed|all)$"),
) -> dict[str, Any]:
    """Starts a run now, in the background, the way that job is meant to be run
    by hand unless a mode is given. If one is already running, its progress is
    returned instead."""
    spec = _spec(job_id)
    return spec.start(mode or spec.manual_mode)
