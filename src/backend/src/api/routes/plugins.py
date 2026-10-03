"""Application-facing Plugin Manager API backed by the isolated runtime."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import mimetypes
import os
import secrets
import socket
import tempfile
import time
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urljoin, urlparse
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import delete, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.responses import FileResponse, JSONResponse

from src.api.routes.session_manager import upload_geoip
from src.core.auth import get_current_admin, get_current_user, hash_token, verify_password
from src.database.models.auth import UserApiKey, UserSession
from src.database.models.notification import Notification
from src.database.models.plugin_notification_provider import (
    PluginNotificationProviderRegistration,
)
from src.database.models.plugin_permission_audit import PluginPermissionAudit
from src.database.models.plugin_permissions import (
    PluginClientIdentity,
    PluginPermissionGrant,
    PluginPermissionRequest,
)
from src.database.models.user import User
from src.database.session import get_db
from src.plugin_api.backend_routes import (
    BackendRouteConflictError,
    ResolvedBackendRoute,
    resolve_backend_route,
    validate_host_route_ownership,
)
from src.plugin_api.capabilities import (
    capability_children,
    capability_definition,
)
from src.plugin_api.catalogues import CatalogueStore, CatalogueStoreError
from src.plugin_api.contracts import (
    BackendRouteAuthorization,
    BackendRouteScope,
    Capability,
    CapabilityRef,
    ErrorCode,
    ErrorEnvelope,
    PermissionDeclaration,
    PluginDependency,
    PluginUiDocument,
    parse_semver,
)
from src.plugin_api.documents import DocumentAccessError, document_path, owned_document
from src.plugin_api.frontend_assets import inline_frontend_assets
from src.plugin_api.gateway import dispatch_gateway_request, runtime_token_is_valid
from src.plugin_api.grants import has_capability_grant, installation_is_executable
from src.plugin_api.installer import (
    DependencyPlan,
    InspectedPackage,
    InstallationConsent,
    InstallationError,
    PluginInstaller,
    inspect_package,
    plan_dependencies,
)
from src.plugin_api.management_auth import (
    MANAGEMENT_PREFIX,
    MANAGEMENT_SCOPES,
    get_plugin_manager_admin,
    get_plugin_manager_reader,
)
from src.plugin_api.manager_state import manager_state
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
_GATEWAY_DISPATCH_TIMEOUT = 8.0
_GEOIP_UPLOAD_FILE = File(...)
_PLUGIN_DB = Depends(get_db)
_PLUGIN_ADMIN = Depends(get_plugin_manager_admin)
_DOCUMENT_DATA_ROOT = Path("/data/users")


class PluginSettingsIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class PluginActionContext(BaseModel):
    """Host context accepted from a contribution mount, never arbitrary plugin data."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^(game|media|documents)$")
    resource_id: str = Field(min_length=1, max_length=128)
    resource_type: str | None = Field(default=None, min_length=1, max_length=64)


class PluginActionIn(PluginSettingsIn):
    confirmed: bool = Field(default=False, strict=True)
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


class CatalogueIcon(BaseModel):
    path: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")

    @model_validator(mode="after")
    def safe_path(self) -> "CatalogueIcon":
        if (
            "\\" in self.path
            or self.path.startswith("/")
            or any(part in {"", ".", ".."} for part in self.path.split("/"))
        ):
            raise ValueError("Icon path must be a safe relative package path")
        return self


