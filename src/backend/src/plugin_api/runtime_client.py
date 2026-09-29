"""Authenticated HTTP transport from the application host to plugin-runtime."""

from __future__ import annotations

import os
from typing import Any

import httpx


class PluginRuntimeUnavailable(RuntimeError):
    """Raised when the isolated runtime cannot be reached."""


class PluginRuntimeClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("PLUGIN_RUNTIME_URL", "http://plugin-runtime:8000")).rstrip("/")
        self.token = token or os.getenv("PLUGIN_RUNTIME_TOKEN", "")
        if len(self.token) < 32:
            raise ValueError("PLUGIN_RUNTIME_TOKEN must contain at least 256 bits")

    def _headers(self) -> dict[str, str]:
        return {"X-Plugin-Runtime-Token": self.token}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(method, f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise PluginRuntimeUnavailable("plugin runtime is unavailable") from exc
        if response.status_code >= 400:
            detail = response.text[:1024]
            raise PluginRuntimeUnavailable(f"plugin runtime returned {response.status_code}: {detail}")
        if not response.content:
            return None
        return response.json()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def plugins(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/plugins")

    async def plugin_ui(self, plugin_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/plugins/{plugin_id}/ui")

    async def start(self, plugin_id: str) -> None:
        await self._request("POST", f"/plugins/{plugin_id}/start")

    async def stop(self, plugin_id: str) -> None:
        await self._request("POST", f"/plugins/{plugin_id}/stop")

    async def plugin_health(self, plugin_id: str) -> bool:
        data = await self._request("GET", f"/plugins/{plugin_id}/health")
        return bool(data.get("healthy"))

    async def save_settings(self, plugin_id: str, values: dict[str, Any]) -> None:
        await self._request("PUT", f"/plugins/{plugin_id}/settings", json=values)

    async def action(self, plugin_id: str, action_id: str, values: dict[str, Any]) -> None:
        await self._request(
            "POST",
            f"/plugins/{plugin_id}/actions/{action_id}",
            json={"values": values},
        )
