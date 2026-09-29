"""Application-facing Plugin Manager API backed by the isolated runtime."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_admin, get_current_user
from src.database.models.plugin_permissions import PluginPermissionGrant, PluginPermissionRequest
from src.database.models.user import User
from src.database.session import get_db
from src.plugin_api.runtime_client import PluginRuntimeClient, PluginRuntimeRequestError, PluginRuntimeUnavailable
from src.plugin_api.publisher_trust import PublisherTrustError, load_trusted_publishers
from src.plugin_api.gateway import dispatch_gateway_request, runtime_token_is_valid
from src.plugin_api.updates import PackageFormatError, PackageVerificationError, PluginPackageVerifier

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
_client = PluginRuntimeClient()


class PluginSettingsIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


_MAX_PLUGIN_PACKAGE_BYTES = 64 * 1024 * 1024
def _plugin_package_verifier() -> PluginPackageVerifier:
    configured_path = os.getenv("PLUGIN_TRUSTED_PUBLISHER_REGISTRY")
    try:
        publishers = load_trusted_publishers(Path(configured_path) if configured_path else None)
    except PublisherTrustError as exc:
        raise RuntimeError("PLUGIN_TRUSTED_PUBLISHER_REGISTRY is invalid") from exc
    return PluginPackageVerifier(publishers=publishers, require_signature=False)


def _runtime_error(exc: PluginRuntimeUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


def _runtime_request_error(exc: PluginRuntimeRequestError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.post("/install", status_code=201)
async def install_plugin(
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Verify a .utp package, request declared permissions, then transfer it to the isolated runtime."""
    temporary_path: str | None = None
    try:
        filename = file.filename or ""
        if not filename.lower().endswith(".utp"):
            raise HTTPException(status_code=400, detail="Plugin packages must use the .utp extension.")
        with tempfile.NamedTemporaryFile(prefix="plugin-upload-", suffix=".utp", delete=False) as handle:
            temporary_path = handle.name
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_PLUGIN_PACKAGE_BYTES:
                    raise HTTPException(status_code=413, detail="Plugin package exceeds the 64 MiB upload limit.")
                handle.write(chunk)

        try:
            verified = _plugin_package_verifier().inspect(Path(temporary_path))
        except (PackageFormatError, PackageVerificationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        package = Path(temporary_path).read_bytes()
        installation_id = uuid4()
        permission_requests = [
            PluginPermissionRequest(
                plugin_id=verified.manifest.plugin_id,
                installation_id=installation_id,
                capability=permission.capability.name.value,
                capability_version=permission.capability.version,
                rationale=permission.rationale,
                status="pending",
            )
            for permission in verified.manifest.permissions
        ]
        db.add_all(permission_requests)
        try:
            result = await _client.install_package(package, filename)
        except PluginRuntimeRequestError as exc:
            await db.rollback()
            raise _runtime_request_error(exc) from exc
        except PluginRuntimeUnavailable as exc:
            await db.rollback()
            raise _runtime_error(exc) from exc
        await db.commit()
        if not permission_requests:
            try:
                await _client.start(verified.manifest.plugin_id, user_id=str(admin.id))
            except PluginRuntimeUnavailable as exc:
                raise _runtime_error(exc) from exc
        trust_status = "trusted"
        trust_warning = None
        if verified.manifest.integrity.signature is None:
            trust_status = "untrusted"
            trust_warning = "Untrusted signing key: this plugin is unsigned."
        return {
            "plugin_id": verified.manifest.plugin_id,
            "version": verified.manifest.version,
            "name": verified.manifest.name,
            "publisher": verified.manifest.integrity.key_id,
            "installation_id": str(installation_id),
            "permissions_requested": len(permission_requests),
            "trust_status": trust_status,
            "trust_warning": trust_warning,
            "status": result.get("status", "installed"),
        }
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
        await file.close()


@router.get("", response_model=list[dict])
async def list_plugins(user: User = Depends(get_current_user)) -> list[dict]:
    del user
    try:
        return sorted(await _client.plugins(), key=lambda value: value["plugin_id"])
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc


@router.post("/{plugin_id}/enable")
async def enable_plugin(plugin_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)) -> dict:
    del admin
    pending = await db.scalar(select(PluginPermissionRequest.id).where(PluginPermissionRequest.plugin_id == plugin_id, PluginPermissionRequest.status == "pending"))
    if pending is not None:
        raise HTTPException(status_code=403, detail="Approve all pending plugin permissions before enabling this plugin.")
    try:
        await _client.start(quote(plugin_id, safe=""), user_id=str(admin.id))
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    return {"plugin_id": plugin_id, "enabled": True}