class PluginCatalogEntry(BaseModel):
    """Transport metadata; packaged assets are validated during catalogue normalization."""

    model_config = {"populate_by_name": True}
    plugin_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2_000)
    version: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2048)
    release_notes: str | None = Field(default=None, max_length=4_000)
    changelog_url: str | None = Field(default=None, max_length=2048)
    dependencies: tuple[PluginDependency, ...] = ()
    icon: str | dict[str, str] | None = None
    icon_metadata: dict[str, str] | None = None
    publisher: str | None = None
    tags: tuple[str, ...] = ()
    readme: str | None = None
    compatibility: str | None = None
    permissions: list[dict[str, object]] = Field(default_factory=list)
    digest: str | None = Field(
        default=None,
        alias="sha256",
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    package_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    package: dict[str, object] = Field(default_factory=dict)
    signing: dict[str, object] = Field(default_factory=dict)
    documentation: dict[str, object] = Field(default_factory=dict)
    build: dict[str, object] = Field(default_factory=dict)
    automatic_update: bool = True


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


def _private_plugin_response(response: Response) -> None:
    """Plugin user data must not be cached or interpreted through MIME sniffing."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


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


def _catalog_entries(payload: Any, *, source_url: str | None = None) -> list[dict[str, Any]]:
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
            icon_metadata = entry.icon if isinstance(entry.icon, dict) else entry.icon_metadata
            if icon_metadata:
                packaged_icon = CatalogueIcon.model_validate(icon_metadata)
                entry.icon_metadata = packaged_icon.model_dump()
                entry.icon = None
                source_path = str(entry.build.get("source_path", ""))
                if (
                    source_url
                    and source_path
                    and all(part not in {"", ".", ".."} for part in str(source_path).split("/"))
                    and "\\" not in source_path
                ):
                    entry.icon = _validate_remote_url(
                        urljoin(source_url, source_path + "/" + packaged_icon.path)
                    )
            if not entry.compatibility:
                entry.compatibility = f"SDK {raw_entry.get('sdk_version_range', '*')}; application {raw_entry.get('application_version_range', '*')}"
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
    readme = None
    icon = manifest.icon
    if inspected.package.package_path.exists():
        with zipfile.ZipFile(inspected.package.package_path) as archive:
            import base64

            for name, content_type in (
                ("payload/icon.svg", "image/svg+xml"),
                ("payload/icon.png", "image/png"),
            ):
                if name in archive.namelist() and archive.getinfo(name).file_size <= 256 * 1024:
                    icon = f"data:{content_type};base64," + base64.b64encode(
                        archive.read(name)
                    ).decode("ascii")
                    break
            readme_name = next(
                (
                    name
                    for name in archive.namelist()
                    if name.lower() in {"payload/readme.md", "payload/readme.txt"}
                ),
                None,
            )
            if readme_name:
                readme = archive.read(readme_name)[: 128 * 1024].decode("utf-8", errors="replace")
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
        "icon": icon,
        "tags": inspected.package.distribution.get("tags", list(manifest.tags)),
        "automatic_update": manifest.automatic_update
        and inspected.package.distribution.get("automatic_update", True),
        "release_notes": inspected.package.distribution.get("release_notes"),
        "readme": readme,
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


async def _validate_catalogue_candidate(
    path: Path, inspected: InspectedPackage, request: PluginInstallUrl, admin: User
) -> list[PluginCatalogEntry]:
    """Bind every catalogue acquisition to its advertised identity and hashes."""
    if request.source_type != "catalogue":
        return []
    if not request.catalogue_url:
        raise HTTPException(422, "Catalogue URL is required for a catalogue package.")
    entries = await plugin_catalog(source=request.catalogue_url, user=admin)
    manifest = inspected.package.manifest
    entry = next((item for item in entries if item.plugin_id == manifest.plugin_id), None)
    if (
        entry is None
        or entry.url != request.url
        or entry.version != manifest.version
        or entry.digest
        and entry.digest.lower() != manifest.integrity.sha256.lower()
        or entry.package_sha256
        and entry.package_sha256.lower() != hashlib.sha256(path.read_bytes()).hexdigest()
    ):
        raise HTTPException(409, "Catalogue release and package identity or hashes differ.")
    return entries


@router.post("/install/preview-url")
async def preview_plugin_install_url(
    request: PluginInstallUrl, admin: User = Depends(get_plugin_manager_admin)
) -> dict[str, Any]:
    """Download and statically inspect a remote .utp/.zip package."""
    path: Path | None = None
    try:
        path, filename, total = await _download_remote_file(request.url)
        inspected = _inspect_install_candidate(path)
        available = [
            entry.model_dump()
            for entry in await _validate_catalogue_candidate(path, inspected, request, admin)
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
    admin: User = Depends(get_plugin_manager_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Download a remote package and send it through the same install/consent path."""
    path: Path | None = None
    upload: UploadFile | None = None
    try:
        path, filename, _ = await _download_remote_file(request.url)
        inspected = _inspect_install_candidate(path)
        await _validate_catalogue_candidate(path, inspected, request, admin)
        upload = UploadFile(path.open("rb"), filename=filename)
        return await _install_plugin_package(
            upload,
            allow_untrusted=allow_untrusted,
            approved_permissions=approved_permissions,
            admin_password=request.admin_password,
            confirm_dangerous=request.confirm_dangerous,
            expected_digest=request.expected_digest,
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
    admin: User = Depends(get_plugin_manager_admin),
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
    admin_password: str | None = Form(default=None),
    confirm_dangerous: bool = Query(default=False),
    admin: User = Depends(get_plugin_manager_admin),
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


def _plugin_installer() -> PluginInstaller:
    return PluginInstaller(_client, _plugin_package_verifier(), verify_password)


async def _commit_plugin_upload(
    file: UploadFile,
    *,
    consent: InstallationConsent,
    source_metadata: dict[str, Any] | None,
    admin: User,
    db: AsyncSession,
    plugin_id: str | None = None,
    operation: str = "update",
) -> dict[str, Any]:
    """HTTP acquisition adapter; all policy and lifecycle decisions belong to the installer."""
    temporary_path: Path | None = None
    try:
        temporary_path, _, _ = await _store_plugin_upload(file, "plugin-candidate-")
        return await _plugin_installer().install(
            temporary_path.read_bytes(),
            consent=consent,
            admin=admin,
            db=db,
            source=source_metadata,
            update_plugin_id=plugin_id,
            operation=operation,
        )
    except InstallationError as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            if exc.plan is not None:
                plan = exc.plan
                preview = (
                    _update_preview(
                        plan.inspected,
                        plan.installed,
                        plan.permissions,
                        plan.dependencies,
                        can_retain_grants=plan.can_retain_grants,
                        source=source_metadata,
                    )
                    if plan.installed is not None
                    else _install_preview(plan.inspected, plan.dependencies, source=source_metadata)
                )
                detail = {**preview, **detail}
            elif exc.inspected is not None:
                detail = {**_install_preview(exc.inspected), **detail}
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except (PackageFormatError, PackageVerificationError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_package",
                "trust_status": "invalid_package",
                "message": str(exc),
            },
        ) from exc
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        await file.close()


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
    expected_digest: str | None = None,
) -> dict[str, Any]:
    return await _commit_plugin_upload(
        file,
        consent=InstallationConsent(
            allow_untrusted=allow_untrusted,
            approved_permissions=tuple(approved_permissions)
            if isinstance(approved_permissions, list)
            else (),
            admin_password=admin_password,
            confirm_dangerous=confirm_dangerous,
            expected_digest=expected_digest,
        ),
        source_metadata=source_metadata,
        admin=admin,
        db=db,
    )


