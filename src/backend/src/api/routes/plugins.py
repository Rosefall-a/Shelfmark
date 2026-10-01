"""Application-facing Plugin Manager API backed by the isolated runtime."""

from __future__ import annotations

import ipaddress
import json
import logging
import mimetypes
import os
import socket
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.responses import JSONResponse

from src.core.auth import get_current_admin, get_current_user, verify_password
from src.database.models.notification import Notification
from src.database.models.plugin_notification_provider import (
    PluginNotificationProviderRegistration,
)
from src.database.models.plugin_permission_audit import PluginPermissionAudit
from src.database.models.plugin_permissions import PluginPermissionGrant, PluginPermissionRequest
from src.database.models.user import User
from src.database.session import get_db
from src.plugin_api.backend_routes import (
    BackendRouteConflictError,
    ResolvedBackendRoute,
    resolve_backend_route,
    validate_host_route_ownership,
)
from src.plugin_api.capabilities import (
    calculate_permission_delta,
    capability_children,
    capability_definition,
    expand_capabilities,
    package_identity_can_retain_grants,
)
from src.plugin_api.catalogues import CatalogueStore, CatalogueStoreError
from src.plugin_api.contracts import (
    BackendRouteAuthorization,
    BackendRouteScope,
    Capability,
    CapabilityRef,
    PluginDependency,
    PluginPackageIdentity,
    PluginUiDocument,
    parse_semver,
)
from src.plugin_api.gateway import dispatch_gateway_request, runtime_token_is_valid
from src.plugin_api.grants import has_capability_grant, installation_is_executable
from src.plugin_api.installer import (
    DependencyPlan,
    InspectedPackage,
    PackageTrustStatus,
    inspect_package,
    plan_dependencies,
)
from src.plugin_api.publisher_trust import PublisherTrustError, load_trusted_publishers
from src.plugin_api.runtime_client import (
    PluginRuntimeClient,
    PluginRuntimeRequestError,
    PluginRuntimeUnavailable,
)
from src.plugin_api.updates import (
    PackageFormatError,
    PackageVerificationError,
    PluginPackageVerifier,
)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
host_router = APIRouter(tags=["plugin-host-routes"])
logger = logging.getLogger(__name__)
_client = PluginRuntimeClient()
_MAX_PLUGIN_ROUTE_BODY_BYTES = 48 * 1024
_MAX_PLUGIN_ROUTE_ENVELOPE_BYTES = 64 * 1024


class PluginSettingsIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class PluginActionContext(BaseModel):
    """Host context accepted from a contribution mount, never arbitrary plugin data."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^(game|media|documents)$")
    resource_id: str = Field(min_length=1, max_length=128)
    resource_type: str | None = Field(default=None, min_length=1, max_length=64)


class PluginActionIn(PluginSettingsIn):
    context: PluginActionContext | None = None


class PluginInstallUrl(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    expected_digest: str | None = Field(default=None, min_length=64, max_length=64)
    source_type: str = Field(default="url", pattern=r"^(url|catalogue)$")
    catalogue_url: str | None = Field(default=None, max_length=2048)
    release_notes: str | None = Field(default=None, max_length=4_000)
    changelog_url: str | None = Field(default=None, max_length=2048)
    admin_password: str | None = Field(default=None, min_length=1, max_length=1024)
    confirm_dangerous: bool = False


class PluginCatalogEntry(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2_000)
    version: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2048)
    release_notes: str | None = Field(default=None, max_length=4_000)
    changelog_url: str | None = Field(default=None, max_length=2048)
    dependencies: tuple[PluginDependency, ...] = ()


class PluginBackendRouteResponse(BaseModel):
    """Bounded JSON response returned by an isolated backend route handler."""

    model_config = ConfigDict(extra="forbid")

    status_code: int = Field(default=200, ge=200, le=599)
    body: Any = None


class PluginCatalogueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True
    priority: int = Field(default=100, ge=1, le=10_000)


class PluginCatalogueUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)


_MAX_PLUGIN_PACKAGE_BYTES = 64 * 1024 * 1024
_PLUGIN_CATALOG_URL = os.getenv(
    "PLUGIN_CATALOG_URL",
    "https://raw.githubusercontent.com/Rosefall-a/unnamed_tracking_app_plugins/main/list.json",
)
_REMOTE_FETCH_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
_MAX_REMOTE_REDIRECTS = 3

_PLUGIN_FRONTEND_CSP = (
    "default-src 'self'; script-src 'self' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; "
    "frame-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
)


@lru_cache(maxsize=8)
def _catalogue_store_for(path: str, official_url: str) -> CatalogueStore:
    return CatalogueStore(Path(path), official_url)


def _catalogue_store() -> CatalogueStore:
    configured_path = os.getenv("PLUGIN_CATALOGUE_REGISTRY", "/data/plugin-catalogues.json")
    return _catalogue_store_for(configured_path, _PLUGIN_CATALOG_URL)


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
    filename = file.filename or "plugin-package"
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


def _validate_remote_url(raw_url: str) -> str:
    """Allow only public HTTP(S) destinations and standard web ports."""
    try:
        parsed = urlparse(raw_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid plugin download URL.") from exc
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise HTTPException(
            status_code=400,
            detail="Plugin download URLs must use HTTP(S) without embedded credentials.",
        )
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Plugin download URL has no hostname.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Plugin download URL has an invalid port."
        ) from exc
    if port is not None and port not in {80, 443}:
        raise HTTPException(
            status_code=400, detail="Plugin download URLs may only use ports 80 and 443."
        )
    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(
                hostname, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
            )
        }
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail="Plugin download hostname could not be resolved."
        ) from exc
    if not addresses or not all(address.is_global for address in addresses):
        raise HTTPException(
            status_code=400,
            detail="Plugin download URL must resolve only to public internet addresses.",
        )
    return parsed.geturl()


async def _download_remote_file(
    raw_url: str, *, json_document: bool = False
) -> tuple[Path, str, int]:
    """Download a bounded public resource without following unvalidated redirects."""
    url = _validate_remote_url(raw_url)
    for _ in range(_MAX_REMOTE_REDIRECTS + 1):
        async with httpx.AsyncClient(
            timeout=_REMOTE_FETCH_TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": "UnnamedTrackingApp-PluginManager/1"},
        ) as client:
            try:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(
                                status_code=502,
                                detail="Plugin download redirect has no destination.",
                            )
                        url = _validate_remote_url(urljoin(url, location))
                        continue
                    if response.status_code != 200:
                        raise HTTPException(
                            status_code=502,
                            detail=(f"Plugin download returned HTTP {response.status_code}."),
                        )
                    max_bytes = 1 * 1024 * 1024 if json_document else _MAX_PLUGIN_PACKAGE_BYTES
                    suffix = ".json" if json_document else ".utp"
                    filename = Path(urlparse(url).path).name or f"plugin-download{suffix}"
                    if not json_document and Path(filename).suffix.lower() not in {
                        ".utp",
                        ".zip",
                    }:
                        filename = f"{filename}.utp"
                    with tempfile.NamedTemporaryFile(
                        prefix="plugin-remote-",
                        suffix=suffix,
                        delete=False,
                    ) as handle:
                        path = Path(handle.name)
                        total = 0
                        too_large = False
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > max_bytes:
                                too_large = True
                                break
                            handle.write(chunk)
                    if too_large:
                        path.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail="Remote plugin resource exceeds the allowed size.",
                        )
                    return path, filename, total
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail="Plugin download failed.") from exc
    raise HTTPException(status_code=502, detail="Plugin download followed too many redirects.")


def _catalog_entries(payload: Any) -> list[dict[str, Any]]:
    """Validate the small, host-consumed catalogue contract."""
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or not isinstance(payload.get("plugins"), list)
    ):
        raise HTTPException(status_code=502, detail="Plugin catalogue is invalid.")
    entries: list[dict[str, Any]] = []
    for raw_entry in payload["plugins"]:
        try:
            entry = PluginCatalogEntry.model_validate(raw_entry)
            parse_semver(entry.version)
            _validate_remote_url(entry.url)
            if entry.changelog_url:
                _validate_remote_url(entry.changelog_url)
        except (ValidationError, ValueError, HTTPException) as exc:
            raise HTTPException(
                status_code=502, detail="Plugin catalogue contains an invalid entry."
            ) from exc
        entries.append(entry.model_dump())
    return entries


def _inspect_install_candidate(path: Path) -> InspectedPackage:
    verifier = _plugin_package_verifier()
    try:
        return inspect_package(path, verifier)
    except (PackageFormatError, PackageVerificationError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_package",
                "trust_status": "invalid_package",
                "message": str(exc),
            },
        ) from exc


def _permission_key(name: str, version: int) -> str:
    return f"{name}:v{version}"


def _permission_preview(permission: Any) -> dict[str, Any]:
    definition = capability_definition(permission.capability.name)
    return {
        "key": _permission_key(
            permission.capability.name.value,
            permission.capability.version,
        ),
        "capability": permission.capability.name.value,
        "capability_version": permission.capability.version,
        "rationale": permission.rationale,
        "title": definition.title,
        "category": definition.category,
        "parent": definition.parent.value if definition.parent else None,
        "children": [child.value for child in capability_children(permission.capability.name)],
        "risk": definition.risk.value,
        "highly_privileged": definition.highly_privileged,
    }


def _install_preview(
    inspected: InspectedPackage,
    dependency_plan: DependencyPlan | None = None,
    *,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = inspected.package.manifest
    trust = inspected.trust
    dependency_items = (
        [
            {
                "plugin_id": item.plugin_id,
                "version_range": item.version_range,
                "optional": item.optional,
                "state": item.state.value,
                "installed_version": item.installed_version,
                "available_version": item.available_version,
                "source_url": item.source_url,
            }
            for item in dependency_plan.items
        ]
        if dependency_plan is not None
        else [
            {
                "plugin_id": dependency.plugin_id,
                "version_range": dependency.version_range,
                "optional": dependency.optional,
                "state": "unresolved",
                "installed_version": None,
                "available_version": None,
                "source_url": None,
            }
            for dependency in manifest.dependencies
        ]
    )
    return {
        "plugin_id": manifest.plugin_id,
        "name": manifest.name,
        "description": manifest.description,
        "version": manifest.version,
        "publisher": trust.publisher_identity,
        "publisher_key_id": trust.publisher_key_id,
        "digest": manifest.integrity.sha256,
        "trust_status": trust.status.value,
        "trust_warning": trust.warning,
        "signature_present": trust.signature_present,
        "signature_verified": trust.signature_verified,
        "installable": trust.installable,
        "sdk_version_range": manifest.sdk_version_range,
        "application_version_range": manifest.application_version_range,
        "dependencies": dependency_items,
        "dependency_ready": dependency_plan.ready
        if dependency_plan is not None
        else not dependency_items,
        "dependency_order": list(dependency_plan.installation_order) if dependency_plan else [],
        "dependency_conflicts": list(dependency_plan.conflicts) if dependency_plan else [],
        "permissions": [_permission_preview(permission) for permission in manifest.permissions],
        "requires_elevated_reauthentication": (
            not trust.is_verified
            and any(
                capability_definition(permission.capability.name).highly_privileged
                for permission in manifest.permissions
            )
        ),
        "source": source or {"type": "upload"},
        "ui": {
            "pages": list(manifest.ui.pages),
            "menus": list(manifest.ui.menus),
            "has_custom_frontend": manifest.frontend is not None,
        },
    }


async def _plan_candidate_dependencies(
    manifest: Any,
    *,
    available: list[dict[str, Any]] | None = None,
) -> DependencyPlan:
    if not manifest.dependencies:
        return plan_dependencies(manifest, ())
    try:
        installed = await _client.plugins()
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    return plan_dependencies(manifest, installed, available or ())


async def _validate_backend_route_candidate(manifest: Any) -> None:
    """Ensure one package cannot take over an existing plugin-owned host URL."""

    if not any(route.scope is BackendRouteScope.HOST for route in manifest.backend_routes):
        return
    try:
        validate_host_route_ownership(
            await _client.plugins(),
            candidate_plugin_id=manifest.plugin_id,
            candidate_routes=manifest.backend_routes,
        )
    except BackendRouteConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "plugin_route_conflict", "message": str(exc)},
        ) from exc


def _dangerous_approved_permissions(
    inspected: InspectedPackage, approved_keys: set[str]
) -> list[str]:
    if inspected.trust.is_verified:
        return []
    return [
        _permission_key(permission.capability.name.value, permission.capability.version)
        for permission in inspected.package.manifest.permissions
        if _permission_key(permission.capability.name.value, permission.capability.version)
        in approved_keys
        and capability_definition(permission.capability.name).highly_privileged
    ]


def _require_dangerous_reauthentication(
    inspected: InspectedPackage,
    approved_keys: set[str],
    *,
    admin: User,
    admin_password: str | None,
    confirm_dangerous: bool,
) -> list[str]:
    dangerous = _dangerous_approved_permissions(inspected, approved_keys)
    if not dangerous:
        return []
    if not confirm_dangerous:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "dangerous_permissions_confirmation_required",
                "message": (
                    "Explicit confirmation is required for dangerous unverified permissions."
                ),
                "permissions": dangerous,
            },
        )
    password_hash = getattr(admin, "password_hash", "")
    if not admin_password or not verify_password(admin_password, password_hash):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "administrator_reauthentication_failed",
                "message": "Administrator password re-entry is required for these permissions.",
                "permissions": dangerous,
            },
        )
    return dangerous


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
    raise HTTPException(
        status_code=400,
        detail={
            "code": "plugin_file_missing",
            "message": "Upload a .utp package as a multipart file.",
        },
    )


@router.post("/install/preview-url")
async def preview_plugin_install_url(
    request: PluginInstallUrl, admin: User = Depends(get_current_admin)
) -> dict[str, Any]:
    """Download and statically inspect a remote .utp/.zip package."""
    path: Path | None = None
    try:
        path, filename, total = await _download_remote_file(request.url)
        inspected = _inspect_install_candidate(path)
        available: list[dict[str, Any]] = []
        if request.source_type == "catalogue" and request.catalogue_url:
            available = [
                entry.model_dump()
                for entry in await plugin_catalog(source=request.catalogue_url, user=admin)
            ]
        dependencies = await _plan_candidate_dependencies(
            inspected.package.manifest,
            available=available,
        )
        source = {
            "type": request.source_type,
            "url": request.url,
            "catalogue_url": request.catalogue_url,
            "release_notes": request.release_notes,
            "changelog_url": request.changelog_url,
        }
        return {
            **_install_preview(inspected, dependencies, source=source),
            "source_url": request.url,
            "download_filename": filename,
            "download_bytes": total,
        }
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


@router.post("/install/url", status_code=201)
async def install_plugin_url(
    request: PluginInstallUrl,
    allow_untrusted: bool = False,
    approved_permissions: list[str] | None = Query(default=None),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Download a remote package and send it through the same install/consent path."""
    path: Path | None = None
    upload: UploadFile | None = None
    try:
        path, filename, _ = await _download_remote_file(request.url)
        inspected = _inspect_install_candidate(path)
        if (
            request.expected_digest
            and inspected.package.manifest.integrity.sha256.lower()
            != request.expected_digest.lower()
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The remote plugin changed after preview; review it again before installing."
                ),
            )
        upload = UploadFile(path.open("rb"), filename=filename)
        return await _install_plugin_package(
            upload,
            allow_untrusted=allow_untrusted,
            approved_permissions=approved_permissions,
            admin_password=request.admin_password,
            confirm_dangerous=request.confirm_dangerous,
            source_metadata={
                "type": request.source_type,
                "url": request.url,
                "catalogue_url": request.catalogue_url,
                "release_notes": request.release_notes,
                "changelog_url": request.changelog_url,
            },
            admin=admin,
            db=db,
        )
    finally:
        if upload is not None:
            await upload.close()
        if path is not None:
            path.unlink(missing_ok=True)


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
        inspected = _inspect_install_candidate(path)
        dependencies = await _plan_candidate_dependencies(inspected.package.manifest)
        logger.info(
            "Plugin install preview validated: plugin_id=%s version=%s "
            "filename=%r bytes=%d trust=%s",
            inspected.package.manifest.plugin_id,
            inspected.package.manifest.version,
            filename,
            total,
            inspected.trust.status.value,
        )
        return _install_preview(inspected, dependencies)
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
    admin_password: str | None = Query(default=None),
    confirm_dangerous: bool = Query(default=False),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _install_plugin_package(
        file,
        allow_untrusted=allow_untrusted,
        approved_permissions=approved_permissions,
        admin_password=admin_password,
        confirm_dangerous=confirm_dangerous,
        source_metadata={"type": "upload"},
        admin=admin,
        db=db,
    )