@router.post("/{plugin_id}/disable")
async def disable_plugin(plugin_id: str, admin: User = Depends(get_current_admin)) -> dict:
    del admin
    try:
        await _client.stop(quote(plugin_id, safe=""))
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    return {"plugin_id": plugin_id, "enabled": False}


@router.post("/{plugin_id}/retry")
async def retry_plugin(plugin_id: str, admin: User = Depends(get_current_admin)) -> dict:
    del admin
    encoded = quote(plugin_id, safe="")
    try:
        await _client.stop(encoded)
    except PluginRuntimeUnavailable:
        pass
    try:
        await _client.start(encoded)
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    return {"plugin_id": plugin_id, "status": "running"}


@router.post("/{plugin_id}/permissions/revoke")
async def revoke_plugin_permissions(
    plugin_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict:
    del admin
    rows = await db.scalars(
        select(PluginPermissionGrant).where(
            PluginPermissionGrant.plugin_id == plugin_id,
            PluginPermissionGrant.revoked_at.is_(None),
        )
    )
    count = 0
    for row in rows:
        row.revoked_at = int(time.time())
        count += 1
    await db.commit()
    return {"plugin_id": plugin_id, "status": "revoked", "count": count}


@router.get("/{plugin_id}/logs")
async def plugin_logs(plugin_id: str, user: User = Depends(get_current_user)) -> dict[str, Any]:
    del user
    try:
        return await _client.logs(quote(plugin_id, safe=""))
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc


@router.get("/{plugin_id}/ui")
async def plugin_ui(plugin_id: str, user: User = Depends(get_current_user)) -> dict:
    del user
    try:
        return await _client.plugin_ui(quote(plugin_id, safe=""))
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc


@router.put("/{plugin_id}/settings")
async def save_plugin_settings(
    plugin_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    user: User = Depends(get_current_user),
) -> dict:
    del user
    try:
        await _client.save_settings(quote(plugin_id, safe=""), payload)
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    return {"plugin_id": plugin_id, "saved": True}


@router.post("/{plugin_id}/actions/{action_id}")
async def plugin_action(
    plugin_id: str,
    action_id: str,
    payload: PluginSettingsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    document = await _client.plugin_ui(quote(plugin_id, safe=""))
    action = next((item for item in document.get("actions", []) if item.get("id") == action_id), None)
    if action is None:
        raise HTTPException(status_code=404, detail="Plugin action not found.")
    plugin = next((item for item in await _client.plugins() if item.get("plugin_id") == plugin_id), None)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")
    if not plugin.get("enabled"):
        raise HTTPException(status_code=409, detail="Enable the plugin before running actions.")
    capability = (action.get("capability") or {}).get("name")
    if capability:
        grant = await db.scalar(select(PluginPermissionGrant.id).where(PluginPermissionGrant.plugin_id == plugin_id, PluginPermissionGrant.capability == capability, PluginPermissionGrant.revoked_at.is_(None)))
        if grant is None:
            raise HTTPException(status_code=403, detail=f"Permission {capability} has not been granted.")
    values = dict(payload.values)
    values.setdefault("_plugin_context", {"path": f"/plugins/{plugin_id}", "user_id": str(user.id)})
    try:
        result = await _client.action(quote(plugin_id, safe=""), quote(action_id, safe=""), values)
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    return {"plugin_id": plugin_id, "action": action_id, **(result or {"completed": True})}


class PluginGatewayIn(BaseModel):
    plugin_id: str
    user_id: UUID
    method: str
    capability: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/runtime/gateway")
async def plugin_gateway(
    payload: PluginGatewayIn,
    db: AsyncSession = Depends(get_db),
    runtime_token: str | None = Header(default=None, alias="X-Plugin-Runtime-Token"),
) -> dict[str, Any]:
    if not runtime_token_is_valid(runtime_token):
        raise HTTPException(status_code=503, detail="Plugin runtime gateway is not configured.")
    try:
        result = await dispatch_gateway_request(
            db, plugin_id=payload.plugin_id, user_id=payload.user_id,
            method=payload.method, capability=payload.capability, payload=payload.payload,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"payload": result}

@router.get("/runtime/health")
async def runtime_health(admin: User = Depends(get_current_admin)) -> dict:
    del admin
    try:
        return await _client.health()
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
