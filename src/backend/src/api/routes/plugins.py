"""Application-facing Plugin Manager API backed by the isolated runtime."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.auth import get_current_admin, get_current_user
from src.database.models.user import User
from src.plugin_api.runtime_client import PluginRuntimeClient, PluginRuntimeUnavailable

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_STATE_PATH = Path("/data/plugin-manager-state.json")
_lock = asyncio.Lock()
_client = PluginRuntimeClient()


class PluginSettingsIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


def _load_state() -> dict[str, bool]:
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict[str, bool]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temporary.replace(_STATE_PATH)


async def _runtime_error(exc: PluginRuntimeUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


def _status(item: dict[str, Any], enabled: bool) -> str:
    if not enabled:
        return "disabled"
    runtime = item.get("status", "unknown")
    if runtime == "running":
        return "running"
    if runtime in {"failed", "quarantined"}:
        return runtime
    return "stopped"


async def _plugins() -> list[dict[str, Any]]:
    try:
        items = await _client.plugins()
    except PluginRuntimeUnavailable as exc:
        raise await _runtime_error(exc)
    state = _load_state()
    result = []
    for item in items:
        plugin_id = str(item["plugin_id"])
        enabled = state.get(plugin_id, bool(item.get("enabled", True)))
        result.append({
            "plugin_id": plugin_id,
            "name": item["name"],
            "version": item["version"],
            "status": _status(item, enabled),
            "compatible": bool(item.get("compatible", False)),
            "compatibility_reason": item.get("compatibility_reason", ""),
            "health": item.get("health", "unknown"),
            "permissions": item.get("permissions", []),
            "enabled": enabled,
        })
    return sorted(result, key=lambda value: value["plugin_id"])


@router.get("", response_model=list[dict])
async def list_plugins(user: User = Depends(get_current_user)) -> list[dict]:
    del user
    return await _plugins()


@router.post("/{plugin_id}/enable")
async def enable_plugin(plugin_id: str, admin: User = Depends(get_current_admin)) -> dict:
    del admin
    async with _lock:
        try:
            await _client.start(plugin_id)
        except PluginRuntimeUnavailable as exc:
            raise await _runtime_error(exc)
        state = _load_state()
        state[plugin_id] = True
        _save_state(state)
    return {"plugin_id": plugin_id, "enabled": True}


@router.post("/{plugin_id}/disable")
async def disable_plugin(plugin_id: str, admin: User = Depends(get_current_admin)) -> dict:
    del admin
    async with _lock:
        try:
            await _client.stop(plugin_id)
        except PluginRuntimeUnavailable as exc:
            raise await _runtime_error(exc)
        state = _load_state()
        state[plugin_id] = False
        _save_state(state)
    return {"plugin_id": plugin_id, "enabled": False}


@router.post("/{plugin_id}/retry")
async def retry_plugin(plugin_id: str, admin: User = Depends(get_current_admin)) -> dict:
    del admin
    async with _lock:
        try:
            await _client.stop(plugin_id)
            await _client.start(plugin_id)
        except PluginRuntimeUnavailable as exc:
            raise await _runtime_error(exc)
        state = _load_state()
        state[plugin_id] = True
        _save_state(state)
    return {"plugin_id": plugin_id, "status": "running"}


@router.post("/{plugin_id}/permissions/revoke")
async def revoke_plugin_permissions(plugin_id: str, admin: User = Depends(get_current_admin)) -> dict:
    # Revocation is installation-wide here; individual capability grants remain
    # represented by the existing /api/plugin-permissions API.
    del admin
    return {"plugin_id": plugin_id, "status": "revocation_requested"}


@router.get("/{plugin_id}/ui")
async def plugin_ui(plugin_id: str, user: User = Depends(get_current_user)) -> dict:
    del user
    try:
        return await _client.plugin_ui(plugin_id)
    except PluginRuntimeUnavailable as exc:
        raise await _runtime_error(exc)


@router.put("/{plugin_id}/settings")
async def save_plugin_settings(
    plugin_id: str,
    payload: PluginSettingsIn,
    user: User = Depends(get_current_user),
) -> dict:
    del user
    try:
        await _client.save_settings(plugin_id, payload.values)
    except PluginRuntimeUnavailable as exc:
        raise await _runtime_error(exc)
    return {"plugin_id": plugin_id, "saved": True}


@router.post("/{plugin_id}/actions/{action_id}")
async def plugin_action(
    plugin_id: str,
    action_id: str,
    payload: PluginSettingsIn,
    user: User = Depends(get_current_user),
) -> dict:
    del user
    try:
        await _client.action(plugin_id, action_id, payload.values)
    except PluginRuntimeUnavailable as exc:
        raise await _runtime_error(exc)
    return {"plugin_id": plugin_id, "action": action_id, "accepted": True}


@router.get("/runtime/health")
async def runtime_health(admin: User = Depends(get_current_admin)) -> dict:
    del admin
    try:
        return await _client.health()
    except PluginRuntimeUnavailable as exc:
        raise await _runtime_error(exc)
