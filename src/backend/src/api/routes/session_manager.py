"""Authenticated APIs for user and administrator browser-session management."""

from __future__ import annotations

import time
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_admin, get_current_user, hash_token
from src.core.geoip import GeoIpProvider, geoip
from src.core.session_manager import session_state
from src.database.models.auth import UserSession
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def view(
    session: UserSession, current_hash: str | None = None, username: str | None = None
) -> dict:
    """Serialize a session without including either raw or hashed credentials."""
    state = session_state(session)
    return {
        "id": str(session.id),
        "user_id": str(session.user_id),
        "username": username,
        "ip_address": session.ip_address,
        "user_agent": session.user_agent,
        "location": {
            "country": session.geo_country,
            "region": session.geo_region,
            "city": session.geo_city,
            "latitude": session.geo_latitude,
            "longitude": session.geo_longitude,
            "network_type": session.geo_network_type,
            "network_label": session.geo_network_label,
            "network_number": session.geo_network_number,
            "network_organization": session.geo_network_organization,
        },
        "created_at": session.created_at,
        "last_seen_at": session.last_seen_at,
        "expires_at": session.expires_at,
        "revoked_at": session.revoked_at,
        "state": state,
        "is_current": bool(
            current_hash and session.token_hash == current_hash and state == "active"
        ),
        "anomaly": {
            "reason": session.anomaly_reason,
            "previous_location": session.anomaly_previous_location,
        },
    }


async def revoke_session(db: AsyncSession, session_id: UUID, user_id: UUID | None = None) -> bool:
    """Mark a session revoked, optionally requiring ownership by a user."""
    statement = update(UserSession).where(
        UserSession.id == session_id, UserSession.revoked_at.is_(None)
    )
    if user_id is not None:
        statement = statement.where(UserSession.user_id == user_id)
    result = await db.execute(statement.values(revoked_at=int(time.time())))
    await db.commit()
    return bool(result.rowcount)


@router.get("/me")
async def list_my_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    session_token: str | None = Cookie(default=None, alias="session"),
) -> list[dict]:
    """Return only the authenticated user's browser sessions."""
    rows = (
        await db.scalars(
            select(UserSession)
            .where(UserSession.user_id == user.id)
            .order_by(UserSession.last_seen_at.desc())
        )
    ).all()
    current_hash = hash_token(session_token) if session_token else None
    return [view(row, current_hash) for row in rows]


@router.delete("/me/all")
async def revoke_all_my_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Revoke every active browser session belonging to the current user."""
    result = await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=int(time.time()))
    )
    await db.commit()
    return {"revoked": result.rowcount}


@router.delete("/me/{session_id}")
async def revoke_my_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Revoke a session owned by the current user."""
    if not await revoke_session(db, session_id, user.id):
        raise HTTPException(404, "Session not found or already revoked.")
    return {"status": "revoked"}


@router.get("/admin")
async def list_all_sessions(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
    user_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    state: str | None = Query(default=None, pattern="^(active|expired|revoked)$"),
    country: str | None = Query(default=None, max_length=128),
    anomaly: bool | None = Query(default=None),
) -> list[dict]:
    """Return session metadata for administrators with optional filtering."""
    del admin
    statement = (
        select(UserSession, User.username)
        .join(User, User.id == UserSession.user_id)
        .order_by(UserSession.last_seen_at.desc())
    )
    if user_id is not None:
        statement = statement.where(UserSession.user_id == user_id)
    if country:
        statement = statement.where(UserSession.geo_country.ilike(country.strip()))
    if anomaly is True:
        statement = statement.where(UserSession.anomaly_reason.is_not(None))
    needle = q.strip().lower() if q else None
    result = []
    for session, username in (await db.execute(statement)).all():
        if state is not None and session_state(session) != state:
            continue
        searchable = (
            username,
            session.ip_address,
            session.user_agent,
            session.geo_country,
            session.geo_region,
        )
        if needle and not any(needle in (value or "").lower() for value in searchable):
            continue
        result.append(view(session, username=username))
    return result


@router.delete("/admin/all")
async def revoke_all_sessions(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict[str, int]:
    """Revoke every active browser session on the server."""
    del admin
    result = await db.execute(
        update(UserSession)
        .where(UserSession.revoked_at.is_(None))
        .values(revoked_at=int(time.time()))
    )
    await db.commit()
    return {"revoked": result.rowcount}


@router.delete("/admin/user/{user_id}")
async def revoke_all_user_sessions(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict[str, int]:
    """Revoke every active browser session belonging to one user."""
    del admin
    result = await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=int(time.time()))
    )
    await db.commit()
    return {"revoked": result.rowcount}


@router.delete("/admin/{session_id}")
async def revoke_admin_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict[str, str]:
    """Revoke any browser session as an administrator."""
    del admin
    if not await revoke_session(db, session_id):
        raise HTTPException(404, "Session not found or already revoked.")
    return {"status": "revoked"}


@router.get("/admin/geoip/status")
async def geoip_status(admin: User = Depends(get_current_admin)) -> dict[str, object]:
    """Return availability of each optional local GeoIP database."""
    del admin
    return {
        "city": {"configured": geoip._get_reader() is not None, "path": str(geoip.path)},
        "country": {
            "configured": geoip._get_country_reader() is not None,
            "path": str(geoip.country_path),
        },
        "network": {"configured": geoip._get_asn_reader() is not None, "path": str(geoip.asn_path)},
    }


@router.post("/admin/geoip")
async def upload_geoip(
    file: UploadFile = File(...),
    kind: str = Query(default="city", pattern="^(city|country|network)$"),
    admin: User = Depends(get_current_admin),
) -> dict[str, object]:
    """Validate and atomically replace one optional local GeoIP database."""
    del admin
    data = await file.read()
    if not data or len(data) > 256 * 1024 * 1024:
        raise HTTPException(400, "Invalid GeoIP database size.")
    paths = {"city": geoip.path, "country": geoip.country_path, "network": geoip.asn_path}
    validators = {
        "city": lambda provider: provider._get_reader(),
        "country": lambda provider: provider._get_country_reader(),
        "network": lambda provider: provider._get_asn_reader(),
    }
    path = paths[kind]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(data)
        validator = validators[kind]
        probe = GeoIpProvider(
            str(temporary) if kind == "city" else str(geoip.path),
            str(temporary) if kind == "country" else str(geoip.country_path),
            str(temporary) if kind == "network" else str(geoip.asn_path),
        )
        if validator(probe) is None:
            temporary.unlink(missing_ok=True)
            raise HTTPException(400, "Invalid or unsupported GeoIP database.")
        temporary.replace(path)
        geoip.reset()
    except HTTPException:
        raise
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not store GeoIP database: {exc}") from exc
    return {"configured": True, "kind": kind, "path": str(path)}