async def _install_plugin_package(
    file: UploadFile,
    *,
    allow_untrusted: bool,
    approved_permissions: list[str] | None,
    admin_password: str | None,
    confirm_dangerous: bool,
    source_metadata: dict[str, Any],
    admin: User,
    db: AsyncSession,
) -> dict[str, Any]:
    """Commit a previewed package and the administrator's explicit permission decisions."""
    temporary_path: Path | None = None
    try:
        temporary_path, _, total = await _store_plugin_upload(file, "plugin-upload-")
        inspected = _inspect_install_candidate(temporary_path)
        verified = inspected.package
        trust = inspected.trust
        await _validate_backend_route_candidate(verified.manifest)
        if not trust.installable:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_signature",
                    "message": trust.warning,
                    **_install_preview(inspected),
                },
            )
        if not trust.is_verified and not allow_untrusted:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "untrusted_plugin",
                    "message": (
                        "The plugin publisher is not verified. "
                        "Explicit untrusted consent is required."
                    ),
                    **_install_preview(inspected),
                },
            )

        dependency_plan = await _plan_candidate_dependencies(verified.manifest)
        if not dependency_plan.ready:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "dependency_resolution_failed",
                    "message": "Required plugin dependencies must be installed compatibly first.",
                    **_install_preview(inspected, dependency_plan, source=source_metadata),
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
        dangerous_permissions = _require_dangerous_reauthentication(
            inspected,
            approved_keys,
            admin=admin,
            admin_password=admin_password,
            confirm_dangerous=confirm_dangerous,
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
                f"{verified.manifest.plugin_id}-{verified.manifest.version}.utp",
                installation_id=str(installation_id),
                source_metadata=source_metadata,
                trust_metadata={
                    "status": trust.status.value,
                    "signature_present": trust.signature_present,
                    "signature_verified": trust.signature_verified,
                    "publisher_key_id": trust.publisher_key_id,
                    "publisher_identity": trust.publisher_identity,
                },
            )
        except PluginRuntimeRequestError as exc:
            await db.rollback()
            raise _runtime_request_error(exc) from exc
        except PluginRuntimeUnavailable as exc:
            await db.rollback()
            raise _runtime_error(exc) from exc
        await db.commit()
        activation_status = "installed"
        healthy = False
        try:
            await _client.start(
                quote(verified.manifest.plugin_id, safe=""),
                user_id=str(getattr(admin, "id", "")) or None,
            )
            healthy = await _client.plugin_health(quote(verified.manifest.plugin_id, safe=""))
            activation_status = "running" if healthy else "unhealthy"
        except (PluginRuntimeRequestError, PluginRuntimeUnavailable) as exc:
            logger.warning(
                "Plugin installed but activation failed: plugin_id=%s error=%s",
                verified.manifest.plugin_id,
                exc,
            )
            activation_status = "failed_activation"
        logger.info(
            "Plugin install committed: plugin_id=%s installation_id=%s bytes=%d "
            "granted=%d denied=%d trust=%s",
            verified.manifest.plugin_id,
            installation_id,
            total,
            len(permission_grants),
            len(permission_requests) - len(permission_grants),
            trust.status.value,
        )
        return {
            "plugin_id": verified.manifest.plugin_id,
            "version": verified.manifest.version,
            "name": verified.manifest.name,
            "publisher": trust.publisher_identity,
            "publisher_key_id": trust.publisher_key_id,
            "installation_id": str(installation_id),
            "permissions_requested": len(permission_requests),
            "permissions_granted": len(permission_grants),
            "permissions_denied": len(permission_requests) - len(permission_grants),
            "trust_status": trust.status.value,
            "trust_warning": trust.warning,
            "dangerous_permissions_reauthenticated": dangerous_permissions,
            "install_status": result.get("status", "installed"),
            "status": activation_status,
            "healthy": healthy,
        }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        await file.close()