@router.get("/catalogues")
async def list_plugin_catalogues(
    admin: User = Depends(get_plugin_manager_admin),
) -> list[dict[str, Any]]:
    del admin
    try:
        return _catalogue_store().list()
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/catalogues", status_code=201)
async def create_plugin_catalogue(
    payload: PluginCatalogueCreate,
    admin: User = Depends(get_plugin_manager_admin),
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
    admin: User = Depends(get_plugin_manager_admin),
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
    admin: User = Depends(get_plugin_manager_admin),
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
    user: User = Depends(get_plugin_manager_reader),
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
        entries = [
            PluginCatalogEntry.model_validate(entry)
            for entry in _catalog_entries(payload, source_url=catalog_url)
        ]
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
        "automatic_update": entry.automatic_update
        if source_type == "catalogue" and entry is not None
        else False,
        "digest": entry.digest if source_type == "catalogue" and entry is not None else None,
        "package_sha256": entry.package_sha256
        if source_type == "catalogue" and entry is not None
        else None,
    }


async def _notify_plugin_update(
    db: AsyncSession,
    update: dict[str, Any],
    *,
    failed: bool = False,
) -> None:
    if not update.get("update_available"):
        return
    plugin_id = str(update["plugin_id"])
    version = str(update["available_version"])
    dedupe_key = f"plugin-update:{plugin_id}:{version}" + (":failed" if failed else "")
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
                title=f"Plugin update {'failed' if failed else 'available'}: {plugin_id}",
                body=(
                    f"Version {version} could not be activated. The previous package is retained; inspect Plugin Manager diagnostics."
                    if failed
                    else f"Version {version} is available (installed: {update['current_version']})."
                ),
                poster_url=None,
                event_at=now,
                dedupe_key=dedupe_key,
            )
        )


@router.post("/updates/check")
async def check_plugin_updates(
    admin: User = Depends(get_plugin_manager_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates: list[dict[str, Any]] = []
    for plugin in await _installed_plugins():
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
        manager_state().patch(str(plugin["plugin_id"]), available_update=update)
        await _notify_plugin_update(db, update)
    await db.commit()
    return {
        "updates": updates,
        "available": sum(bool(item.get("update_available")) for item in updates),
        "checked_at": int(time.time()),
    }


async def _installed_plugins() -> list[dict[str, Any]]:
    store = manager_state()
    try:
        return store.reconcile(await _client.plugins())
    except (PluginRuntimeRequestError, PluginRuntimeUnavailable) as exc:
        return [
            {
                **item,
                "runtime_available": False,
                "status": "unknown",
                "health": "unknown",
                "runtime_error": str(exc),
                "runtime": {
                    **item.get("runtime", {}),
                    "available": False,
                    "mechanism": "unavailable",
                    "sandbox_available": False,
                    "bubblewrap_available": None,
                    "last_error": str(exc),
                },
            }
            for item in store.read()["plugins"].values()
        ]


class ManagerSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    automatic_updates: bool | None = None
    retained_versions: int | None = Field(default=None, ge=1, le=100)


class AutoUpdateIn(BaseModel):
    mode: str = Field(pattern=r"^(follow|enabled|disabled)$")


class PackageOperationIn(BaseModel):
    expected_digest: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    approved_permissions: list[str] = Field(default_factory=list)
    allow_untrusted: bool = False
    confirm_dangerous: bool = False
    admin_password: str | None = None
    purge: bool = False
    confirmed: bool = False
    history_id: UUID | None = None


@router.get("/manager-settings")
async def get_manager_settings(admin: User = Depends(get_plugin_manager_admin)) -> dict:
    del admin
    return manager_state().settings()


@router.put("/manager-settings")
async def save_manager_settings(
    payload: ManagerSettingsIn, admin: User = Depends(get_plugin_manager_admin)
) -> dict:
    del admin
    settings = manager_state().settings(payload.model_dump(exclude_none=True))
    for plugin in await _client.plugins():
        await _client.prune_history(plugin["plugin_id"], settings["retained_versions"])
    return settings


@router.put("/{plugin_id}/auto-update")
async def set_plugin_auto_update(
    plugin_id: str, payload: AutoUpdateIn, admin: User = Depends(get_plugin_manager_admin)
) -> dict:
    del admin
    if plugin_id not in manager_state().read()["plugins"]:
        raise HTTPException(404, "Plugin installation not found.")
    return manager_state().patch(plugin_id, automatic_updates=payload.mode)


@router.post("/{plugin_id}/update/staged/preview")
async def preview_staged_update(
    plugin_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_plugin_manager_admin),
) -> dict:
    del admin
    path = manager_state().stage_path(plugin_id)
    if not path.is_file():
        raise HTTPException(404, "No staged package.")
    inspected = _inspect_install_candidate(path)
    installed, _, delta, dependencies, retain = await _update_context(plugin_id, inspected, db)
    return _update_preview(inspected, installed, delta, dependencies, can_retain_grants=retain)


@router.post("/{plugin_id}/update/staged")
async def activate_staged_update(
    plugin_id: str,
    payload: PackageOperationIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_plugin_manager_admin),
) -> dict:
    path = manager_state().stage_path(plugin_id)
    if not path.is_file():
        raise HTTPException(404, "No staged package.")
    record = manager_state().read()["plugins"].get(plugin_id, {})
    if payload.expected_digest:
        inspected = _inspect_install_candidate(path)
        if inspected.package.manifest.integrity.sha256 != payload.expected_digest:
            raise HTTPException(409, "Staged package changed; review its permissions again.")
    if payload.confirmed and not payload.approved_permissions:
        manager_state().patch(
            plugin_id, staged_update={**record.get("staged_update", {}), "status": "denied"}
        )
        return {"plugin_id": plugin_id, "status": "denied"}
    return await _perform_package_operation(
        plugin_id,
        path.read_bytes(),
        payload,
        admin,
        db,
        source=record.get("staged_update", {}).get("source"),
    )


