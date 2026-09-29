from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

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