@router.get("/catalogues")
async def list_plugin_catalogues(
    admin: User = Depends(get_current_admin),
) -> list[dict[str, Any]]:
    del admin
    try:
        return _catalogue_store().list()
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/catalogues", status_code=201)
async def create_plugin_catalogue(
    payload: PluginCatalogueCreate,
    admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    del admin
    url = _validate_remote_url(payload.url)
    try:
        return _catalogue_store().add(
            name=payload.name.strip(),
            url=url,
            enabled=payload.enabled,
            priority=payload.priority,
        )
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/catalogues/{catalogue_id}")
async def update_plugin_catalogue(
    catalogue_id: str,
    payload: PluginCatalogueUpdate,
    admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    del admin
    changes = payload.model_dump(exclude_unset=True)
    if "url" in changes:
        changes["url"] = _validate_remote_url(str(changes["url"]))
    if "name" in changes:
        changes["name"] = str(changes["name"]).strip()
    try:
        return _catalogue_store().update(catalogue_id, **changes)
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/catalogues/{catalogue_id}", status_code=204)
async def delete_plugin_catalogue(
    catalogue_id: str,
    admin: User = Depends(get_current_admin),
) -> Response:
    del admin
    try:
        _catalogue_store().remove(catalogue_id)
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/catalog", response_model=list[PluginCatalogEntry])
async def plugin_catalog(
    source: str | None = Query(default=None, min_length=1, max_length=2048),
    user: User = Depends(get_current_user),
) -> list[PluginCatalogEntry]:
    del user
    catalog_url = source or _PLUGIN_CATALOG_URL
    path: Path | None = None
    configured = next(
        (item for item in _catalogue_store().list() if item.get("url") == catalog_url),
        None,
    )
    try:
        path, _, _ = await _download_remote_file(catalog_url, json_document=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = [PluginCatalogEntry.model_validate(entry) for entry in _catalog_entries(payload)]
        if configured is not None:
            _catalogue_store().record_check(str(configured["id"]), None)
        return entries
    except json.JSONDecodeError as exc:
        if configured is not None:
            _catalogue_store().record_check(str(configured["id"]), "Catalogue is not valid JSON.")
        raise HTTPException(status_code=502, detail="Plugin catalogue is not valid JSON.") from exc
    except HTTPException as exc:
        if configured is not None:
            _catalogue_store().record_check(str(configured["id"]), str(exc.detail)[:1000])
        raise
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


async def _check_plugin_update(
    plugin: dict[str, Any],
    admin: User,
) -> dict[str, Any]:
    plugin_id = str(plugin.get("plugin_id", ""))
    current_version = str(plugin.get("version", "0.0.0"))
    source_value = plugin.get("source")
    source: dict[str, Any] = source_value if isinstance(source_value, dict) else {}
    source_type = source.get("type")
    candidate_url: str | None = None
    release_notes: str | None = None
    changelog_url: str | None = None
    available_version: str | None = None

    if source_type == "catalogue" and isinstance(source.get("catalogue_url"), str):
        entries = await plugin_catalog(source=str(source["catalogue_url"]), user=admin)
        entry = next((item for item in entries if item.plugin_id == plugin_id), None)
        if entry is None:
            raise HTTPException(
                status_code=404, detail="Plugin is no longer listed by its catalogue."
            )
        candidate_url = entry.url
        available_version = entry.version
        release_notes = entry.release_notes
        changelog_url = entry.changelog_url
    elif source_type == "url" and isinstance(source.get("url"), str):
        candidate_url = str(source["url"])
        path: Path | None = None
        try:
            path, _, _ = await _download_remote_file(candidate_url)
            inspected = _inspect_install_candidate(path)
            if inspected.package.manifest.plugin_id != plugin_id:
                raise HTTPException(
                    status_code=409, detail="Update source returned a different plugin."
                )
            available_version = inspected.package.manifest.version
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
        release_notes = source.get("release_notes")
        changelog_url = source.get("changelog_url")
    else:
        return {
            "plugin_id": plugin_id,
            "current_version": current_version,
            "update_available": False,
            "reason": "No update-capable source metadata is recorded.",
        }

    update_available = bool(
        available_version and parse_semver(available_version) > parse_semver(current_version)
    )
    return {
        "plugin_id": plugin_id,
        "current_version": current_version,
        "available_version": available_version,
        "update_available": update_available,
        "url": candidate_url,
        "release_notes": release_notes,
        "changelog_url": changelog_url,
        "source": source,
    }


async def _notify_plugin_update(
    db: AsyncSession,
    update: dict[str, Any],
) -> None:
    if not update.get("update_available"):
        return
    plugin_id = str(update["plugin_id"])
    version = str(update["available_version"])
    dedupe_key = f"plugin-update:{plugin_id}:{version}"
    admin_ids = list(
        await db.scalars(select(User.id).where(User.is_admin.is_(True), User.is_active.is_(True)))
    )
    if not admin_ids:
        return
    existing = set(
        await db.scalars(
            select(Notification.user_id).where(
                Notification.user_id.in_(admin_ids),
                Notification.dedupe_key == dedupe_key,
            )
        )
    )
    now = int(time.time())
    for user_id in admin_ids:
        if user_id in existing:
            continue
        db.add(
            Notification(
                user_id=user_id,
                kind="plugin_update",
                media_type="plugin",
                media_id=uuid5(NAMESPACE_URL, f"urn:unnamed-tracking:plugin:{plugin_id}"),
                title=f"Plugin update available: {plugin_id}",
                body=f"Version {version} is available (installed: {update['current_version']}).",
                poster_url=None,
                event_at=now,
                dedupe_key=dedupe_key,
            )
        )


@router.post("/updates/check")
async def check_plugin_updates(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates: list[dict[str, Any]] = []
    for plugin in await _client.plugins():
        try:
            update = await _check_plugin_update(plugin, admin)
        except HTTPException as exc:
            update = {
                "plugin_id": plugin.get("plugin_id"),
                "current_version": plugin.get("version"),
                "update_available": False,
                "error": str(exc.detail),
            }
        updates.append(update)
        await _notify_plugin_update(db, update)
    await db.commit()
    return {
        "updates": updates,
        "available": sum(bool(item.get("update_available")) for item in updates),
        "checked_at": int(time.time()),
    }


@router.get("/{plugin_id}/changelog")
async def plugin_changelog(
    plugin_id: str,
    admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    plugin = next(
        (item for item in await _client.plugins() if item.get("plugin_id") == plugin_id),
        None,
    )
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    update = await _check_plugin_update(plugin, admin)
    if update.get("release_notes"):
        return {
            "plugin_id": plugin_id,
            "version": update.get("available_version"),
            "format": "markdown",
            "source": "catalogue",
            "body": update["release_notes"],
        }
    changelog_url = update.get("changelog_url")
    if not isinstance(changelog_url, str):
        return {
            "plugin_id": plugin_id,
            "version": update.get("available_version"),
            "format": "text",
            "source": "none",
            "body": "No release notes were supplied by this update source.",
        }
    path: Path | None = None
    try:
        path, _, _ = await _download_remote_file(changelog_url, json_document=True)
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=502, detail="Plugin changelog is not UTF-8 text."
            ) from exc
        return {
            "plugin_id": plugin_id,
            "version": update.get("available_version"),
            "format": "markdown",
            "source": "remote",
            "url": changelog_url,
            "body": body,
        }
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


async def _live_plugin(plugin_id: str, *, require_enabled: bool = True) -> dict[str, Any]:
    """Resolve a live installation before any capability can execute."""
    try:
        installed = await _client.plugins()
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    matches = [item for item in installed if item.get("plugin_id") == plugin_id]
    if len(matches) != 1 or not matches[0].get("installation_id"):
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    plugin = matches[0]
    try:
        UUID(str(plugin["installation_id"]))
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail="Plugin installation identity is invalid."
        ) from exc
    if require_enabled and not installation_is_executable(plugin):
        raise HTTPException(status_code=409, detail="Plugin installation is not executable.")
    return plugin


async def _plugin_and_capabilities(
    plugin_id: str,
    db: AsyncSession,
    user: User,
    *,
    require_enabled: bool = True,
) -> tuple[dict[str, Any], frozenset[str]]:
    """Resolve one enabled installation and this user's effective grants."""
    plugin = await _live_plugin(plugin_id, require_enabled=require_enabled)
    if not installation_is_executable(plugin):
        return plugin, frozenset()
    installation_id = UUID(str(plugin["installation_id"]))
    rows = await db.execute(
        select(
            PluginPermissionGrant.capability,
            PluginPermissionGrant.capability_version,
        ).where(
            PluginPermissionGrant.plugin_id == plugin_id,
            PluginPermissionGrant.installation_id == installation_id,
            PluginPermissionGrant.revoked_at.is_(None),
            PluginPermissionGrant.device_id.is_(None),
            or_(
                PluginPermissionGrant.user_id.is_(None),
                PluginPermissionGrant.user_id == user.id,
            ),
        )
    )
    granted = [str(capability) for capability, version in rows if version == 1]
    return plugin, frozenset(expand_capabilities(granted))


def _filter_ui_document(
    document: PluginUiDocument,
    effective_capabilities: frozenset[str],
) -> PluginUiDocument:
    """Remove host integrations that this installation is not authorized to mount."""

    def permitted(capability: Capability) -> bool:
        return capability.value in effective_capabilities

    navigation_capabilities = {
        "main.sidebar": Capability.FRONTEND_NAVIGATION_MAIN,
        "settings.sidebar": Capability.FRONTEND_NAVIGATION_SETTINGS,
        "administration": Capability.FRONTEND_NAVIGATION_ADMIN,
        "game.context": Capability.FRONTEND_CONTEXT_GAME,
        "media.context": Capability.FRONTEND_CONTEXT_MEDIA,
    }
    context_capabilities = {
        "game": Capability.FRONTEND_CONTEXT_GAME,
        "media": Capability.FRONTEND_CONTEXT_MEDIA,
        "documents": Capability.FRONTEND_CONTEXT_DOCUMENTS,
    }
    extension_capabilities = {
        "app.global": Capability.FRONTEND_OVERLAY,
        "home.replace": Capability.FRONTEND_PAGE_REPLACE_HOME,
    }
    authorized_routes = document.routes if permitted(Capability.FRONTEND_ROUTES) else ()
    authorized_settings = (
        document.settings_sections if permitted(Capability.FRONTEND_SETTINGS) else ()
    )
    authorized_route_ids = {item.id for item in authorized_routes}
    authorized_settings_ids = {item.id for item in authorized_settings}
    return document.model_copy(
        update={
            "native_frontend": (
                document.native_frontend if permitted(Capability.FRONTEND_NATIVE) else None
            ),
            "navigation": tuple(
                item
                for item in document.navigation
                if permitted(navigation_capabilities[item.location.value])
                and (item.route_id is None or item.route_id in authorized_route_ids)
                and (
                    item.settings_section_id is None
                    or item.settings_section_id in authorized_settings_ids
                )
            ),
            "settings_sections": authorized_settings,
            "extensions": tuple(
                item
                for item in document.extensions
                if permitted(
                    extension_capabilities.get(item.slot.value, Capability.FRONTEND_PAGE_EXTEND)
                )
            ),
            "overlays": (document.overlays if permitted(Capability.FRONTEND_OVERLAY) else ()),
            "dialog_contributions": (
                document.dialog_contributions if permitted(Capability.FRONTEND_DIALOG) else ()
            ),
            "contextual_actions": tuple(
                item
                for item in document.contextual_actions
                if permitted(context_capabilities[item.location.value])
            ),
            "routes": authorized_routes,
            "page_replacements": tuple(
                item
                for item in document.page_replacements
                if permitted(Capability(f"frontend.page.replace.{item.page.value}"))
            ),
        }
    )


@router.get("", response_model=list[dict])
async def list_plugins(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    try:
        plugins = await _client.plugins()
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    result: list[dict] = []
    for plugin in plugins:
        granted: list[str] = []
        installation_id = plugin.get("installation_id")
        if installation_id:
            rows = await db.execute(
                select(
                    PluginPermissionGrant.capability,
                    PluginPermissionGrant.capability_version,
                ).where(
                    PluginPermissionGrant.plugin_id == plugin.get("plugin_id"),
                    PluginPermissionGrant.installation_id == UUID(str(installation_id)),
                    PluginPermissionGrant.revoked_at.is_(None),
                    PluginPermissionGrant.device_id.is_(None),
                    or_(
                        PluginPermissionGrant.user_id.is_(None),
                        PluginPermissionGrant.user_id == user.id,
                    ),
                )
            )
            granted = [str(capability) for capability, version in rows if version == 1]
        result.append(
            {
                **plugin,
                "granted_capabilities": sorted(set(granted)),
                "effective_capabilities": (
                    list(expand_capabilities(granted)) if installation_is_executable(plugin) else []
                ),
            }
        )
    return sorted(result, key=lambda value: value["plugin_id"])


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


async def _update_context(
    plugin_id: str,
    inspected: InspectedPackage,
    db: AsyncSession,
) -> tuple[dict[str, Any], UUID, Any, DependencyPlan, bool]:
    manifest = inspected.package.manifest
    if manifest.plugin_id != plugin_id:
        raise HTTPException(
            status_code=400,
            detail="Updated package plugin ID does not match the installed plugin.",
        )
    installed_plugins = await _client.plugins()
    installed = next(
        (item for item in installed_plugins if item.get("plugin_id") == plugin_id),
        None,
    )
    if installed is None or not installed.get("installation_id"):
        raise HTTPException(status_code=409, detail="Plugin installation identity is missing.")
    if parse_semver(manifest.version) <= parse_semver(str(installed.get("version", "0.0.0"))):
        raise HTTPException(status_code=409, detail="Plugin update version must be newer.")
    installation_id = UUID(str(installed["installation_id"]))
    installed_trust_value = installed.get("trust")
    installed_trust: dict[str, Any] = (
        installed_trust_value if isinstance(installed_trust_value, dict) else {}
    )
    previous_identity = PluginPackageIdentity(
        plugin_id=plugin_id,
        publisher_key_id=installed_trust.get("publisher_key_id") or installed.get("publisher"),
    )
    candidate_identity = PluginPackageIdentity(
        plugin_id=manifest.plugin_id,
        publisher_key_id=(
            manifest.integrity.key_id if manifest.integrity.signature is not None else None
        ),
    )
    can_retain_grants = inspected.trust.is_verified and package_identity_can_retain_grants(
        previous_identity,
        candidate_identity,
    )
    if installed_trust.get("status") == PackageTrustStatus.TRUSTED.value and not can_retain_grants:
        raise HTTPException(
            status_code=409,
            detail=(
                "The verified update publisher does not match the installed package. "
                "Install it as a new lifecycle instance and review permissions again."
            ),
        )
    grant_rows = (
        await db.execute(
            select(
                PluginPermissionGrant.capability,
                PluginPermissionGrant.capability_version,
            ).where(
                PluginPermissionGrant.plugin_id == plugin_id,
                PluginPermissionGrant.installation_id == installation_id,
                PluginPermissionGrant.revoked_at.is_(None),
            )
        )
    ).all()
    existing_grants = tuple(
        CapabilityRef(name=capability, version=version) for capability, version in grant_rows
    )
    previous_requested = (
        tuple(
            CapabilityRef.model_validate(reference)
            for reference in installed.get("permission_refs", [])
        )
        if can_retain_grants
        else ()
    )
    permission_delta = calculate_permission_delta(
        previous_requested,
        tuple(permission.capability for permission in manifest.permissions),
        existing_grants if can_retain_grants else (),
    )
    dependencies = plan_dependencies(
        manifest,
        (item for item in installed_plugins if item.get("plugin_id") != plugin_id),
    )
    return installed, installation_id, permission_delta, dependencies, can_retain_grants


def _update_preview(
    inspected: InspectedPackage,
    installed: dict[str, Any],
    permission_delta: Any,
    dependencies: DependencyPlan,
    *,
    can_retain_grants: bool,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preview = _install_preview(
        inspected,
        dependencies,
        source=(
            source
            if source is not None
            else installed.get("source")
            if isinstance(installed.get("source"), dict)
            else None
        ),
    )
    new_keys = {
        _permission_key(item.name.value, item.version)
        for item in permission_delta.newly_requested_grants
    }
    preview["permissions"] = [
        {**permission, "new": permission["key"] in new_keys}
        for permission in preview["permissions"]
    ]
    preview.update(
        {
            "operation": "update",
            "installed_version": installed.get("version"),
            "permission_delta": permission_delta.model_dump(mode="json"),
            "new_permission_keys": sorted(new_keys),
            "existing_grants_retained": can_retain_grants,
            "identity_warning": (
                None
                if can_retain_grants
                else (
                    "Unverified updates cannot inherit existing permission grants; "
                    "review every requested permission again."
                )
            ),
            "release_notes": (
                source.get("release_notes")
                if isinstance(source, dict)
                else installed.get("source", {}).get("release_notes")
                if isinstance(installed.get("source"), dict)
                else None
            ),
        }
    )
    return preview


@router.put("/{plugin_id}/update/preview")
async def preview_plugin_update(
    plugin_id: str,
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del admin
    temporary_path: Path | None = None
    try:
        temporary_path, _, _ = await _store_plugin_upload(file, "plugin-update-preview-")
        inspected = _inspect_install_candidate(temporary_path)
        installed, _, permission_delta, dependencies, can_retain_grants = await _update_context(
            plugin_id, inspected, db
        )
        return _update_preview(
            inspected,
            installed,
            permission_delta,
            dependencies,
            can_retain_grants=can_retain_grants,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        await file.close()


@router.post("/{plugin_id}/update/preview-url")
async def preview_plugin_update_url(
    plugin_id: str,
    request: PluginInstallUrl,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del admin
    temporary_path: Path | None = None
    try:
        temporary_path, filename, total = await _download_remote_file(request.url)
        inspected = _inspect_install_candidate(temporary_path)
        installed, _, permission_delta, dependencies, can_retain_grants = await _update_context(
            plugin_id,
            inspected,
            db,
        )
        source = {
            "type": request.source_type,
            "url": request.url,
            "catalogue_url": request.catalogue_url,
            "release_notes": request.release_notes,
            "changelog_url": request.changelog_url,
        }
        return {
            **_update_preview(
                inspected,
                installed,
                permission_delta,
                dependencies,
                can_retain_grants=can_retain_grants,
                source=source,
            ),
            "source_url": request.url,
            "download_filename": filename,
            "download_bytes": total,
        }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@router.post("/{plugin_id}/update/url")
async def update_plugin_url(
    plugin_id: str,
    request: PluginInstallUrl,
    allow_untrusted: bool = False,
    approved_permissions: list[str] | None = Query(default=None),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    temporary_path: Path | None = None
    upload: UploadFile | None = None
    try:
        temporary_path, filename, _ = await _download_remote_file(request.url)
        inspected = _inspect_install_candidate(temporary_path)
        if (
            request.expected_digest
            and inspected.package.manifest.integrity.sha256.lower()
            != request.expected_digest.lower()
        ):
            raise HTTPException(
                status_code=409,
                detail="The remote plugin changed after preview; review it again before updating.",
            )
        upload = UploadFile(temporary_path.open("rb"), filename=filename)
        return await _update_plugin_package(
            plugin_id,
            upload,
            allow_untrusted=allow_untrusted,
            approved_permissions=approved_permissions,
            admin_password=request.admin_password,
            confirm_dangerous=request.confirm_dangerous,
            source_metadata={
                "type": request.source_type,
                "url": request.url,
                "catalogue_url": request.catalogue_url,
                "release_notes": request.release_notes,
                "changelog_url": request.changelog_url,
            },
            admin=admin,
            db=db,
        )
    finally:
        if upload is not None:
            await upload.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@router.put("/{plugin_id}/update", status_code=200)
async def update_plugin(
    plugin_id: str,
    file: UploadFile = File(...),
    allow_untrusted: bool = False,
    approved_permissions: list[str] | None = Query(default=None),
    admin_password: str | None = Query(default=None),
    confirm_dangerous: bool = Query(default=False),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _update_plugin_package(
        plugin_id,
        file,
        allow_untrusted=allow_untrusted,
        approved_permissions=approved_permissions,
        admin_password=admin_password,
        confirm_dangerous=confirm_dangerous,
        source_metadata=None,
        admin=admin,
        db=db,
    )


async def _update_plugin_package(
    plugin_id: str,
    file: UploadFile,
    *,
    allow_untrusted: bool,
    approved_permissions: list[str] | None,
    admin_password: str | None,
    confirm_dangerous: bool,
    source_metadata: dict[str, Any] | None,
    admin: User,
    db: AsyncSession,
) -> dict[str, Any]:
    temporary_path: Path | None = None
    try:
        temporary_path, _, _ = await _store_plugin_upload(file, "plugin-update-")
        inspected = _inspect_install_candidate(temporary_path)
        await _validate_backend_route_candidate(inspected.package.manifest)
        if not inspected.trust.installable:
            raise HTTPException(status_code=400, detail="Plugin package signature is invalid.")
        if not inspected.trust.is_verified and not allow_untrusted:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "untrusted_plugin",
                    "message": "Explicit unverified update consent is required.",
                    **_install_preview(inspected),
                },
            )
        (
            installed,
            installation_id,
            permission_delta,
            dependencies,
            can_retain_grants,
        ) = await _update_context(plugin_id, inspected, db)
        if not dependencies.ready:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "dependency_resolution_failed",
                    **_update_preview(
                        inspected,
                        installed,
                        permission_delta,
                        dependencies,
                        can_retain_grants=can_retain_grants,
                        source=source_metadata,
                    ),
                },
            )
        new_keys = {
            _permission_key(item.name.value, item.version)
            for item in permission_delta.newly_requested_grants
        }
        approved_keys = set(approved_permissions or ())
        if not approved_keys.issubset(new_keys):
            raise HTTPException(
                status_code=400, detail="Update consent contains an invalid permission."
            )
        dangerous = _require_dangerous_reauthentication(
            inspected,
            approved_keys,
            admin=admin,
            admin_password=admin_password,
            confirm_dangerous=confirm_dangerous,
        )
        now = int(time.time())
        if not can_retain_grants:
            await db.execute(
                sql_update(PluginPermissionGrant)
                .where(
                    PluginPermissionGrant.plugin_id == plugin_id,
                    PluginPermissionGrant.installation_id == installation_id,
                    PluginPermissionGrant.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        rows: list[Any] = []
        for capability in permission_delta.newly_requested_grants:
            key = _permission_key(capability.name.value, capability.version)
            approved = key in approved_keys
            rationale = next(
                permission.rationale
                for permission in inspected.package.manifest.permissions
                if permission.capability == capability
            )
            rows.append(
                PluginPermissionRequest(
                    plugin_id=plugin_id,
                    installation_id=installation_id,
                    capability=capability.name.value,
                    capability_version=capability.version,
                    rationale=rationale,
                    status="approved" if approved else "denied",
                    resolved_at=now,
                    resolved_by=getattr(admin, "id", None),
                )
            )
            if approved:
                rows.append(
                    PluginPermissionGrant(
                        plugin_id=plugin_id,
                        installation_id=installation_id,
                        capability=capability.name.value,
                        capability_version=capability.version,
                    )
                )
            rows.append(
                PluginPermissionAudit(
                    plugin_id=plugin_id,
                    installation_id=installation_id,
                    capability=capability.name.value,
                    capability_version=capability.version,
                    user_id=getattr(admin, "id", None),
                    decision="allowed" if approved else "denied",
                    reason="administrator update consent",
                )
            )
        db.add_all(rows)
        try:
            result = await _client.install_package(
                temporary_path.read_bytes(),
                f"{plugin_id}-{inspected.package.manifest.version}.utp",
                installation_id=str(installation_id),
                replace=True,
                source_metadata=source_metadata,
                trust_metadata={
                    "status": inspected.trust.status.value,
                    "signature_present": inspected.trust.signature_present,
                    "signature_verified": inspected.trust.signature_verified,
                    "publisher_key_id": inspected.trust.publisher_key_id,
                    "publisher_identity": inspected.trust.publisher_identity,
                },
            )
        except PluginRuntimeRequestError as exc:
            await db.rollback()
            raise _runtime_request_error(exc) from exc
        except PluginRuntimeUnavailable as exc:
            await db.rollback()
            raise _runtime_error(exc) from exc
        if can_retain_grants:
            removed_keys = {
                (capability.name.value, capability.version)
                for capability in permission_delta.removed
            }
            for grant in await db.scalars(
                select(PluginPermissionGrant).where(
                    PluginPermissionGrant.plugin_id == plugin_id,
                    PluginPermissionGrant.installation_id == installation_id,
                    PluginPermissionGrant.revoked_at.is_(None),
                )
            ):
                if (grant.capability, grant.capability_version) in removed_keys:
                    grant.revoked_at = now
        await db.commit()
        activation_status = result.get("status", "updated")
        healthy = False
        if installed.get("enabled"):
            try:
                await _client.start(quote(plugin_id, safe=""), user_id=str(admin.id))
                healthy = await _client.plugin_health(quote(plugin_id, safe=""))
                activation_status = "running" if healthy else "unhealthy"
            except (PluginRuntimeRequestError, PluginRuntimeUnavailable) as exc:
                logger.warning(
                    "Plugin update activation failed: plugin_id=%s error=%s", plugin_id, exc
                )
                activation_status = "failed_activation"
        return {
            "plugin_id": plugin_id,
            "version": inspected.package.manifest.version,
            "permissions_requested": len(permission_delta.newly_requested_grants),
            "permissions_granted": len(approved_keys),
            "permission_delta": permission_delta.model_dump(mode="json"),
            "dangerous_permissions_reauthenticated": dangerous,
            "trust_status": inspected.trust.status.value,
            "install_status": result.get("status", "updated"),
            "status": activation_status,
            "healthy": healthy,
        }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if not asset_path or ".." in Path(asset_path).parts:
        raise HTTPException(status_code=404, detail="Plugin frontend asset not found.")
    await _plugin_and_capabilities(plugin_id, db, user)
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


@router.get("/{plugin_id}/native-frontend/{asset_path:path}")
async def plugin_native_frontend(
    plugin_id: str,
    asset_path: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if not asset_path or ".." in Path(asset_path).parts:
        raise HTTPException(status_code=404, detail="Plugin native frontend asset not found.")
    _, capabilities = await _plugin_and_capabilities(plugin_id, db, user)
    if Capability.FRONTEND_NATIVE.value not in capabilities:
        raise HTTPException(
            status_code=403, detail="Permission frontend.native has not been granted."
        )
    try:
        content = await _client.native_frontend_asset(quote(plugin_id, safe=""), asset_path)
    except PluginRuntimeRequestError as exc:
        raise HTTPException(
            status_code=404, detail="Plugin native frontend asset not found."
        ) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    media_type = mimetypes.guess_type(asset_path)[0] or "application/octet-stream"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{plugin_id}/ui")
async def plugin_ui(
    plugin_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _, capabilities = await _plugin_and_capabilities(plugin_id, db, user, require_enabled=False)
    try:
        payload = await _client.plugin_ui(quote(plugin_id, safe=""))
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    try:
        document = PluginUiDocument.model_validate(payload)
    except ValidationError as exc:
        logger.warning("Rejected invalid plugin UI document: plugin_id=%s", plugin_id)
        raise HTTPException(status_code=422, detail="Plugin UI document is invalid.") from exc
    if document.plugin_id != plugin_id:
        raise HTTPException(status_code=422, detail="Plugin UI document identity is invalid.")
    return _filter_ui_document(document, capabilities).model_dump(mode="json")


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
    plugin = await _live_plugin(plugin_id)
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
    plugin = await _live_plugin(plugin_id)
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
    payload: PluginActionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    request_id = uuid4()
    plugin = await _live_plugin(plugin_id)
    document = await _client.plugin_ui(quote(plugin_id, safe=""))
    action = next(
        (item for item in document.get("actions", []) if item.get("id") == action_id), None
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Plugin action not found.")
    installation_id = UUID(str(plugin.get("installation_id")))
    capability_ref = action.get("capability")
    if capability_ref is not None:
        try:
            reference = CapabilityRef.model_validate(capability_ref)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail="Plugin action capability is invalid."
            ) from exc
        capability = reference.name.value
        if not await has_capability_grant(
            db,
            plugin_id=plugin_id,
            installation_id=installation_id,
            capability=capability,
            user_id=user.id,
            capability_version=reference.version,
        ):
            raise HTTPException(
                status_code=403, detail=f"Permission {capability} has not been granted."
            )
    values = dict(payload.values)
    values.pop("_plugin_context", None)
    context: dict[str, str] = {
        "path": f"/plugins/{plugin_id}",
        "user_id": str(user.id),
    }
    action_context = getattr(payload, "context", None)
    if action_context is not None:
        navigation_location = {
            "game": "game.context",
            "media": "media.context",
            "documents": None,
        }[action_context.kind]
        contextual_action = next(
            (
                item
                for item in document.get("contextual_actions", [])
                if item.get("action_id") == action_id
                and item.get("location") == action_context.kind
            ),
            None,
        )
        contextual_navigation = next(
            (
                item
                for item in document.get("navigation", [])
                if item.get("action_id") == action_id
                and item.get("location") == navigation_location
            ),
            None,
        )
        if contextual_action is None and contextual_navigation is None:
            raise HTTPException(
                status_code=403,
                detail="The action is not declared for this host context.",
            )
        context_capability = f"frontend.context.{action_context.kind}"
        if not await has_capability_grant(
            db,
            plugin_id=plugin_id,
            installation_id=installation_id,
            capability=context_capability,
            user_id=user.id,
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Permission {context_capability} has not been granted.",
            )
        context.update(
            {
                "kind": action_context.kind,
                "resource_id": action_context.resource_id,
            }
        )
        if action_context.resource_type is not None:
            context["resource_type"] = action_context.resource_type
    values["_plugin_context"] = context
    try:
        result = await _client.action(
            quote(plugin_id, safe=""), quote(action_id, safe=""), values, user_id=str(user.id)
        )
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
    model_config = ConfigDict(extra="forbid")
    plugin_id: str
    installation_id: UUID
    request_id: UUID
    user_id: UUID
    method: str
    capability: str
    capability_version: int = Field(default=1, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/runtime/gateway")
async def plugin_gateway(
    payload: PluginGatewayIn,
    db: AsyncSession = Depends(get_db),
    runtime_token: str | None = Header(default=None, alias="X-Plugin-Runtime-Token"),
) -> dict[str, Any]:
    if not runtime_token_is_valid(runtime_token):
        raise HTTPException(status_code=503, detail="Plugin runtime gateway is not configured.")
    plugin = await _live_plugin(payload.plugin_id)
    if UUID(str(plugin["installation_id"])) != payload.installation_id:
        raise HTTPException(status_code=409, detail="Plugin installation identity does not match.")
    user = await db.scalar(select(User).where(User.id == payload.user_id, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(status_code=403, detail="Active user context is required.")
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
            capability_version=payload.capability_version,
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


def _backend_route_error(
    status_code: int, code: str, message: str, request_id: UUID
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "api_version": "v1",
            "code": code,
            "message": message,
            "request_id": str(request_id),
        },
    )


async def _backend_route_request(
    request: Request,
    path_parameters: dict[str, str],
    request_id: UUID | None = None,
) -> dict[str, Any]:
    error_request_id = request_id or uuid4()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_PLUGIN_ROUTE_BODY_BYTES:
                raise _backend_route_error(
                    413,
                    "invalid_request",
                    "Plugin request body exceeds 48 KiB.",
                    error_request_id,
                )
        except ValueError as exc:
            raise _backend_route_error(
                400,
                "invalid_request",
                "Content-Length must be an integer.",
                error_request_id,
            ) from exc
    raw_body = await request.body()
    if len(raw_body) > _MAX_PLUGIN_ROUTE_BODY_BYTES:
        raise _backend_route_error(
            413,
            "invalid_request",
            "Plugin request body exceeds 48 KiB.",
            error_request_id,
        )
    body: dict[str, Any] | None = None
    if raw_body:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise _backend_route_error(
                415,
                "invalid_request",
                "Plugin backend routes accept JSON request bodies.",
                error_request_id,
            )
        try:
            decoded = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _backend_route_error(
                400,
                "invalid_request",
                "Plugin request body is not valid JSON.",
                error_request_id,
            ) from exc
        if not isinstance(decoded, dict):
            raise _backend_route_error(
                422,
                "invalid_request",
                "Plugin request body must be a JSON object.",
                error_request_id,
            )
        body = decoded
    payload = {
        "method": request.method,
        "path": request.url.path,
        "path_parameters": path_parameters,
        "query": {
            key: request.query_params.getlist(key) for key in sorted(request.query_params.keys())
        },
        "headers": {
            key: request.headers[key]
            for key in ("accept", "content-type")
            if key in request.headers
        },
        "body": body,
    }
    if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > (
        _MAX_PLUGIN_ROUTE_ENVELOPE_BYTES
    ):
        raise _backend_route_error(
            413,
            "invalid_request",
            "Plugin request exceeds the 64 KiB route limit.",
            error_request_id,
        )
    return payload


async def _resolve_plugin_backend_route(
    *,
    scope: BackendRouteScope,
    route_path: str,
    method: str,
    request_id: UUID,
    plugin_id: str | None = None,
) -> ResolvedBackendRoute:
    """Resolve the single installation that owns a declared request path."""

    try:
        installed_plugins = await _client.plugins()
        if scope is BackendRouteScope.HOST:
            validate_host_route_ownership(installed_plugins)
        resolved = resolve_backend_route(
            installed_plugins,
            scope=scope,
            path=route_path,
            method=method,
            plugin_id=plugin_id,
        )
    except BackendRouteConflictError as exc:
        logger.error("Plugin backend route ownership conflict: path=%s error=%s", route_path, exc)
        raise _backend_route_error(409, "conflict", str(exc), request_id) from exc
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    if resolved is None:
        raise _backend_route_error(404, "not_found", "Plugin backend route not found.", request_id)
    return resolved


def _route_installation(
    resolved: ResolvedBackendRoute, request_id: UUID
) -> tuple[str, UUID]:
    """Validate live installation identity and lifecycle state."""

    plugin = resolved.plugin
    owner_id = str(plugin.get("plugin_id", ""))
    installation_value = plugin.get("installation_id")
    if not installation_value:
        raise _backend_route_error(
            409, "unavailable", "Plugin installation identity is missing.", request_id
        )
    try:
        installation_id = UUID(str(installation_value))
    except ValueError as exc:
        raise _backend_route_error(
            409, "unavailable", "Plugin installation identity is invalid.", request_id
        ) from exc
    if not installation_is_executable(plugin):
        logger.warning(
            "Plugin backend route unavailable: request_id=%s plugin_id=%s "
            "installation_id=%s route_id=%s",
            request_id,
            owner_id,
            installation_id,
            resolved.route.id,
        )
        raise _backend_route_error(
            409, "unavailable", "Plugin is not available to serve backend routes.", request_id
        )
    return owner_id, installation_id


async def _authorize_plugin_backend_route(
    db: AsyncSession,
    *,
    resolved: ResolvedBackendRoute,
    scope: BackendRouteScope,
    user: User,
    request_id: UUID,
) -> tuple[str, UUID]:
    """Enforce host authorization policy and the installation-scoped capability grant."""

    owner_id, installation_id = _route_installation(resolved, request_id)
    if resolved.route.authorization is BackendRouteAuthorization.ADMIN and not getattr(
        user, "is_admin", False
    ):
        logger.warning(
            "Plugin backend route denied: request_id=%s plugin_id=%s installation_id=%s "
            "route_id=%s authorization=admin user_id=%s",
            request_id,
            owner_id,
            installation_id,
            resolved.route.id,
            user.id,
        )
        raise _backend_route_error(403, "forbidden", "Administrator access required.", request_id)

    required_capability = (
        Capability.BACKEND_ROUTES_PLUGIN
        if scope is BackendRouteScope.PLUGIN
        else Capability.BACKEND_ROUTES_HOST
    )
    if not await has_capability_grant(
        db,
        plugin_id=owner_id,
        installation_id=installation_id,
        capability=required_capability.value,
        user_id=user.id,
    ):
        logger.warning(
            "Plugin backend route denied: request_id=%s plugin_id=%s installation_id=%s "
            "route_id=%s capability=%s user_id=%s",
            request_id,
            owner_id,
            installation_id,
            resolved.route.id,
            required_capability.value,
            user.id,
        )
        raise _backend_route_error(
            403,
            "forbidden",
            f"Permission {required_capability.value} has not been granted.",
            request_id,
        )
    return owner_id, installation_id


async def _execute_plugin_backend_route(
    request: Request,
    *,
    resolved: ResolvedBackendRoute,
    owner_id: str,
    user: User,
    request_id: UUID,
) -> PluginBackendRouteResponse:
    """Execute one bounded runtime handler and validate its JSON response."""

    route_request = await _backend_route_request(
        request, resolved.path_parameters, request_id
    )
    route_request["user"] = {
        "id": str(user.id),
        "username": str(getattr(user, "username", "")),
        "is_admin": bool(getattr(user, "is_admin", False)),
    }
    try:
        raw_result = await _client.route(
            owner_id,
            resolved.route.id,
            route_request,
            user_id=str(user.id),
        )
        result = PluginBackendRouteResponse.model_validate(raw_result)
        json.dumps(result.body, allow_nan=False)
    except (TypeError, ValueError, ValidationError) as exc:
        logger.warning(
            "Plugin backend route returned an invalid response: request_id=%s plugin_id=%s "
            "route_id=%s",
            request_id,
            owner_id,
            resolved.route.id,
        )
        raise _backend_route_error(
            502, "invalid_request", "Plugin returned an invalid route response.", request_id
        ) from exc
    except PluginRuntimeRequestError as exc:
        logger.warning(
            "Plugin backend route execution failed: request_id=%s plugin_id=%s route_id=%s",
            request_id,
            owner_id,
            resolved.route.id,
        )
        raise _backend_route_error(
            502, "unavailable", "Plugin backend route is unavailable.", request_id
        ) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    return result


async def _dispatch_backend_route(
    request: Request,
    *,
    scope: BackendRouteScope,
    route_path: str,
    db: AsyncSession,
    user: User | None = None,
    plugin_id: str | None = None,
) -> Response:
    """Authenticate, authorize, and dispatch a declared plugin backend route."""

    request_id = uuid4()
    resolved = await _resolve_plugin_backend_route(
        scope=scope,
        route_path=route_path,
        method=request.method,
        request_id=request_id,
        plugin_id=plugin_id,
    )
    if user is None:
        user = await get_current_user(
            db,
            request.headers.get("authorization"),
            request.cookies.get("session"),
        )
    owner_id, installation_id = await _authorize_plugin_backend_route(
        db,
        resolved=resolved,
        scope=scope,
        user=user,
        request_id=request_id,
    )
    result = await _execute_plugin_backend_route(
        request,
        resolved=resolved,
        owner_id=owner_id,
        user=user,
        request_id=request_id,
    )
    logger.info(
        "Plugin backend route completed: request_id=%s plugin_id=%s installation_id=%s "
        "route_id=%s scope=%s method=%s user_id=%s status=%s",
        request_id,
        owner_id,
        installation_id,
        resolved.route.id,
        scope.value,
        request.method,
        user.id,
        result.status_code,
    )
    if result.status_code == 204:
        return Response(status_code=204)
    return JSONResponse(status_code=result.status_code, content=result.body)


@router.api_route(
    "/{plugin_id}/{route_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def plugin_backend_route(
    plugin_id: str,
    route_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Dispatch one authenticated request within a plugin-owned namespace."""

    return await _dispatch_backend_route(
        request,
        scope=BackendRouteScope.PLUGIN,
        route_path=route_path,
        plugin_id=plugin_id,
        db=db,
    )


@host_router.api_route(
    "/{route_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def plugin_host_backend_route(
    route_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Dispatch a privileged plugin route only after all core routes were considered."""

    return await _dispatch_backend_route(
        request,
        scope=BackendRouteScope.HOST,
        route_path=f"/{route_path}",
        db=db,
    )
