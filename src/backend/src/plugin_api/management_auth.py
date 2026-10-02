"""Dedicated, granular control-plane credentials; never general application keys."""

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user, hash_token
from src.database.models.auth import UserApiKey
from src.database.models.user import User
from src.database.session import get_db

MANAGEMENT_PREFIX = "utpm_"
MANAGEMENT_SCOPES = frozenset(
    {
        "plugins.read",
        "plugins.install",
        "plugins.update",
        "plugins.lifecycle",
        "plugins.permissions",
    }
)


def management_scope(method: str, path: str) -> str | None:
    """Allow only manager operations; plugin-provided APIs remain inaccessible."""
    relative = path.removeprefix("/api/plugins").strip("/")
    parts = relative.split("/") if relative else []
    if path.startswith("/api/plugin-permissions/"):
        return "plugins.read" if method == "GET" else "plugins.permissions"
    if not path.startswith("/api/plugins"):
        return None
    if method == "GET" and (
        not parts
        or parts[0] in {"catalog", "catalogues", "manager-settings", "runtime"}
        or len(parts) == 2
        and parts[1] in {"logs", "changelog", "detail"}
    ):
        return "plugins.read"
    if parts and parts[0] == "install":
        return "plugins.install"
    if parts and parts[0] in {"updates", "manager-settings", "catalogues"}:
        return "plugins.update"
    if len(parts) >= 2 and parts[1] in {
        "update",
        "rollback",
        "history",
        "reinstall",
        "auto-update",
    }:
        return "plugins.update"
    if len(parts) >= 2 and parts[1] == "permissions":
        return "plugins.permissions"
    if (
        len(parts) == 1
        and method == "DELETE"
        or len(parts) == 2
        and parts[1] in {"start", "stop", "enable", "disable", "retry"}
    ):
        return "plugins.lifecycle"
    return None


async def _management_user(request: Request, db: AsyncSession, authorization: str) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    required = management_scope(request.method, request.url.path)
    row = await db.scalar(
        select(UserApiKey).where(
            UserApiKey.key_hash == hash_token(token),
            UserApiKey.revoked_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(401, "Invalid plugin management token.")
    if required is None or required not in row.scopes:
        raise HTTPException(403, "Plugin management scope is not granted.")
    user = await db.scalar(
        select(User).where(
            User.id == row.user_id,
            User.is_active.is_(True),
            User.is_admin.is_(True),
        )
    )
    if user is None:
        raise HTTPException(403, "Active administrator token owner required.")
    return user


async def get_plugin_manager_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    session_token: str | None = Cookie(default=None, alias="session"),
) -> User:
    if authorization and authorization.startswith(f"Bearer {MANAGEMENT_PREFIX}"):
        return await _management_user(request, db, authorization)
    user = await get_current_user(db, authorization, session_token)
    if not user.is_admin:
        raise HTTPException(403, "Administrator access required.")
    return user


async def get_plugin_manager_reader(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    session_token: str | None = Cookie(default=None, alias="session"),
) -> User:
    if authorization and authorization.startswith(f"Bearer {MANAGEMENT_PREFIX}"):
        return await _management_user(request, db, authorization)
    return await get_current_user(db, authorization, session_token)
