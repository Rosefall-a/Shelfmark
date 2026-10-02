"""Reusable installed-plugin checks through the public host/runtime boundary.

Callers supply an authenticated HTTP client and a plugin-specific persistence
probe. No plugin implementation, host model or runtime internals are imported.
Only use destructive lifecycle checks against a disposable installation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx


class InstalledPluginConformance:
    """Exercise any installed plugin using the existing Plugin Manager API."""

    def __init__(self, client: httpx.Client, plugin_id: str) -> None:
        self.client = client
        self.plugin_id = plugin_id
        self.path = "/" + quote(plugin_id, safe="")

    def request(
        self, method: str, path: str, expected: int = 200, **kwargs: Any
    ) -> Any:
        response = self.client.request(method, "/api/plugins" + path, **kwargs)
        assert response.status_code == expected, (
            path,
            response.status_code,
            response.text[:4096],
        )
        return response.json() if response.content else None

    def current(self) -> dict[str, Any]:
        return next(
            item
            for item in self.request("GET", "")
            if item["plugin_id"] == self.plugin_id
        )

    def action(
        self, name: str, values: dict | None = None, expected: int = 200
    ) -> dict:
        return self.request(
            "POST",
            self.path + "/actions/" + quote(name, safe=""),
            expected,
            json={"values": values or {}, "confirmed": True},
        )

    def assert_ready(self) -> None:
        current = self.current()
        assert current["enabled"] and current["runtime_available"]
        assert current["status"] == "running" and current["health"] == "healthy"
        diagnostics = self.request("GET", self.path + "/logs")
        assert any(
            event["event"] == "lifecycle.ready" for event in diagnostics["events"]
        )
        health = self.request("GET", "/runtime/health")
        assert (
            health["api_version"] == "v1" and "v1" in health["supported_api_versions"]
        )

    def preserving_lifecycle(self, probe: Callable[[], Any]) -> None:
        """Check stop/start, disable/enable and ordinary reinstall against real data.

        The probe must return stable plugin-owned data/configuration/secret state,
        excluding timestamps and host-generated request IDs. It can use public
        actions or an administrator's independent read of disposable storage.
        """
        identity = self.current()["installation_id"]
        baseline = probe()
        self.assert_ready()
        self.request("POST", self.path + "/stop")
        stopped = self.current()
        assert stopped["enabled"] and stopped["status"] == "stopped"
        self.request("POST", self.path + "/start")
        self.assert_ready()
        assert probe() == baseline
        self.request("POST", self.path + "/disable")
        disabled = self.current()
        assert not disabled["enabled"] and disabled["status"] == "disabled"
        self.request("POST", self.path + "/enable")
        self.assert_ready()
        assert probe() == baseline
        self.request("POST", self.path + "/reinstall", json={})
        self.assert_ready()
        assert probe() == baseline
        assert self.current()["installation_id"] == identity
