# pylint: disable=missing-function-docstring
"""Per-user preferences stored on the server (calendar options,
notification toggles). See core/preferences.py for the list and defaults."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user
from src.core.preferences import load_preferences, save_preferences
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(
    prefix="/api/preferences", tags=["preferences"], dependencies=[Depends(get_current_user)]
)


@router.get("")
async def get_preferences(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict[str, Any]:
    return await load_preferences(db, current_user.id)


@router.patch("")
async def update_preferences(
    changes: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await save_preferences(db, current_user.id, changes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
