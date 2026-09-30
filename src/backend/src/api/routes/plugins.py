"""Application-facing Plugin Manager API backed by the isolated runtime."""

from __future__ import annotations

import logging
import mimetypes
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from urllib.parse import quote

from starlette.datastructures import UploadFile as StarletteUploadFile

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Request,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_admin, get_current_user
from src.database.models.plugin_notification_provider import (
    PluginNotificationProviderRegistration,
)
from src.database.models.plugin_permissions import PluginPermissionGrant, PluginPermissionRequest
from src.database.models.plugin_permission_audit import PluginPermissionAudit
from src.database.models.user import User
from src.database.session import get_db
from src.plugin_api.contracts import PluginUiDocument
from src.plugin_api.runtime_client import (
    PluginRuntimeClient,
    PluginRuntimeRequestError,
    PluginRuntimeUnavailable,
)
from src.plugin_api.publisher_trust import PublisherTrustError, load_trusted_publishers
from src.plugin_api.gateway import dispatch_gateway_request, runtime_token_is_valid
from src.plugin_api.grants import has_capability_grant
from src.plugin_api.updates import (
    PackageFormatError,
    PackageVerificationError,
    PluginPackageVerifier,
)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
logger = logging.getLogger(__name__)
_client = PluginRuntimeClient()


class PluginSettingsIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


_MAX_PLUGIN_PACKAGE_BYTES = 64 * 1024 * 1024
_PLUGIN_FRONTEND_CSP = (
    "default-src 'self'; script-src 'self' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; "
    "frame-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
)


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


async def _store_plugin_upload(file: StarletteUploadFile, prefix: str) -> tuple[Path, str, int]:
    filename = file.filename or ""
    if not filename.lower().endswith(".utp"):
        raise HTTPException(status_code=400, detail="Plugin packages must use the .utp extension.")
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".utp", delete=False) as handle:
        path = Path(handle.name)
        total = 0
        too_large = False
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > _MAX_PLUGIN_PACKAGE_BYTES:
                too_large = True
                break
            handle.write(chunk)
    if too_large:
        path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail="Plugin package exceeds the 64 MiB upload limit.",
        )
    return path, filename, total


def _inspect_install_candidate(path: Path) -> tuple[Any, str, str | None]:
    verifier = _plugin_package_verifier()
    try:
        return verifier.inspect(path, verify_signature=True), "trusted", None
    except PackageVerificationError as signature_error:
        try:
            candidate = verifier.inspect(path, verify_signature=False)
        except (PackageFormatError, PackageVerificationError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "package_verification_failed", "message": str(exc)},
            ) from signature_error
        return candidate, "untrusted", "Publisher signature could not be verified."
    except PackageFormatError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "package_format_invalid", "message": str(exc)},
        ) from exc


def _permission_key(name: str, version: int) -> str:
    return f"{name}:v{version}"


def _install_preview(verified: Any, trust_status: str, trust_warning: str | None) -> dict[str, Any]:
    manifest = verified.manifest
    return {
        "plugin_id": manifest.plugin_id,
        "name": manifest.name,
        "description": manifest.description,
        "version": manifest.version,
        "publisher": manifest.integrity.key_id,
        "digest": manifest.integrity.sha256,
        "trust_status": trust_status,
        "trust_warning": trust_warning,
        "sdk_version_range": manifest.sdk_version_range,
        "application_version_range": manifest.application_version_range,
        "dependencies": [
            {
                "plugin_id": dependency.plugin_id,
                "version_range": dependency.version_range,
                "optional": dependency.optional,
            }
            for dependency in manifest.dependencies
        ],
        "permissions": [
            {
                "key": _permission_key(
                    permission.capability.name.value,
                    permission.capability.version,
                ),
                "capability": permission.capability.name.value,
                "capability_version": permission.capability.version,
                "rationale": permission.rationale,
            }
            for permission in manifest.permissions
        ],
        "ui": {
            "pages": list(manifest.ui.pages),
            "menus": list(manifest.ui.menus),
            "has_custom_frontend": manifest.frontend is not None,
        },
    }


