"""Administrative plugin diagnostics endpoint coverage."""

import asyncio

import pytest
from fastapi import HTTPException

from src.api.routes import plugins


class FakeRuntimeClient:
    async def logs(self, plugin_id: str) -> dict:
        return {
            "plugin_id": plugin_id,
            "status": "stopped",
            "last_exit_code": 1,
            "events": [
                {"sequence": 1, "level": "info", "message": "started"},
                {"sequence": 2, "level": "error", "message": "failed"},
                {"sequence": 3, "level": "error", "message": "stopped"},
            ],
        }


def test_admin_diagnostics_can_filter_and_bound_events(monkeypatch) -> None:
    monkeypatch.setattr(plugins, "_client", FakeRuntimeClient())

    result = asyncio.run(
        plugins.plugin_logs("example.plugin", level="error", limit=1, admin=object())
    )

    assert result["status"] == "stopped"
    assert result["last_exit_code"] == 1
    assert [event["sequence"] for event in result["events"]] == [3]


def test_admin_diagnostics_reject_unknown_levels(monkeypatch) -> None:
    monkeypatch.setattr(plugins, "_client", FakeRuntimeClient())

    with pytest.raises(HTTPException) as raised:
        asyncio.run(plugins.plugin_logs("example.plugin", level="fatal", limit=100, admin=object()))

    assert raised.value.status_code == 400