async def _perform_package_operation(
    plugin_id: str,
    package: bytes,
    payload: PackageOperationIn,
    admin: User,
    db: AsyncSession,
    *,
    operation: str = "update",
    source: dict | None = None,
) -> dict:
    try:
        return await _plugin_installer().install(
            package,
            consent=InstallationConsent(
                approved_permissions=tuple(payload.approved_permissions),
                expected_digest=payload.expected_digest,
                allow_untrusted=payload.allow_untrusted,
                confirm_dangerous=payload.confirm_dangerous,
                admin_password=payload.admin_password,
            ),
            admin=admin,
            db=db,
            update_plugin_id=plugin_id,
            operation=operation,
            source=source,
        )
    except InstallationError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post("/{plugin_id}/reinstall")
async def reinstall_plugin(
    plugin_id: str,
    payload: PackageOperationIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_plugin_manager_admin),
) -> dict:
    if payload.purge and not payload.confirmed:
        raise HTTPException(409, "Reinstall with purge requires explicit destructive confirmation.")
    package = await _client.package_archive(plugin_id)
    if payload.purge:
        await _client.purge_data(plugin_id)
        await _purge_plugin_database(db, plugin_id)
        await db.commit()
    return await _perform_package_operation(
        plugin_id, package, payload, admin, db, operation="reinstall"
    )


@router.post("/{plugin_id}/rollback")
async def rollback_plugin(
    plugin_id: str,
    payload: PackageOperationIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_plugin_manager_admin),
) -> dict:
    plugin = next(
        (item for item in await _client.plugins() if item["plugin_id"] == plugin_id), None
    )
    history = plugin.get("history", []) if plugin else []
    history_id = (
        str(payload.history_id) if payload.history_id else history[0]["id"] if history else None
    )
    if history_id is None:
        raise HTTPException(409, "No retained package version.")
    package = await _client.package_archive(plugin_id, history_id)
    return await _perform_package_operation(
        plugin_id, package, payload, admin, db, operation="rollback"
    )


@router.delete("/{plugin_id}/history/{history_id}")
async def delete_package_history(
    plugin_id: str, history_id: UUID, admin: User = Depends(get_plugin_manager_admin)
) -> dict:
    del admin
    await _client.prune_history(
        plugin_id, manager_state().settings()["retained_versions"], str(history_id)
    )
    manager_state().reconcile(await _client.plugins())
    return {"deleted": True}


@router.post("/{plugin_id}/stop")
async def stop_plugin(plugin_id: str, admin: User = Depends(get_plugin_manager_admin)) -> dict:
    del admin
    await _client.stop_runtime(quote(plugin_id, safe=""))
    manager_state().reconcile(await _client.plugins())
    return {"plugin_id": plugin_id, "status": "stopped"}


@router.post("/{plugin_id}/start")
async def start_plugin(plugin_id: str, admin: User = Depends(get_plugin_manager_admin)) -> dict:
    plugin = next(
        (item for item in await _client.plugins() if item["plugin_id"] == plugin_id), None
    )
    if not plugin or not plugin.get("enabled"):
        raise HTTPException(409, "Enable this plugin before starting it.")
    await _client.start(quote(plugin_id, safe=""), user_id=str(admin.id))
    manager_state().reconcile(await _client.plugins())
    return {"plugin_id": plugin_id, "status": "running"}


class ManagementTokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str]


@router.post("/management/tokens", status_code=201)
async def create_management_token(
    payload: ManagementTokenIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict:
    if not payload.scopes or not set(payload.scopes).issubset(MANAGEMENT_SCOPES):
        raise HTTPException(422, "Choose only plugin management scopes.")
    token = MANAGEMENT_PREFIX + secrets.token_urlsafe(32)
    row = UserApiKey(
        user_id=admin.id,
        name=payload.name,
        key_prefix=token[:12],
        key_hash=hash_token(token),
        scopes=sorted(set(payload.scopes)),
    )
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "token": token, "scopes": row.scopes}


@router.delete("/management/tokens/{token_id}")
async def revoke_management_token(
    token_id: UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)
) -> dict:
    del admin
    row = await db.scalar(
        select(UserApiKey).where(
            UserApiKey.id == token_id, UserApiKey.key_prefix.startswith(MANAGEMENT_PREFIX)
        )
    )
    if row is None:
        raise HTTPException(404, "Plugin management token not found.")
    row.revoked_at = int(time.time())
    await db.commit()
    return {"revoked": True}


