"""Core-owned notification delivery creation, retry, and terminal state."""

from __future__ import annotations

import logging
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.notification import Notification
from src.database.models.notification_delivery import NotificationDelivery
from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.user import User

from .base import notification_message
from .registry import get_notification_providers

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


async def ensure_deliveries(db: AsyncSession, notification_ids: list[UUID]) -> None:
    """Create one pending delivery per active provider without duplicating work."""
    if not notification_ids:
        return
    providers = await get_notification_providers(db)
    if not providers:
        return
    existing = set(
        (
            await db.execute(
                select(
                    NotificationDelivery.notification_id, NotificationDelivery.provider_id
                ).where(NotificationDelivery.notification_id.in_(notification_ids))
            )
        ).all()
    )
    now = int(time.time())
    for notification_id in notification_ids:
        for provider_id in providers:
            if (notification_id, provider_id) not in existing:
                db.add(
                    NotificationDelivery(
                        notification_id=notification_id,
                        provider_id=provider_id,
                        status="pending",
                        attempts=0,
                        next_attempt_at=now,
                    )
                )
    await db.flush()


async def process_pending_deliveries(db: AsyncSession, limit: int = 50) -> int:
    """Process a bounded batch while core retains retry and preference authority."""
    now = int(time.time())
    deliveries = (
        (
            await db.execute(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.status.in_(("pending", "retry")),
                    NotificationDelivery.next_attempt_at <= now,
                )
                .order_by(NotificationDelivery.next_attempt_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    if not deliveries:
        return 0

    providers = await get_notification_providers(db)
    delivered = 0
    for delivery in deliveries:
        notification = await db.get(Notification, delivery.notification_id)
        if notification is None:
            delivery.status = "failed"
            delivery.last_error = "Notification no longer exists."
            logger.warning(
                "Notification delivery failed: delivery_id=%s provider_id=%s reason=notification_missing",
                delivery.id,
                delivery.provider_id,
            )
            continue
        provider = providers.get(delivery.provider_id)
        if provider is None:
            delivery.status = "failed"
            delivery.last_error = "Provider is unavailable."
            logger.warning(
                "Notification delivery failed: delivery_id=%s provider_id=%s reason=provider_unavailable",
                delivery.id,
                delivery.provider_id,
            )
            continue
        user = await db.get(User, notification.user_id)
        if user is None:
            delivery.status = "failed"
            delivery.last_error = "User no longer exists."
            continue
        setting = await db.scalar(
            select(NotificationProviderSetting).where(
                NotificationProviderSetting.user_id == user.id,
                NotificationProviderSetting.provider_id == delivery.provider_id,
            )
        )
        destination = await provider.lookup_destination(db, user, setting)
        if destination is None:
            delivery.status = "skipped"
            delivery.last_error = None
            logger.info(
                "Notification delivery skipped: delivery_id=%s provider_id=%s user_id=%s",
                delivery.id,
                delivery.provider_id,
                user.id,
            )
            continue

        delivery.attempts += 1
        delivery.attempted_at = now
        result = await provider.deliver(db, destination, notification_message(notification))
        if result.success:
            delivery.status = "sent"
            delivery.last_error = None
            delivered += 1
            logger.info(
                "Notification delivered: delivery_id=%s provider_id=%s attempt=%s",
                delivery.id,
                delivery.provider_id,
                delivery.attempts,
            )
        elif not result.retryable or delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "failed"
            delivery.last_error = result.error
            logger.warning(
                "Notification delivery failed: delivery_id=%s provider_id=%s attempt=%s retryable=%s",
                delivery.id,
                delivery.provider_id,
                delivery.attempts,
                result.retryable,
            )
        else:
            delivery.status = "retry"
            delivery.last_error = result.error
            delivery.next_attempt_at = now + 60 * (2 ** (delivery.attempts - 1))
            logger.warning(
                "Notification delivery scheduled for retry: delivery_id=%s provider_id=%s attempt=%s",
                delivery.id,
                delivery.provider_id,
                delivery.attempts,
            )
    await db.commit()
    return delivered
