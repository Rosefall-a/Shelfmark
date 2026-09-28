"""Shared browser-session creation and anomaly handling."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import SESSION_TTL_SECONDS, hash_token
from src.core.geoip import geoip
from src.database.models.auth import UserSession
from src.database.models.notification import Notification
from src.database.models.notification_delivery import NotificationDelivery
from src.database.models.user import User
from src.features.notification_providers.registry import PROVIDER_IDS


@dataclass(frozen=True)
class SessionContext:
    """Raw token returned only to the login response plus its database row."""

    token: str
    session: UserSession


def request_ip(request: Request) -> str | None:
    """Read the reverse-proxy client address, falling back to the direct peer."""
    value = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
    return value.strip() if value and value.strip() else None


def request_user_agent(request: Request) -> str | None:
    """Return a bounded browser user-agent value."""
    value = request.headers.get("user-agent")
    return value[:1024] if value else None


def _location_key(session: UserSession | None) -> str | None:
    return session.geo_country or session.geo_region if session else None


def _set_anomaly(previous: UserSession | None, current: UserSession) -> None:
    old, new = _location_key(previous), _location_key(current)
    if old and new and old != new:
        current.anomaly_reason = f"New geographic location: {new} (previous: {old})."
        current.anomaly_previous_location = old


async def _queue_anomaly_notification(db: AsyncSession, user: User, session: UserSession) -> None:
    if not session.anomaly_reason:
        return
    now = int(time.time())
    statement = (
        pg_insert(Notification)
        .values(
            user_id=user.id,
            kind="session_anomaly",
            title="New sign-in location",
            body=(
                f"A session was created from {session.geo_country or 'an unavailable location'} "
                f"at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(session.created_at))}. "
                "Location is approximate and may be inaccurate."
            ),
            media_type="system",
            media_id=session.id,
            event_at=session.created_at,
            created_at=now,
            dedupe_key=f"session-anomaly:{session.id}",
        )
        .on_conflict_do_nothing(constraint="uq_notifications_user_dedupe")
        .returning(Notification.id)
    )
    notification_id = await db.scalar(statement)
    if notification_id:
        for provider_id in PROVIDER_IDS:
            db.add(
                NotificationDelivery(
                    notification_id=notification_id,
                    provider_id=provider_id,
                    status="pending",
                    attempts=0,
                    next_attempt_at=now,
                )
            )


async def create_session(db: AsyncSession, user: User, request: Request) -> SessionContext:
    """Create an existing-style opaque browser session and its metadata."""
    now = int(time.time())
    ip = request_ip(request)
    location = geoip.lookup(ip)
    previous = await db.scalar(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.created_at.desc())
        .limit(1)
    )
    token = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=now + SESSION_TTL_SECONDS,
        created_at=now,
        last_seen_at=now,
        ip_address=ip,
        user_agent=request_user_agent(request),
        geo_country=location.country,
        geo_region=location.region,
        geo_city=location.city,
        geo_latitude=location.latitude,
        geo_longitude=location.longitude,
        geo_network_type=location.network_type,
        geo_network_label=location.network_label,
        geo_network_number=location.network_number,
        geo_network_organization=location.network_organization,
    )
    _set_anomaly(previous, session)
    db.add(session)
    await db.flush()
    await _queue_anomaly_notification(db, user, session)
    return SessionContext(token=token, session=session)


async def purge_old_sessions(db: AsyncSession, retention_seconds: int = 30 * 86400) -> int:
    """Delete expired or revoked session metadata after a bounded retention period."""
    cutoff = int(time.time()) - retention_seconds
    result = await db.execute(
        delete(UserSession).where(
            or_(UserSession.expires_at < cutoff, UserSession.revoked_at < cutoff)
        )
    )
    await db.commit()
    return result.rowcount


def session_state(session: UserSession, now: int | None = None) -> str:
    """Classify a stored session without equating database existence with activity."""
    now = int(time.time()) if now is None else now
    if session.revoked_at is not None:
        return "revoked"
    if session.expires_at <= now:
        return "expired"
    return "active"