async def _purge_plugin_database(db: AsyncSession, plugin_id: str) -> None:
    from src.database.models.plugin_permissions import PluginLifecycleTransaction
    from src.database.models.media_provider import MediaProviderLink

    for model in (
        MediaProviderLink,
        PluginLifecycleTransaction,
        PluginPermissionGrant,
        PluginPermissionRequest,
        PluginClientIdentity,
        PluginNotificationProviderRegistration,
    ):
        await db.execute(delete(model).where(model.plugin_id == plugin_id))


async def run_automatic_plugin_updates(db: AsyncSession, admin: User) -> dict[str, int]:
    """Discover, validate and stage releases, then apply policy without granting scopes."""
    counts = {"checked": 0, "installed": 0, "staged": 0, "failed": 0}
    store = manager_state()
    for plugin in await _installed_plugins():
        source = plugin.get("source", {})
        if source.get("type") != "catalogue":
            continue
        configured = next(
            (
                item
                for item in _catalogue_store().list()
                if item["url"] == source.get("catalogue_url") and item["enabled"]
            ),
            None,
        )
        if configured is None:
            continue
        counts["checked"] += 1
        path = None
        try:
            update = await _check_plugin_update(plugin, admin)
            store.patch(plugin["plugin_id"], available_update=update)
            if not update.get("update_available"):
                continue
            await _notify_plugin_update(db, update)
            path, _, _ = await _download_remote_file(update["url"])
            if (
                update.get("package_sha256")
                and hashlib.sha256(path.read_bytes()).hexdigest()
                != update["package_sha256"].lower()
            ):
                raise ValueError("Catalogue archive hash differs.")
            inspected = _inspect_install_candidate(path)
            manifest = inspected.package.manifest
            if (
                manifest.plugin_id != plugin["plugin_id"]
                or manifest.version != update["available_version"]
            ):
                raise ValueError("Catalogue release and package identity differ.")
            if update.get("digest") and update["digest"] != manifest.integrity.sha256:
                raise ValueError("Catalogue package digest differs.")
            plan = await _plugin_installer().plan_update(plugin["plugin_id"], inspected, db)
            mode = plugin.get("automatic_updates", "follow")
            enabled = (
                mode == "enabled" or mode == "follow" and store.settings()["automatic_updates"]
            )
            eligible = (
                enabled
                and update["automatic_update"]
                and manifest.automatic_update
                and inspected.package.distribution.get("automatic_update", True)
                and inspected.trust.is_verified
                and plan.dependencies.ready
                and not plan.permissions.newly_requested_grants
            )
            previous_stage = store.read()["plugins"][plugin["plugin_id"]].get("staged_update") or {}
            denied = (
                previous_stage.get("status") == "denied"
                and previous_stage.get("digest") == manifest.integrity.sha256
                and (previous_stage.get("version") or previous_stage.get("available_version"))
                == manifest.version
            )
            eligible = eligible and not denied
            stage = {
                **update,
                "digest": manifest.integrity.sha256,
                "status": "denied"
                if denied
                else (
                    "awaiting_permissions"
                    if plan.permissions.newly_requested_grants
                    else "downloaded"
                ),
            }
            store.stage(plugin["plugin_id"], path.read_bytes(), stage)
            counts["staged"] += 1
            if eligible:
                result = await _plugin_installer().install(
                    path.read_bytes(),
                    consent=InstallationConsent(),
                    admin=admin,
                    db=db,
                    update_plugin_id=plugin["plugin_id"],
                    source=source,
                )
                if result["status"] == "rolled_back":
                    counts["failed"] += 1
                    await _notify_plugin_update(db, update, failed=True)
                else:
                    counts["installed"] += 1
        except Exception as exc:
            await db.rollback()
            counts["failed"] += 1
            store.patch(plugin["plugin_id"], last_update_error=str(exc))
            logger.warning(
                "Plugin automatic update failed: plugin_id=%s error=%s", plugin["plugin_id"], exc
            )
            failure = store.read()["plugins"][plugin["plugin_id"]].get("available_update")
            if failure and failure.get("update_available"):
                await _notify_plugin_update(db, failure, failed=True)
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
    await db.commit()
    return counts


@router.post("/{plugin_id}/permissions/grant")
async def grant_plugin_permissions(
    plugin_id: str,
    payload: PackageOperationIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_plugin_manager_admin),
) -> dict:
    """Explicitly re-grant declared permissions without replacing package or data."""
    from src.plugin_api.capabilities import calculate_permission_delta
    from src.plugin_api.installer import InstallationPlan

    inspected = await asyncio.to_thread(
        _plugin_installer()._inspect_snapshot, await _client.package_archive(plugin_id)
    )
    manifest = inspected.package.manifest
    requested = set(payload.approved_permissions)
    if payload.expected_digest and manifest.integrity.sha256 != payload.expected_digest:
        raise HTTPException(409, "Active package changed; review its permissions again.")
    refs = tuple(
        p.capability
        for p in manifest.permissions
        if _permission_key(p.capability.name.value, p.capability.version) in requested
    )
    if len(refs) != len(requested):
        raise HTTPException(422, "Grant only permissions declared by the active package.")
    plugin = next(item for item in await _client.plugins() if item["plugin_id"] == plugin_id)
    installation_id = UUID(plugin["installation_id"])
    plan = InstallationPlan(
        inspected,
        installation_id,
        plan_dependencies(manifest, await _client.plugins()),
        calculate_permission_delta((), refs, ()),
    )
    try:
        _plugin_installer().confirm(
            plan,
            InstallationConsent(
                allow_untrusted=payload.allow_untrusted,
                approved_permissions=tuple(requested),
                confirm_dangerous=payload.confirm_dangerous,
                admin_password=payload.admin_password,
            ),
            admin,
        )
    except InstallationError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    for ref in refs:
        db.add(
            PluginPermissionGrant(
                plugin_id=plugin_id,
                installation_id=installation_id,
                capability=ref.name.value,
                capability_version=ref.version,
            )
        )
        db.add(
            PluginPermissionAudit(
                plugin_id=plugin_id,
                installation_id=installation_id,
                capability=ref.name.value,
                capability_version=ref.version,
                user_id=admin.id,
                decision="allowed",
                reason="administrator explicit permission re-grant",
            )
        )
    await db.commit()
    return {"granted": sorted(requested)}


