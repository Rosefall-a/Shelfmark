"""Authenticated HTTP transport from the application host to plugin-runtime."""

from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib.parse import quote

import httpx


class PluginRuntimeUnavailable(RuntimeError):
    """Raised when the isolated runtime cannot be reached."""


class PluginRuntimeRequestError(RuntimeError):
    """Raised when the runtime rejects a validly reached request."""


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
                    method,
                    f"{self.base_url}{path}",
                    headers={**self._headers(), **kwargs.pop("headers", {})},
                    **kwargs,
                )
        except httpx.HTTPError as exc:
            raise PluginRuntimeUnavailable("plugin runtime is unavailable") from exc
        if response.status_code >= 500:
            raise PluginRuntimeUnavailable(
                f"plugin runtime returned {response.status_code}: {response.text[:1024]}"
            )
        if response.status_code >= 400:
            raise PluginRuntimeRequestError(
                f"plugin runtime rejected the request ({response.status_code}): {response.text[:1024]}"
            )
        return response.json() if response.content else None

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def plugins(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/plugins")

    async def plugin_ui(self, plugin_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/plugins/{plugin_id}/ui")

    async def logs(self, plugin_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/plugins/{plugin_id}/logs")

    async def frontend_asset(self, plugin_id: str, path: str) -> bytes:
        data = await self._request("GET", f"/plugins/{plugin_id}/frontend/{path}")
        return base64.b64decode(str(data["content"]))

    async def native_frontend_asset(self, plugin_id: str, path: str) -> bytes:
        data = await self._request("GET", f"/plugins/{plugin_id}/native-frontend/{path}")
        return base64.b64decode(str(data["content"]))

    async def start(self, plugin_id: str, user_id: str | None = None) -> None:
        payload = {"user_id": user_id} if user_id is not None else None
        await self._request("POST", f"/plugins/{plugin_id}/start", json=payload)

    async def stop(self, plugin_id: str) -> None:
        await self._request("POST", f"/plugins/{plugin_id}/stop")

    async def delete(self, plugin_id: str) -> None:
        await self._request("DELETE", f"/plugins/{plugin_id}")

    async def save_secret(self, plugin_id: str, key: str, value: str) -> None:
        await self._request(
            "POST", f"/plugins/{plugin_id}/storage", json={"key": key, "value": value}
        )

    async def install_package(
        self,
        package: bytes,
        filename: str,
        *,
        installation_id: str,
        replace: bool = False,
        source_metadata: dict[str, Any] | None = None,
        trust_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            "/plugins/install",
            content=package,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Plugin-Package-Name": filename,
                "X-Plugin-Installation-ID": installation_id,
                "X-Plugin-Replace": "true" if replace else "false",
                "X-Plugin-Source": base64.urlsafe_b64encode(
                    json.dumps(source_metadata or {}, separators=(",", ":")).encode("utf-8")
                ).decode("ascii"),
                "X-Plugin-Trust": base64.urlsafe_b64encode(
                    json.dumps(trust_metadata or {}, separators=(",", ":")).encode("utf-8")
                ).decode("ascii"),
            },
        )

    async def plugin_health(self, plugin_id: str) -> bool:
        data = await self._request("GET", f"/plugins/{plugin_id}/health")
        return bool(data.get("healthy"))

    async def save_settings(self, plugin_id: str, values: dict[str, Any]) -> None:
        await self._request("PUT", f"/plugins/{plugin_id}/settings", json=values)

    async def action(
        self, plugin_id: str, action_id: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/plugins/{quote(plugin_id, safe='')}/actions/{quote(action_id, safe='')}",
            json={"values": values},
        )

    async def route(
        self,
        plugin_id: str,
        route_id: str,
        request: dict[str, Any],
        *,
        user_id: str,
    ) -> dict[str, Any]:
        """Execute one declared backend route as the authenticated request user."""

        result = await self._request(
            "POST",
            f"/plugins/{quote(plugin_id, safe='')}/routes/{quote(route_id, safe='')}",
            json={"request": request, "user_id": user_id},
        )
        if not isinstance(result, dict):
            raise PluginRuntimeRequestError("plugin backend route returned an invalid response")
        return result
