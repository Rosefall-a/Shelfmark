"""Adapter from durable plugin registrations to the core provider contract."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.plugin_notification_provider import (
    PluginNotificationProviderRegistration,
)
from src.database.models.user import User
from src.plugin_api.contracts import (
    NotificationDeliveryRepresentation,
    NotificationDeliveryResult,
)
from src.plugin_api.grants import has_capability_grant, installation_is_executable
from src.plugin_api.runtime_client import (
    PluginRuntimeClient,
    PluginRuntimeRequestError,
    PluginRuntimeUnavailable,
)

from .base import DeliveryResult, NotificationMessage, ProviderDestination


class PluginNotificationProvider:
    """Core-controlled delivery adapter for one registered plugin provider."""

    def __init__(
        self,
        registration: PluginNotificationProviderRegistration,
        runtime: PluginRuntimeClient | None = None,
    ) -> None:
        self.registration = registration
        self.id = registration.provider_id
        self.name = registration.name
        self._runtime = runtime or PluginRuntimeClient()

    async def lookup_destination(
        self,
        db: AsyncSession,
        user: User,
        setting: NotificationProviderSetting | None,
    ) -> ProviderDestination | None:
        if setting is None or not setting.enabled or setting.user_id != user.id:
            return None
        allowed = await self._authorized(db, user.id)
        if not allowed:
            return None
        return ProviderDestination(user_id=user.id, display=self.name)

    async def _authorized(self, db: AsyncSession, user_id: UUID) -> bool:
        """Recheck durable registration, grants and live installation at delivery."""
        allowed = await has_capability_grant(
            db,
            plugin_id=self.registration.plugin_id,
            installation_id=self.registration.installation_id,
            capability="notification_providers.deliver",
            user_id=user_id,
        )
        if not allowed:
            return False
        active_user = await db.scalar(
            select(User.id).where(User.id == user_id, User.is_active.is_(True))
        )
        if active_user is None:
            return False
        registration = await db.scalar(
            select(PluginNotificationProviderRegistration.id).where(
                PluginNotificationProviderRegistration.id == self.registration.id,
                PluginNotificationProviderRegistration.plugin_id == self.registration.plugin_id,
                PluginNotificationProviderRegistration.installation_id
                == self.registration.installation_id,
                PluginNotificationProviderRegistration.revoked_at.is_(None),
            )
        )
        if registration is None:
            return False
        installed = await self._runtime.plugins()
        matches = [
            item for item in installed if item.get("plugin_id") == self.registration.plugin_id
        ]
        return (
            len(matches) == 1
            and matches[0].get("installation_id") == str(self.registration.installation_id)
            and installation_is_executable(matches[0])
        )

    async def deliver(
        self,
        db: AsyncSession,
        destination: ProviderDestination,
        message: NotificationMessage,
    ) -> DeliveryResult:
        work = NotificationDeliveryRepresentation(
            notification_id=message.id,
            kind=message.kind,
            title=message.title,
            body=message.body,
            media_type=message.media_type,
            media_id=message.media_id,
            event_at=message.event_at,
        )
        try:
            if not await self._authorized(db, destination.user_id):
                return DeliveryResult(
                    success=False, error="Plugin provider authorization is unavailable."
                )
            response = await self._runtime.action(
                self.registration.plugin_id,
                self.registration.action_id,
                {
                    "delivery": work.model_dump(mode="json"),
                    "user_id": str(destination.user_id),
                },
                user_id=str(destination.user_id),
            )
            result = NotificationDeliveryResult.model_validate(response)
        except (PluginRuntimeRequestError, PluginRuntimeUnavailable, ValueError) as exc:
            return DeliveryResult(success=False, retryable=True, error=str(exc)[:512])
        return DeliveryResult(
            success=result.success,
            retryable=result.retryable,
            error=result.error,
        )