@router.post("/{plugin_id}/permissions/preview")
async def preview_plugin_permissions(
    plugin_id: str, admin: User = Depends(get_plugin_manager_admin)
) -> dict:
    del admin
    inspected = await asyncio.to_thread(
        _plugin_installer()._inspect_snapshot, await _client.package_archive(plugin_id)
    )
    return _install_preview(inspected)


@router.get("/{plugin_id}/changelog")
async def plugin_changelog(
    plugin_id: str,
    admin: User = Depends(get_plugin_manager_admin),
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
    from src.plugin_api.grants import effective_capabilities

    return plugin, await effective_capabilities(db, plugin_id, installation_id, user.id, granted)


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
            "document_readers": (
                document.document_readers
                if permitted(Capability.FRONTEND_CONTEXT_DOCUMENTS)
                and permitted(Capability.DOCUMENTS_READ)
                else ()
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
    user: User = Depends(get_plugin_manager_reader),
) -> list[dict]:
    from src.plugin_api.grants import effective_capabilities

    plugins = await _installed_plugins()
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
                "permission_details": [
                    _permission_preview(PermissionDeclaration.model_validate(item))
                    for item in plugin.get("permission_declarations", [])
                ],
                "granted_capabilities": sorted(set(granted)),
                "effective_capabilities": (
                    sorted(
                        await effective_capabilities(
                            db,
                            str(plugin["plugin_id"]),
                            UUID(str(installation_id)),
                            user.id,
                            granted,
                        )
                    )
                    if installation_id and installation_is_executable(plugin)
                    else []
                ),
            }
        )
    return sorted(result, key=lambda value: value["plugin_id"])


@router.delete("/{plugin_id}", status_code=204)
async def delete_plugin(
    plugin_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_plugin_manager_admin),
) -> Response:
    del admin
    try:
        await _client.delete(quote(plugin_id, safe=""))
    except PluginRuntimeRequestError as exc:
        raise _runtime_request_error(exc) from exc
    except PluginRuntimeUnavailable as exc:
        raise _runtime_error(exc) from exc
    await _purge_plugin_database(db, plugin_id)
    await db.commit()
    manager_state().remove(plugin_id)
    return Response(status_code=204)


@router.post("/{plugin_id}/enable")
async def enable_plugin(
    plugin_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_plugin_manager_admin),
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
async def disable_plugin(plugin_id: str, admin: User = Depends(get_plugin_manager_admin)) -> dict:
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
    operation: str = "update",
) -> tuple[dict[str, Any], UUID, Any, DependencyPlan, bool]:
    try:
        plan = await _plugin_installer().plan_update(plugin_id, inspected, db, operation=operation)
    except InstallationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    assert plan.installed is not None
    return (
        plan.installed,
        plan.installation_id,
        plan.permissions,
        plan.dependencies,
        plan.can_retain_grants,
    )


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
                inspected.package.distribution.get("release_notes")
                or (
                    source.get("release_notes")
                    if isinstance(source, dict)
                    else installed.get("source", {}).get("release_notes")
                    if isinstance(installed.get("source"), dict)
                    else None
                )
            ),
        }
    )
    return preview


