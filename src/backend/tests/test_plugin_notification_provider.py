from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest

from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.plugin_notification_provider import (
    PluginNotificationProviderRegistration,
)
from src.features.notification_providers.base import NotificationMessage
from src.features.notification_providers.plugin import PluginNotificationProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["disabled", "quarantined", "failed", "stopping"])
async def test_provider_obtained_before_transition_cannot_deliver_afterward(monkeypatch, status):
    registration = SimpleNamespace(
        id=uuid4(),
        plugin_id="contract.provider",
        installation_id=uuid4(),
        provider_id="contract.provider.delivery",
        name="Contract",
        action_id="deliver",
    )
    runtime = AsyncMock()
    installed = {
        "plugin_id": registration.plugin_id,
        "installation_id": str(registration.installation_id),
        "enabled": True,
        "compatible": True,
        "status": "running",
        "health": "healthy",
    }
    runtime.plugins.return_value = [installed]
    provider = PluginNotificationProvider(registration, runtime=runtime)
    monkeypatch.setattr(
        "src.features.notification_providers.plugin.has_capability_grant",
        AsyncMock(return_value=True),
    )
    user = SimpleNamespace(id=uuid4())
    destination = await provider.lookup_destination(
        AsyncMock(), user, SimpleNamespace(enabled=True, user_id=user.id)
    )
    assert destination is not None
    installed["status"] = status
    result = await provider.deliver(
        AsyncMock(),
        destination,
        NotificationMessage(
            id=uuid4(),
            kind="contract",
            title="Title",
            body="Body",
            media_type="plugin",
            media_id=uuid4(),
            event_at=1,
        ),
    )
    assert not result.success
    runtime.action.assert_not_awaited()


@pytest.mark.asyncio
async def test_plugin_provider_requires_delivery_grant(monkeypatch) -> None:
    registration = PluginNotificationProviderRegistration(
        plugin_id="example.plugin",
        installation_id=uuid4(),
        provider_id="example.plugin.webhook",
        name="Example webhook",
        action_id="deliver",
    )
    provider = PluginNotificationProvider(registration, runtime=AsyncMock())
    user = type("User", (), {"id": uuid4()})()
    setting = NotificationProviderSetting(
        user_id=user.id,
        provider_id=registration.provider_id,
        enabled=True,
    )
    grant = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "src.features.notification_providers.plugin.has_capability_grant",
        grant,
    )

    assert await provider.lookup_destination(AsyncMock(), user, setting) is None
    grant.assert_awaited_once_with(
        ANY,
        plugin_id=registration.plugin_id,
        installation_id=registration.installation_id,
        capability="notification_providers.deliver",
        user_id=user.id,
    )


@pytest.mark.asyncio
async def test_plugin_provider_dispatches_minimized_delivery_contract(monkeypatch) -> None:
    registration = PluginNotificationProviderRegistration(
        plugin_id="example.plugin",
        installation_id=uuid4(),
        provider_id="example.plugin.webhook",
        name="Example webhook",
        action_id="deliver",
    )
    runtime = AsyncMock()
    runtime.plugins.return_value = [
        {
            "plugin_id": registration.plugin_id,
            "installation_id": str(registration.installation_id),
            "enabled": True,
            "compatible": True,
            "status": "running",
            "health": "healthy",
        }
    ]
    runtime.action.return_value = {
        "success": True,
        "retryable": False,
        "error": None,
    }
    provider = PluginNotificationProvider(registration, runtime=runtime)
    user = type("User", (), {"id": uuid4()})()
    setting = NotificationProviderSetting(
        user_id=user.id,
        provider_id=registration.provider_id,
        enabled=True,
    )
    monkeypatch.setattr(
        "src.features.notification_providers.plugin.has_capability_grant",
        AsyncMock(return_value=True),
    )
    destination = await provider.lookup_destination(AsyncMock(), user, setting)
    assert destination is not None
    message = NotificationMessage(
        id=uuid4(),
        kind="plugin",
        title="Title",
        body="Body",
        media_type="plugin",
        media_id=uuid4(),
        event_at=1,
    )

    result = await provider.deliver(AsyncMock(), destination, message)

    assert result.success
    runtime.action.assert_awaited_once()
    plugin_id, action_id, payload = runtime.action.await_args.args
    assert (plugin_id, action_id) == ("example.plugin", "deliver")
    assert payload["user_id"] == str(user.id)
    assert set(payload["delivery"]) == {
        "notification_id",
        "kind",
        "title",
        "body",
        "media_type",
        "media_id",
        "event_at",
    }
    assert "secret" not in str(payload).lower()