async def _resolve_plugin_upload(request: Request, file: UploadFile | None) -> StarletteUploadFile:
    """Resolve HTTP uploads while remaining compatible with direct route tests."""
    if isinstance(request, StarletteUploadFile):
        return request
    if isinstance(file, StarletteUploadFile):
        return file
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/"):
        form = await request.form()
        for value in form.values():
            if isinstance(value, StarletteUploadFile):
                return value
    raise HTTPException(status_code=400, detail={"code": "plugin_file_missing", "message": "Upload a .utp package as a multipart file."})


@router.post("/install/preview")
async def preview_plugin_install(
    request: Request,
    file: UploadFile | None = File(default=None),
    admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    """Statically inspect an upload for consent without installing or executing it."""
    del admin
    path: Path | None = None
    resolved_file: StarletteUploadFile | None = None
    try:
        resolved_file = await _resolve_plugin_upload(request, file)
        path, filename, total = await _store_plugin_upload(resolved_file, "plugin-preview-")
        verified, trust_status, trust_warning = _inspect_install_candidate(path)
        logger.info(
            "Plugin install preview validated: plugin_id=%s version=%s filename=%r bytes=%d trust=%s",
            verified.manifest.plugin_id,
            verified.manifest.version,
            filename,
            total,
            trust_status,
        )
        return _install_preview(verified, trust_status, trust_warning)
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        if resolved_file is not None:
            await resolved_file.close()


@router.post("/install", status_code=201)
async def install_plugin(
    file: UploadFile = File(...),
    allow_untrusted: bool = False,
    approved_permissions: list[str] | None = Query(default=None),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Commit a previewed package and the administrator's explicit permission decisions."""
    temporary_path: Path | None = None
    try:
        temporary_path, filename, total = await _store_plugin_upload(file, "plugin-upload-")
        verified, trust_status, trust_warning = _inspect_install_candidate(temporary_path)
        if trust_status == "untrusted" and not allow_untrusted:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "untrusted_plugin",
                    "message": "The plugin publisher is not trusted. Explicit untrusted consent is required.",
                    **_install_preview(verified, trust_status, trust_warning),
                },
            )

        package = temporary_path.read_bytes()
        installation_id = uuid4()
        declared_keys = {
            _permission_key(permission.capability.name.value, permission.capability.version)
            for permission in verified.manifest.permissions
        }
        approved_keys = set(approved_permissions if isinstance(approved_permissions, list) else ())
        if not approved_keys.issubset(declared_keys):
            raise HTTPException(
                status_code=400, detail="Consent contains an undeclared permission."
            )
        resolved_at = int(time.time())
        permission_requests: list[PluginPermissionRequest] = []
        permission_grants: list[PluginPermissionGrant] = []
        permission_audits: list[PluginPermissionAudit] = []
        for permission in verified.manifest.permissions:
            capability = permission.capability.name.value
            version = permission.capability.version
            approved = _permission_key(capability, version) in approved_keys
            permission_requests.append(
                PluginPermissionRequest(
                    plugin_id=verified.manifest.plugin_id,
                    installation_id=installation_id,
                    capability=capability,
                    capability_version=version,
                    rationale=permission.rationale,
                    status="approved" if approved else "denied",
                    resolved_at=resolved_at,
                    resolved_by=getattr(admin, "id", None),
                )
            )
            if approved:
                permission_grants.append(
                    PluginPermissionGrant(
                        plugin_id=verified.manifest.plugin_id,
                        installation_id=installation_id,
                        capability=capability,
                        capability_version=version,
                    )
                )
            permission_audits.append(
                PluginPermissionAudit(
                    plugin_id=verified.manifest.plugin_id,
                    installation_id=installation_id,
                    capability=capability,
                    capability_version=version,
                    user_id=getattr(admin, "id", None),
                    decision="allowed" if approved else "denied",
                    reason="administrator install consent",
                )
            )
        db.add_all([*permission_requests, *permission_grants, *permission_audits])
        try:
            result = await _client.install_package(
                package,
                filename,
                installation_id=str(installation_id),
            )
        except PluginRuntimeRequestError as exc:
            await db.rollback()
            raise _runtime_request_error(exc) from exc
        except PluginRuntimeUnavailable as exc:
            await db.rollback()
            raise _runtime_error(exc) from exc
        await db.commit()
        logger.info(
            "Plugin install committed: plugin_id=%s installation_id=%s bytes=%d granted=%d denied=%d trust=%s",
            verified.manifest.plugin_id,
            installation_id,
            total,
            len(permission_grants),
            len(permission_requests) - len(permission_grants),
            trust_status,
        )
        return {
            "plugin_id": verified.manifest.plugin_id,
            "version": verified.manifest.version,
            "name": verified.manifest.name,
            "publisher": verified.manifest.integrity.key_id,
            "installation_id": str(installation_id),
            "permissions_requested": len(permission_requests),
            "permissions_granted": len(permission_grants),
            "permissions_denied": len(permission_requests) - len(permission_grants),
            "trust_status": trust_status,
            "trust_warning": trust_warning,
            "status": result.get("status", "installed"),
        }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
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


