"""Notification-provider contracts owned by the core application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.notification import Notification
from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.user import User


@dataclass(frozen=True)
class NotificationMessage:
    id: UUID
    kind: str
    title: str
    body: str
    media_type: str
    media_id: UUID
    event_at: int


@dataclass(frozen=True)
class ProviderDestination:
    user_id: UUID
    display: str


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    retryable: bool = False
    error: str | None = None


class NotificationProvider(Protocol):
    id: str
    name: str

    async def lookup_destination(
        self,
        db: AsyncSession,
        user: User,
        setting: NotificationProviderSetting | None,
    ) -> ProviderDestination | None: ...

    async def deliver(
        self,
        db: AsyncSession,
        destination: ProviderDestination,
        message: NotificationMessage,
    ) -> DeliveryResult: ...


def notification_message(notification: Notification) -> NotificationMessage:
    return NotificationMessage(
        id=notification.id,
        kind=notification.kind,
        title=notification.title,
        body=notification.body,
        media_type=notification.media_type,
        media_id=notification.media_id,
        event_at=notification.event_at,
    )
