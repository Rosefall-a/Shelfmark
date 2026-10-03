"""Scoped session-domain operations for any Plugin API consumer."""

from __future__ import annotations

import time
from typing import Any, cast
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.session_manager import view
from src.core.geoip import geoip
from src.database.models.auth import UserSession
from src.database.models.user import User
from src.plugin_api.contracts import SessionRepresentation


def identifier(value: Any, name: str) -> UUID:
    """Reject missing, malformed, and non-string UUID inputs."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a UUID")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a UUID") from exc


async def dispatch_sessions(
    db: AsyncSession, *, user_id: UUID, method: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Run after gateway grant enforcement; scope self-service SQL to its caller."""
    admin_operation = method.startswith("sessions.admin.") or method == "sessions.geoip.status"
    if admin_operation:
        admin = await db.scalar(
            select(User).where(
                User.id == user_id, User.is_admin.is_(True), User.is_active.is_(True)
            )
        )
        if admin is None:
            raise PermissionError("administrator access is required")
    if method == "sessions.geoip.status":
        return {
            kind: {"configured": configured} for kind, configured in geoip.availability().items()
        }

    if method.endswith(".list"):
        return await _list_sessions(db, user_id, admin_operation, payload)
    return await _revoke_sessions(db, user_id, admin_operation, method, payload)


def _apply_filters(statement, payload: dict[str, Any], admin_operation: bool, now: int):
    """Validate bounded user/state/anomaly filters before applying them to SQL."""
    if payload.get("user_id") is not None:
        if not admin_operation:
            raise ValueError("user_id filter requires administrator session access")
        statement = statement.where(
            UserSession.user_id == identifier(payload["user_id"], "user_id")
        )
    state = payload.get("state")
    if state is not None:
        states = {
            "active": (UserSession.revoked_at.is_(None), UserSession.expires_at > now),
            "expired": (UserSession.revoked_at.is_(None), UserSession.expires_at <= now),
            "revoked": (UserSession.revoked_at.is_not(None),),
        }
        if not isinstance(state, str) or state not in states:
            raise ValueError("state must be active, expired, or revoked")
        statement = statement.where(*states[state])
    anomaly = payload.get("anomaly")
    if anomaly is not None:
        if not isinstance(anomaly, bool):
            raise ValueError("anomaly must be a boolean")
        statement = statement.where(
            UserSession.anomaly_reason.is_not(None)
            if anomaly
            else UserSession.anomaly_reason.is_(None)
        )
    return _apply_text_filters(statement, payload)


def _apply_text_filters(statement, payload: dict[str, Any]):
    """Apply literal text matching; wildcard inputs cannot change search semantics."""
    for key, maximum in (("q", 200), ("country", 128)):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            raise ValueError(f"{key} must be a string of at most {maximum} characters")
    if payload.get("country"):
        statement = statement.where(UserSession.geo_country.ilike(payload["country"].strip()))
    if (payload.get("q") or "").strip():
        needle = payload["q"].strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(
            or_(
                *[
                    column.ilike(f"%{needle}%", escape="\\")
                    for column in (
                        User.username,
                        UserSession.ip_address,
                        UserSession.user_agent,
                        UserSession.geo_country,
                        UserSession.geo_region,
                        UserSession.geo_city,
                        UserSession.geo_network_organization,
                    )
                ]
            )
        )
    return statement


def _session_dto(
    session: UserSession, username: str | None, user_id: UUID, current: UUID | None
) -> dict[str, Any]:
    """Reuse the source feature's credential-free serializer and validate its public DTO."""
    data = view(session, username=username)
    for key in ("created_at", "last_seen_at", "expires_at", "revoked_at"):
        if data[key] is not None:
            data[key] = int(data[key])
    data["active"] = data["state"] == "active"
    data["is_current"] = bool(
        session.user_id == user_id and session.id == current and data["active"]
    )
    return SessionRepresentation.model_validate(data).model_dump(mode="json")


async def _list_sessions(
    db: AsyncSession, user_id: UUID, admin_operation: bool, payload: dict[str, Any]
) -> dict[str, Any]:
    """Return one bounded page, including a cursor rather than silently truncating."""
    now = int(time.time())
    ownership = [] if admin_operation else [UserSession.user_id == user_id]
    limit = payload.get("limit", 50)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be an integer between 1 and 200")
    statement = select(UserSession, User.username).join(User, User.id == UserSession.user_id)
    statement = statement.where(*ownership)
    statement = _apply_filters(statement, payload, admin_operation, now)
    cursor = payload.get("cursor")
    if cursor is not None:
        anchor = await db.scalar(
            select(UserSession).where(UserSession.id == identifier(cursor, "cursor"), *ownership)
        )
        if anchor is None:
            raise ValueError("invalid session cursor")
        statement = statement.where(
            or_(
                UserSession.last_seen_at < anchor.last_seen_at,
                (UserSession.last_seen_at == anchor.last_seen_at) & (UserSession.id < anchor.id),
            )
        )
    rows = (
        await db.execute(
            statement.order_by(UserSession.last_seen_at.desc(), UserSession.id.desc()).limit(
                limit + 1
            )
        )
    ).all()
    current = payload.get("current_session_id")
    if current is not None:
        current = identifier(current, "current_session_id")
    return {
        "sessions": [
            _session_dto(session, username if admin_operation else None, user_id, current)
            for session, username in rows[:limit]
        ],
        "next_cursor": str(rows[limit - 1][0].id) if len(rows) > limit else None,
        "geoip": {"city": geoip.availability()["city"]},
    }


async def _revoke_sessions(
    db: AsyncSession, user_id: UUID, admin_operation: bool, method: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Require confirmation and ownership in the write query; retain revoked metadata."""
    ownership = [] if admin_operation else [UserSession.user_id == user_id]
    if payload.get("confirmed") is not True:
        raise ValueError("explicit revocation confirmation is required")
    revocation = update(UserSession).where(*ownership, UserSession.revoked_at.is_(None))
    if method.endswith(".revoke"):
        session_id = identifier(payload.get("session_id"), "session_id")
        revocation = revocation.where(UserSession.id == session_id)
    elif method.endswith(".revoke_user"):
        revocation = revocation.where(
            UserSession.user_id == identifier(payload.get("user_id"), "user_id")
        )
    current_revoked = False
    current = payload.get("current_session_id")
    if current:
        current_row = await db.scalar(
            select(UserSession).where(
                UserSession.id == identifier(current, "current_session_id"),
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
        )
        current_revoked = current_row is not None and (
            method.endswith(".revoke_all")
            or method.endswith(".revoke_user")
            and str(current_row.user_id) == payload.get("user_id")
        )
    result = cast(
        CursorResult[Any], await db.execute(revocation.values(revoked_at=int(time.time())))
    )
    if method.endswith(".revoke") and not result.rowcount:
        raise LookupError("session not found or already revoked")
    await db.commit()
    if method.endswith(".revoke"):
        return {"revoked": True, "session_id": str(session_id)}
    return {"revoked": result.rowcount, "current_revoked": current_revoked}