@router.put("/{plugin_id}/update/preview")
async def preview_plugin_update(
    plugin_id: str,
    file: UploadFile = File(...),
    admin: User = Depends(get_plugin_manager_admin),
    db: AsyncSession = Depends(get_db),
    operation: Literal["update", "replace"] = "update",
) -> dict[str, Any]:
    del admin
    temporary_path: Path | None = None
    try:
        temporary_path, _, _ = await _store_plugin_upload(file, "plugin-update-preview-")
        inspected = _inspect_install_candidate(temporary_path)
        installed, _, permission_delta, dependencies, can_retain_grants = await _update_context(
            plugin_id, inspected, db, operation=operation
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
    admin: User = Depends(get_plugin_manager_admin),
    db: AsyncSession = Depends(get_db),
    operation: Literal["update", "replace"] = "update",
) -> dict[str, Any]:
    temporary_path: Path | None = None
    try:
        temporary_path, filename, total = await _download_remote_file(request.url)
        inspected = _inspect_install_candidate(temporary_path)
        await _validate_catalogue_candidate(temporary_path, inspected, request, admin)
        installed, _, permission_delta, dependencies, can_retain_grants = await _update_context(
            plugin_id,
            inspected,
            db,
            operation=operation,
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
    admin: User = Depends(get_plugin_manager_admin),
    db: AsyncSession = Depends(get_db),
    operation: Literal["update", "replace"] = "update",
) -> dict[str, Any]:
    temporary_path: Path | None = None
    upload: UploadFile | None = None
    try:
        temporary_path, filename, _ = await _download_remote_file(request.url)
        inspected = _inspect_install_candidate(temporary_path)
        await _validate_catalogue_candidate(temporary_path, inspected, request, admin)
        upload = UploadFile(temporary_path.open("rb"), filename=filename)
        return await _update_plugin_package(
            plugin_id,
            upload,
            operation=operation,
            allow_untrusted=allow_untrusted,
            approved_permissions=approved_permissions,
            admin_password=request.admin_password,
            confirm_dangerous=request.confirm_dangerous,
            expected_digest=request.expected_digest,
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
    admin_password: str | None = Form(default=None),
    confirm_dangerous: bool = Query(default=False),
    admin: User = Depends(get_plugin_manager_admin),
    db: AsyncSession = Depends(get_db),
    operation: Literal["update", "replace"] = "update",
) -> dict[str, Any]:
    return await _update_plugin_package(
        plugin_id,
        file,
        operation=operation,
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
    expected_digest: str | None = None,
    operation: str = "update",
) -> dict[str, Any]:
    return await _commit_plugin_upload(
        file,
        consent=InstallationConsent(
            allow_untrusted=allow_untrusted,
            approved_permissions=tuple(approved_permissions)
            if isinstance(approved_permissions, list)
            else (),
            admin_password=admin_password,
            confirm_dangerous=confirm_dangerous,
            expected_digest=expected_digest,
        ),
        source_metadata=source_metadata,
        admin=admin,
        db=db,
        plugin_id=plugin_id,
        operation=operation,
    )


