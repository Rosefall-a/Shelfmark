"""Authenticated HTTP transport from the application host to plugin-runtime."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx


class PluginRuntimeUnavailable(RuntimeError):
    """Raised when the isolated runtime cannot be reached."""


class PluginRuntimeClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        resolved_url = base_url or os.getenv("PLUGIN_RUNTIME_URL") or "http://plugin-runtime:8000"
        resolved_token = token or os.getenv("PLUGIN_RUNTIME_TOKEN") or ""
        self.base_url = resolved_url.rstrip("/")
        self.token = resolved_token

    def _headers(self) -> dict[str, str]:
        if len(self.token) < 32:
            raise PluginRuntimeUnavailable("plugin runtime credentials are not configured")
        return {"X-Plugin-Runtime-Token": self.token}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers=self._headers(), **kwargs
                )
        except httpx.HTTPError as exc:
            raise PluginRuntimeUnavailable("plugin runtime is unavailable") from exc
        if response.status_code >= 400:
            raise PluginRuntimeUnavailable(
                f"plugin runtime returned {response.status_code}: {response.text[:1024]}"
            )
        return response.json() if response.content else None

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

    async def install_package(self, package: bytes, filename: str) -> dict[str, Any]:
        return await self._request(
            "PUT",
            "/plugins/install",
            content=package,
            headers={"Content-Type": "application/octet-stream", "X-Plugin-Package-Name": filename},
        )

    async def plugin_health(self, plugin_id: str) -> bool:
        data = await self._request("GET", f"/plugins/{plugin_id}/health")
        return bool(data.get("healthy"))

    async def save_settings(self, plugin_id: str, values: dict[str, Any]) -> None:
        await self._request("PUT", f"/plugins/{plugin_id}/settings", json=values)

    async def action(self, plugin_id: str, action_id: str, values: dict[str, Any]) -> None:
        await self._request(
            "POST", f"/plugins/{quote(plugin_id, safe='')}/actions/{quote(action_id, safe='')}",
            json={"values": values},
        )
