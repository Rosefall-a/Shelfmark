# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user
from src.database.models.auth import UserApiKey
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/api-keys")
async def list_user_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, str | int | list[str] | None]]:
    keys = await db.scalars(
        select(UserApiKey)
        .where(UserApiKey.user_id == user.id)
        .order_by(UserApiKey.created_at.desc())
    )
    return [
        {
            "id": str(api_key.id),
            "name": api_key.name,
            "key_prefix": api_key.key_prefix,
            "scopes": api_key.scopes,
            "created_at": api_key.created_at,
            "revoked_at": api_key.revoked_at,
        }
        for api_key in keys
    ]