@router.post("/{plugin_id}/retry")
async def retry_plugin(plugin_id: str, admin: User = Depends(get_plugin_manager_admin)) -> dict:
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
    admin: User = Depends(get_plugin_manager_admin),
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
    admin: User = Depends(get_plugin_manager_admin),
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
    media_type = {".css": "text/css", ".js": "text/javascript", ".html": "text/html"}.get(
        Path(asset_path).suffix.lower(),
        mimetypes.guess_type(asset_path)[0] or "application/octet-stream",
    )
    csp = _PLUGIN_FRONTEND_CSP
    if media_type == "text/html":
        try:
            ui = await _client.plugin_ui(quote(plugin_id, safe=""))
        except PluginRuntimeRequestError as exc:
            raise _runtime_request_error(exc) from exc
        except PluginRuntimeUnavailable as exc:
            raise _runtime_error(exc) from exc
        frontend = ui.get("frontend", {})
        if frontend.get("inline_assets") is True and frontend.get("entry") == asset_path:
            nonce = secrets.token_urlsafe(24)

            async def load_asset(path: str) -> bytes:
                return await _client.frontend_asset(quote(plugin_id, safe=""), path)

            try:
                content = await inline_frontend_assets(content, asset_path, nonce, load_asset)
            except (ValueError, PluginRuntimeRequestError) as exc:
                raise HTTPException(422, "Invalid packaged frontend assets.") from exc
            except PluginRuntimeUnavailable as exc:
                raise _runtime_error(exc) from exc
            csp = csp.replace("script-src 'self'", f"script-src 'nonce-{nonce}' 'self'")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Security-Policy": csp,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.api_route(
    "/{plugin_id}/capabilities/documents/{document_id}/download", methods=["GET", "HEAD"]
)
async def plugin_document_download(
    plugin_id: str,
    document_id: UUID,
    db: AsyncSession = _PLUGIN_DB,
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Stream an owned original as an attachment, including unsupported preview types."""
    _, capabilities = await _plugin_and_capabilities(plugin_id, db, user)
    if "documents.read" not in capabilities:
        raise HTTPException(403, "Permission documents.read has not been granted.")
    row = await owned_document(db, user.id, document_id)
    if row is None:
        raise HTTPException(404, "Document not found.")
    item, game = row
    try:
        path = document_path(_DOCUMENT_DATA_ROOT, user.id, game.folder_location, item.filename)
    except DocumentAccessError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return FileResponse(
        path,
        filename=item.filename.split("_", 1)[-1],
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
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
    _, capabilities = await _plugin_and_capabilities(plugin_id, db, user)
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


async def _current_browser_session_id(
    db: AsyncSession, user_id: UUID, request: Request
) -> str | None:
    """Resolve a non-secret session identifier from authenticated host cookies."""
    token = request.cookies.get("session")
    if not token:
        return None
    session_id = await db.scalar(
        select(UserSession.id).where(
            UserSession.user_id == user_id,
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > int(time.time()),
        )
    )
    return str(session_id) if session_id else None


@router.post("/{plugin_id}/capabilities/sessions/geoip")
async def plugin_geoip_upload(
    plugin_id: str,
    *,
    file: UploadFile = _GEOIP_UPLOAD_FILE,
    kind: str = Query(default="city", pattern="^(city|country|network)$"),
    confirmed: bool = Query(default=False),
    db: AsyncSession = _PLUGIN_DB,
    admin: User = _PLUGIN_ADMIN,
) -> dict[str, object]:
    """Allow enabled plugins with a narrow grant to replace a local GeoIP database."""
    plugin = await _live_plugin(plugin_id)
    if not await has_capability_grant(
        db,
        plugin_id=plugin_id,
        installation_id=UUID(str(plugin["installation_id"])),
        capability="sessions.geoip.configure",
        user_id=admin.id,
    ):
        raise HTTPException(403, "Permission sessions.geoip.configure has not been granted.")
    if not confirmed:
        raise HTTPException(409, "Explicit GeoIP replacement confirmation is required.")
    result = await upload_geoip(file=file, kind=kind, admin=admin)
    return {"configured": result["configured"], "kind": kind}


@router.post("/{plugin_id}/actions/{action_id}", dependencies=[Depends(_private_plugin_response)])
async def plugin_action(
    plugin_id: str,
    action_id: str,
    payload: PluginActionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    *,
    request: Request,
) -> dict:
    """Authorize a declared action and supply host-owned authentication context."""
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
    if action.get("confirmation") and getattr(payload, "confirmed", False) is not True:
        raise HTTPException(status_code=409, detail="Explicit action confirmation is required.")
    values = dict(payload.values)
    values.pop("_plugin_context", None)
    context: dict[str, Any] = {
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
    context["confirmed"] = getattr(payload, "confirmed", False)
    context["is_admin"] = bool(getattr(user, "is_admin", False))
    session_id = await _current_browser_session_id(db, user.id, request)
    if session_id:
        context["session_id"] = session_id
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
    api_version: str = Field(default="v1", min_length=1, max_length=16)
    plugin_id: str
    installation_id: UUID
    request_id: UUID
    user_id: UUID
    method: str
    capability: str
    capability_version: int = Field(default=1, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/runtime/gateway", dependencies=[Depends(_private_plugin_response)], response_model=None
)
async def plugin_gateway(
    payload: PluginGatewayIn,
    db: AsyncSession = Depends(get_db),
    runtime_token: str | None = Header(default=None, alias="X-Plugin-Runtime-Token"),
) -> dict[str, Any] | JSONResponse:
    def failure(status: int, code: ErrorCode, message: str) -> JSONResponse:
        envelope = ErrorEnvelope(code=code, message=message[:1024], request_id=payload.request_id)
        response = JSONResponse(
            status_code=status,
            content={"detail": message, "error": envelope.model_dump(mode="json")},
        )
        _private_plugin_response(response)
        return response

    if not runtime_token_is_valid(runtime_token):
        return failure(503, ErrorCode.UNAVAILABLE, "Plugin runtime gateway is not configured.")
    if payload.api_version != "v1":
        return failure(
            409, ErrorCode.INCOMPATIBLE, "Unsupported Plugin API version; supported: v1."
        )
    try:
        plugin = await _live_plugin(payload.plugin_id, require_enabled=False)
    except HTTPException as exc:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.UNAVAILABLE
        return failure(exc.status_code, code, str(exc.detail))
    starting_authorization = (
        payload.method == "capabilities.check"
        and plugin.get("enabled") is True
        and plugin.get("compatible") is True
        and plugin.get("status") == "starting"
        and plugin.get("health") in {"healthy", "unknown"}
    )
    if not installation_is_executable(plugin) and not starting_authorization:
        return failure(409, ErrorCode.CONFLICT, "Plugin installation is not executable.")
    if UUID(str(plugin["installation_id"])) != payload.installation_id:
        return failure(409, ErrorCode.CONFLICT, "Plugin installation identity does not match.")
    user = await db.scalar(select(User).where(User.id == payload.user_id, User.is_active.is_(True)))
    if user is None:
        return failure(403, ErrorCode.FORBIDDEN, "Active user context is required.")
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
        # Complete before the runtime bridge's ten-second transport deadline.
        async with asyncio.timeout(_GATEWAY_DISPATCH_TIMEOUT):
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
        return failure(403, ErrorCode.FORBIDDEN, str(exc))
    except (ValueError, LookupError) as exc:
        return failure(422, ErrorCode.INVALID_REQUEST, str(exc))
    except TimeoutError:
        return failure(504, ErrorCode.UNAVAILABLE, "Plugin gateway operation timed out.")
    except Exception:
        logger.exception("Plugin gateway failure: request_id=%s", payload.request_id)
        return failure(500, ErrorCode.INTERNAL, "Plugin gateway operation failed.")
    return {"api_version": "v1", "request_id": str(payload.request_id), "payload": result}


@router.get("/runtime/health")
async def runtime_health(admin: User = Depends(get_plugin_manager_admin)) -> dict:
    del admin
    try:
        return await _client.health()
    except PluginRuntimeUnavailable as exc:
        return {
            "available": False,
            "bubblewrap_available": None,
            "sandbox_available": False,
            "mechanism": "unavailable",
            "last_error": str(exc),
        }


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


def _route_installation(resolved: ResolvedBackendRoute, request_id: UUID) -> tuple[str, UUID]:
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
    db: AsyncSession,
) -> PluginBackendRouteResponse:
    """Execute one bounded runtime handler and validate its JSON response."""

    route_request = await _backend_route_request(request, resolved.path_parameters, request_id)
    route_request["current_session_id"] = await _current_browser_session_id(db, user.id, request)
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
        db=db,
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
    return JSONResponse(
        status_code=result.status_code,
        content=result.body,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


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
