"""Resolve active notification providers from durable plugin registrations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.plugin_notification_provider import (
    PluginNotificationProviderRegistration,
)
from src.plugin_api.lifecycle import plugin_contributions_active
from src.plugin_api.runtime_client import PluginRuntimeClient, PluginRuntimeUnavailable

from .base import NotificationProvider
from .plugin import PluginNotificationProvider


async def get_notification_providers(
    db: AsyncSession,
) -> dict[str, NotificationProvider]:
    registrations = (
        await db.scalars(
            select(PluginNotificationProviderRegistration).where(
                PluginNotificationProviderRegistration.revoked_at.is_(None)
            )
        )
    ).all()
    if not registrations:
        return {}
    runtime = PluginRuntimeClient()
    try:
        plugins = await runtime.plugins()
    except PluginRuntimeUnavailable:
        return {}
    active = {
        (plugin["plugin_id"], str(plugin.get("installation_id")))
        for plugin in plugins
        if plugin_contributions_active(plugin)
    }
    return {
        registration.provider_id: PluginNotificationProvider(registration, runtime=runtime)
        for registration in registrations
        if (registration.plugin_id, str(registration.installation_id)) in active
    }
