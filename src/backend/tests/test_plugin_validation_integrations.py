"""Validation coverage for the first Plugin API integration examples."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.plugin_api import (
    Capability,
    CapabilityRef,
    PermissionGrant,
    PluginIdentity,
    RequestContext,
)
from src.plugin_api.contracts import GameRepresentation
from src.plugin_api.coordinators import (
    MetadataCandidate,
    MetadataProviderRequest,
    NotificationRequest,
)
from src.plugin_api.validation import (
    DiscordValidationPlugin,
    MetadataValidationPlugin,
    NotificationValidationPlugin,
    PlayniteValidationPlugin,
    ValidationGateway,
    ValidationGatewayError,
    validation_event,
)

USER_A = UUID(int=10)
USER_B = UUID(int=11)
INSTALL_A = UUID(int=20)
DEVICE_A = UUID(int=30)


def grant(
    plugin: PluginIdentity,
    capability: Capability,
    user_id: UUID | None = None,
) -> PermissionGrant:
    return PermissionGrant(
        plugin_id=plugin.plugin_id,
        installation_id=plugin.installation_id,
        capability=CapabilityRef(name=capability),
        user_id=user_id,
        device_id=DEVICE_A if plugin.plugin_id == "playnite.validation" else None,
        granted_at=datetime.now(timezone.utc),
    )


def plugin_context(
    plugin: PluginIdentity,
    capability: Capability,
    user_id: UUID | None = None,
) -> RequestContext:
    return RequestContext(
        request_id=UUID(int=100),
        application_id=UUID(int=1),
        gateway_id=UUID(int=2),
        plugin=plugin,
        user=({"user_id": user_id, "authenticated": True} if user_id is not None else None),
        requested_capability=CapabilityRef(name=capability),
    )


@pytest.mark.asyncio
async def test_notification_provider_uses_core_coordinator_contract() -> None:
    plugin = PluginIdentity(
        plugin_id="notify.validation",
        installation_id=INSTALL_A,
        version="1.0.0",
    )
    provider = NotificationValidationPlugin()
    gateway = ValidationGateway(
        grants=(grant(plugin, Capability.NOTIFICATIONS_SEND, USER_A),),
        notifications={plugin.plugin_id: provider},
    )

    result = await gateway.send_notification(
        plugin_context(plugin, Capability.NOTIFICATIONS_SEND, USER_A),
        NotificationRequest(
            notification_id=UUID(int=40),
            user_id=USER_A,
            title="Validation",
            body="Notification provider works",
            created_at=datetime.now(timezone.utc),
        ),
    )

    assert result.delivered is True
    assert provider.delivered == [UUID(int=40)]


@pytest.mark.asyncio
async def test_metadata_provider_returns_normalized_results() -> None:
    plugin = PluginIdentity(
        plugin_id="metadata.validation",
        installation_id=INSTALL_A,
        version="1.0.0",
    )
    provider = MetadataValidationPlugin(
        candidates=(
            MetadataCandidate(external_id="g-1", title="Example Game", provider="validation"),
            MetadataCandidate(external_id="g-2", title="Other", provider="validation"),
        )
    )
    gateway = ValidationGateway(
        grants=(grant(plugin, Capability.GAMES_READ, USER_A),),
        metadata={plugin.plugin_id: provider},
    )

    results = await gateway.search_metadata(
        plugin_context(plugin, Capability.GAMES_READ, USER_A),
        MetadataProviderRequest(request_id=UUID(int=41), user_id=USER_A, query="example"),
    )

    assert [item.external_id for item in results] == ["g-1"]


def test_discord_scopes_events_and_uses_plugin_storage() -> None:
    plugin = PluginIdentity(
        plugin_id="discord.validation",
        installation_id=INSTALL_A,
        version="1.0.0",
    )
    gateway = ValidationGateway(
        grants=(
            grant(plugin, Capability.PLUGIN_STORAGE),
            grant(plugin, Capability.EVENTS_SUBSCRIBE, USER_A),
        )
    )
    discord = DiscordValidationPlugin(gateway=gateway, plugin=plugin)

    asyncio.run(discord.link_user("discord-123", USER_A))
    discord.subscribe(USER_A)

    gateway.publish_event(
        validation_event(
            event_type="game.updated",
            user_id=USER_A,
            payload={"game": "g-1"},
        )
    )
    gateway.publish_event(
        validation_event(
            event_type="game.updated",
            user_id=USER_B,
            payload={"game": "g-2"},
        )
    )

    assert len(discord.received_events()) == 1
    assert discord.received_events()[0].user_id == USER_A
    assert gateway.storage["discord.validation"]["users/discord-123"] == str(USER_A).encode()


@pytest.mark.asyncio
async def test_playnite_uses_scoped_device_identity() -> None:
    plugin = PluginIdentity(
        plugin_id="playnite.validation",
        installation_id=INSTALL_A,
        version="1.0.0",
    )
    gateway = ValidationGateway(
        grants=(
            grant(plugin, Capability.GAMES_READ, USER_A),
            grant(plugin, Capability.GAMES_WRITE, USER_A),
        )
    )
    playnite = PlayniteValidationPlugin(
        gateway=gateway,
        plugin=plugin,
        device_id=DEVICE_A,
    )

    context = playnite.validate_scoped_identity(USER_A)
    assert context.device_id == DEVICE_A
    assert context.user is not None
    assert context.user.user_id == USER_A

    synced = await playnite.sync_game(
        USER_A,
        GameRepresentation(id=UUID(int=50), title="Playnite Example"),
    )
    assert synced.title == "Playnite Example"


@pytest.mark.asyncio
async def test_gateway_is_default_deny_and_user_scoped() -> None:
    plugin = PluginIdentity(
        plugin_id="notify.validation",
        installation_id=INSTALL_A,
        version="1.0.0",
    )
    provider = NotificationValidationPlugin()
    gateway = ValidationGateway(
        grants=(grant(plugin, Capability.NOTIFICATIONS_SEND, USER_A),),
        notifications={plugin.plugin_id: provider},
    )

    with pytest.raises(ValidationGatewayError):
        await gateway.send_notification(
            plugin_context(plugin, Capability.NOTIFICATIONS_SEND, USER_B),
            NotificationRequest(
                notification_id=UUID(int=51),
                user_id=USER_B,
                title="Denied",
                body="Must not deliver",
                created_at=datetime.now(timezone.utc),
            ),
        )


def test_plugin_storage_is_namespaced() -> None:
    plugin_a = PluginIdentity(
        plugin_id="discord.validation",
        installation_id=INSTALL_A,
        version="1.0.0",
    )
    plugin_b = PluginIdentity(
        plugin_id="metadata.validation",
        installation_id=INSTALL_A,
        version="1.0.0",
    )
    gateway = ValidationGateway(
        grants=(
            grant(plugin_a, Capability.PLUGIN_STORAGE),
            grant(plugin_b, Capability.PLUGIN_STORAGE),
        )
    )

    gateway.storage_put(
        plugin_context(plugin_a, Capability.PLUGIN_STORAGE, USER_A),
        "secret",
        b"a",
    )
    gateway.storage_put(
        plugin_context(plugin_b, Capability.PLUGIN_STORAGE, USER_A),
        "secret",
        b"b",
    )

    assert (
        gateway.storage_get(plugin_context(plugin_a, Capability.PLUGIN_STORAGE, USER_A), "secret")
        == b"a"
    )
    assert (
        gateway.storage_get(plugin_context(plugin_b, Capability.PLUGIN_STORAGE, USER_A), "secret")
        == b"b"
    )
