from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from src.api.routes import plugins


class FakeRuntimeClient:
    def __init__(self, installation_id) -> None:
        self.installation_id = installation_id
        self.action = AsyncMock(
            return_value={
                "completed": True,
                "plugin_id": "spoofed.plugin",
                "action": "spoofed-action",
            }
        )
        self.save_secret = AsyncMock()

    async def plugin_ui(self, _plugin_id: str) -> dict:
        return {
            "actions": [
                {
                    "id": "revoke-session",
                    "capability": {"name": "sessions.revoke", "version": 1},
                }
            ]
        }

    async def plugins(self) -> list[dict]:
        return [
            {
                "plugin_id": "example.plugin",
                "installation_id": str(self.installation_id),
                "enabled": True,
                "compatible": True,
                "status": "running",
                "health": "healthy",
            }
        ]


@pytest.mark.asyncio
async def test_action_dispatch_requires_exact_installation_grant(monkeypatch) -> None:
    installation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    runtime = FakeRuntimeClient(installation_id)
    grant = AsyncMock(return_value=False)
    monkeypatch.setattr(plugins, "_client", runtime)
    monkeypatch.setattr(plugins, "has_capability_grant", grant)

    with pytest.raises(HTTPException) as denied:
        await plugins.plugin_action(
            "example.plugin",
            "revoke-session",
            plugins.PluginSettingsIn(values={}),
            ANY,
            user,
        )

    assert denied.value.status_code == 403
    runtime.action.assert_not_awaited()
    grant.assert_awaited_once_with(
        ANY,
        plugin_id="example.plugin",
        installation_id=installation_id,
        capability="sessions.revoke",
        user_id=user.id,
        capability_version=1,
    )


@pytest.mark.asyncio
async def test_action_result_cannot_spoof_host_identity(monkeypatch) -> None:
    installation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    runtime = FakeRuntimeClient(installation_id)
    monkeypatch.setattr(plugins, "_client", runtime)
    monkeypatch.setattr(
        plugins,
        "has_capability_grant",
        AsyncMock(return_value=True),
    )

    result = await plugins.plugin_action(
        "example.plugin",
        "revoke-session",
        plugins.PluginSettingsIn(values={}),
        ANY,
        user,
    )

    assert result["plugin_id"] == "example.plugin"
    assert result["action"] == "revoke-session"
    assert UUID(result["request_id"])
    runtime.action.assert_awaited_once()


@pytest.mark.asyncio
async def test_secret_write_requires_storage_grant_and_stays_runtime_private(
    monkeypatch,
) -> None:
    installation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    runtime = FakeRuntimeClient(installation_id)
    grant = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(plugins, "_client", runtime)
    monkeypatch.setattr(plugins, "has_capability_grant", grant)

    with pytest.raises(HTTPException) as denied:
        await plugins.save_plugin_secret(
            "example.plugin",
            "webhook",
            {"value": "secret-value"},
            ANY,
            user,
        )
    assert denied.value.status_code == 403
    runtime.save_secret.assert_not_awaited()

    result = await plugins.save_plugin_secret(
        "example.plugin",
        "webhook",
        {"value": "secret-value"},
        ANY,
        user,
    )

    assert result == {
        "plugin_id": "example.plugin",
        "key": "webhook",
        "saved": True,
    }
    runtime.save_secret.assert_awaited_once_with(
        "example.plugin",
        "secrets/webhook",
        "secret-value",
    )
    assert all("secret-value" not in str(call) for call in grant.await_args_list)


@pytest.mark.asyncio
async def test_native_frontend_asset_requires_native_grant(monkeypatch) -> None:
    user = SimpleNamespace(id=uuid4())
    runtime = SimpleNamespace(
        native_frontend_asset=AsyncMock(return_value=b"export default () => {}")
    )
    monkeypatch.setattr(plugins, "_client", runtime)
    monkeypatch.setattr(
        plugins,
        "_plugin_and_capabilities",
        AsyncMock(return_value=({}, frozenset())),
    )

    with pytest.raises(HTTPException) as denied:
        await plugins.plugin_native_frontend(
            "example.plugin",
            "native/index.js",
            ANY,
            user,
        )

    assert denied.value.status_code == 403
    runtime.native_frontend_asset.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_payload_requires_declared_scoped_capability(monkeypatch) -> None:
    installation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    runtime = FakeRuntimeClient(installation_id)
    runtime.plugin_ui = AsyncMock(
        return_value={
            "actions": [
                {
                    "id": "revoke-session",
                    "capability": {"name": "sessions.revoke", "version": 1},
                }
            ],
            "contextual_actions": [
                {
                    "id": "game-revoke",
                    "location": "game",
                    "action_id": "revoke-session",
                }
            ],
        }
    )
    grant = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(plugins, "_client", runtime)
    monkeypatch.setattr(plugins, "has_capability_grant", grant)

    with pytest.raises(HTTPException) as denied:
        await plugins.plugin_action(
            "example.plugin",
            "revoke-session",
            plugins.PluginActionIn(
                values={},
                context=plugins.PluginActionContext(kind="game", resource_id="game-1"),
            ),
            ANY,
            user,
        )

    assert denied.value.status_code == 403
    runtime.action.assert_not_awaited()
    assert grant.await_args_list[-1].kwargs["capability"] == "frontend.context.game"
