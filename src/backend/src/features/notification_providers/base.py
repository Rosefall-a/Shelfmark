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
    value: str
    display: str

@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    error: str | None = None

class NotificationProvider(Protocol):
    id: str
    name: str
    def available(self) -> bool: ...
    async def lookup_destination(self, db: AsyncSession, user: User, setting: NotificationProviderSetting | None) -> ProviderDestination | None: ...
    async def deliver(self, destination: ProviderDestination, message: NotificationMessage) -> DeliveryResult: ...
    def enabled_for_user(self, setting: NotificationProviderSetting | None) -> bool: ...

def notification_message(notification: Notification) -> NotificationMessage:
    return NotificationMessage(notification.id, notification.kind, notification.title, notification.body, notification.media_type, notification.media_id, notification.event_at)