@router.delete("/{plugin_id}", status_code=204)
async def delete_plugin(
    plugin_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> Response:
    del admin
    try:
        await _client.delete(quote(plugin_id, safe=""))
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    await db.execute(
        sql_update(PluginNotificationProviderRegistration)
        .where(
            PluginNotificationProviderRegistration.plugin_id == plugin_id,
            PluginNotificationProviderRegistration.revoked_at.is_(None),
        )
        .values(revoked_at=int(time.time()))
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/{plugin_id}/enable")
async def enable_plugin(
    plugin_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)
) -> dict:
    plugin = next(
        (item for item in await _client.plugins() if item.get("plugin_id") == plugin_id),
        None,
    )
    if plugin is None or not plugin.get("installation_id"):
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    installation_id = UUID(str(plugin["installation_id"]))
    pending = await db.scalar(
        select(PluginPermissionRequest.id).where(
            PluginPermissionRequest.plugin_id == plugin_id,
            PluginPermissionRequest.installation_id == installation_id,
            PluginPermissionRequest.status == "pending",
        )
    )
    if pending is not None:
        raise HTTPException(
            status_code=403,
            detail="Approve all pending plugin permissions before enabling this plugin.",
        )
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


@router.put("/{plugin_id}/update", status_code=200)
async def update_plugin(
    plugin_id: str,
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del admin
    temporary_path: str | None = None
    try:
        filename = file.filename or ""
        if not filename.lower().endswith(".utp"):
            raise HTTPException(
                status_code=400, detail="Plugin packages must use the .utp extension."
            )
        with tempfile.NamedTemporaryFile(
            prefix="plugin-update-", suffix=".utp", delete=False
        ) as handle:
            temporary_path = handle.name
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_PLUGIN_PACKAGE_BYTES:
                    raise HTTPException(
                        status_code=413, detail="Plugin package exceeds the 64 MiB upload limit."
                    )
                handle.write(chunk)
        try:
            verified = _plugin_package_verifier().inspect(Path(temporary_path))
        except (PackageFormatError, PackageVerificationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if verified.manifest.plugin_id != plugin_id:
            raise HTTPException(
                status_code=400,
                detail="Updated package plugin ID does not match the installed plugin.",
            )
        installed = next(
            (item for item in await _client.plugins() if item.get("plugin_id") == plugin_id),
            None,
        )
        if installed is None or not installed.get("installation_id"):
            raise HTTPException(status_code=409, detail="Plugin installation identity is missing.")
        installation_id = UUID(str(installed["installation_id"]))
        active_grants = set(
            await db.scalars(
                select(PluginPermissionGrant.capability).where(
                    PluginPermissionGrant.plugin_id == plugin_id,
                    PluginPermissionGrant.installation_id == installation_id,
                    PluginPermissionGrant.revoked_at.is_(None),
                )
            )
        )
        permission_requests = [
            PluginPermissionRequest(
                plugin_id=plugin_id,
                installation_id=installation_id,
                capability=permission.capability.name.value,
                capability_version=permission.capability.version,
                rationale=permission.rationale,
                status="pending",
            )
            for permission in verified.manifest.permissions
            if permission.capability.name.value not in active_grants
        ]
        db.add_all(permission_requests)
        try:
            result = await _client.install_package(
                Path(temporary_path).read_bytes(),
                filename,
                installation_id=str(installation_id),
                replace=True,
            )
        except PluginRuntimeRequestError as exc:
            await db.rollback()
            raise _runtime_request_error(exc) from exc
        except PluginRuntimeUnavailable as exc:
            await db.rollback()
            raise _runtime_error(exc) from exc
        await db.commit()
        return {
            "plugin_id": plugin_id,
            "version": verified.manifest.version,
            "permissions_requested": len(permission_requests),
            "status": result.get("status", "updated"),
        }
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
        await file.close()


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
    await db.execute(
        sql_update(PluginNotificationProviderRegistration)
        .where(
            PluginNotificationProviderRegistration.plugin_id == plugin_id,
            PluginNotificationProviderRegistration.revoked_at.is_(None),
        )
        .values(revoked_at=int(time.time()))
    )
    await db.commit()
    return {"plugin_id": plugin_id, "status": "revoked", "count": count}


@router.get("/{plugin_id}/logs")
async def plugin_logs(
    plugin_id: str,
    level: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    del admin
    if level is not None and level not in {"debug", "info", "warning", "error"}:
        raise HTTPException(status_code=400, detail="Unknown diagnostic level.")
    try:
        diagnostics = await _client.logs(quote(plugin_id, safe=""))
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    events = diagnostics.get("events", [])
    if not isinstance(events, list):
        events = []
    events = [event for event in events if isinstance(event, dict)]
    if level is not None:
        events = [event for event in events if event.get("level") == level]
    diagnostics["events"] = events[-limit:]
    return diagnostics


@router.get("/{plugin_id}/frontend/{asset_path:path}")
async def plugin_frontend(
    plugin_id: str,
    asset_path: str,
    user: User = Depends(get_current_user),
) -> Response:
    del user
    if not asset_path or ".." in Path(asset_path).parts:
        raise HTTPException(status_code=404, detail="Plugin frontend asset not found.")
    try:
        content = await _client.frontend_asset(quote(plugin_id, safe=""), asset_path)
    except PluginRuntimeRequestError as exc:
        raise HTTPException(status_code=404, detail="Plugin frontend asset not found.") from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    media_type = mimetypes.guess_type(asset_path)[0] or "application/octet-stream"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Security-Policy": _PLUGIN_FRONTEND_CSP,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{plugin_id}/ui")
async def plugin_ui(plugin_id: str, user: User = Depends(get_current_user)) -> dict:
    del user
    try:
        payload = await _client.plugin_ui(quote(plugin_id, safe=""))
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    try:
        document = PluginUiDocument.model_validate(payload)
    except ValidationError as exc:
        logger.warning("Rejected invalid plugin UI document: plugin_id=%s", plugin_id)
        raise HTTPException(status_code=422, detail="Plugin UI document is invalid.") from exc
    return document.model_dump(mode="json")


@router.put("/{plugin_id}/secrets/{key}")
async def save_plugin_secret(
    plugin_id: str,
    key: str,
    payload: dict[str, str] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not key or len(key) > 128 or "/" in key or ".." in key:
        raise HTTPException(status_code=400, detail="Invalid plugin secret key.")
    plugin = next(
        (item for item in await _client.plugins() if item.get("plugin_id") == plugin_id),
        None,
    )
    if plugin is None or not plugin.get("installation_id"):
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    if not await has_capability_grant(
        db,
        plugin_id=plugin_id,
        installation_id=UUID(str(plugin["installation_id"])),
        capability="plugin.storage",
        user_id=user.id,
    ):
        raise HTTPException(
            status_code=403, detail="Permission plugin.storage has not been granted."
        )
    value = payload.get("value")
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=400, detail="Secret value must be a non-empty string.")
    try:
        await _client.save_secret(quote(plugin_id, safe=""), f"secrets/{key}", value)
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    logger.info(
        "Plugin secret updated: plugin_id=%s installation_id=%s key=%s user_id=%s",
        plugin_id,
        plugin["installation_id"],
        key,
        user.id,
    )
    return {"plugin_id": plugin_id, "key": key, "saved": True}


@router.put("/{plugin_id}/settings")
async def save_plugin_settings(
    plugin_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    plugin = next(
        (item for item in await _client.plugins() if item.get("plugin_id") == plugin_id),
        None,
    )
    if plugin is None or not plugin.get("installation_id"):
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    if not await has_capability_grant(
        db,
        plugin_id=plugin_id,
        installation_id=UUID(str(plugin["installation_id"])),
        capability="plugin.settings",
        user_id=user.id,
    ):
        raise HTTPException(
            status_code=403, detail="Permission plugin.settings has not been granted."
        )
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
    request_id = uuid4()
    document = await _client.plugin_ui(quote(plugin_id, safe=""))
    action = next(
        (item for item in document.get("actions", []) if item.get("id") == action_id), None
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Plugin action not found.")
    plugin = next(
        (item for item in await _client.plugins() if item.get("plugin_id") == plugin_id), None
    )
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")
    if not plugin.get("installation_id"):
        raise HTTPException(status_code=409, detail="Plugin installation identity is missing.")
    if not plugin.get("enabled"):
        raise HTTPException(status_code=409, detail="Enable the plugin before running actions.")
    installation_id = UUID(str(plugin.get("installation_id")))
    capability = (action.get("capability") or {}).get("name")
    if capability:
        if not await has_capability_grant(
            db,
            plugin_id=plugin_id,
            installation_id=installation_id,
            capability=capability,
            user_id=user.id,
        ):
            raise HTTPException(
                status_code=403, detail=f"Permission {capability} has not been granted."
            )
    values = dict(payload.values)
    values.setdefault("_plugin_context", {"path": f"/plugins/{plugin_id}", "user_id": str(user.id)})
    try:
        result = await _client.action(quote(plugin_id, safe=""), quote(action_id, safe=""), values)
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    logger.info(
        "Plugin action completed: request_id=%s plugin_id=%s installation_id=%s action_id=%s user_id=%s",
        request_id,
        plugin_id,
        installation_id,
        action_id,
        user.id,
    )
    return {
        **(result or {"completed": True}),
        "plugin_id": plugin_id,
        "action": action_id,
        "request_id": str(request_id),
    }


class PluginGatewayIn(BaseModel):
    plugin_id: str
    installation_id: UUID
    request_id: UUID
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
    logger.info(
        "Plugin gateway dispatch: request_id=%s plugin_id=%s installation_id=%s method=%s capability=%s user_id=%s",
        payload.request_id,
        payload.plugin_id,
        payload.installation_id,
        payload.method,
        payload.capability,
        payload.user_id,
    )
    try:
        result = await dispatch_gateway_request(
            db,
            plugin_id=payload.plugin_id,
            user_id=payload.user_id,
            installation_id=payload.installation_id,
            method=payload.method,
            capability=payload.capability,
            payload=payload.payload,
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
