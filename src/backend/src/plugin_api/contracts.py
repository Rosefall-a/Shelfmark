"""Versioned, implementation-independent Plugin API v1 contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION = "v1"
Timestamp = datetime


class ContractModel(BaseModel):
    """Base model for public wire contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ApiVersion(StrEnum):
    """Major API versions understood by the gateway."""

    V1 = "v1"


class Capability(StrEnum):
    """Stable capability identifiers grouped by capability family."""

    USERS_READ = "users.read"
    USERS_PROFILE_READ = "users.profile.read"
    GAMES_READ = "games.read"
    GAMES_WRITE = "games.write"
    MEDIA_READ = "media.read"
    MEDIA_WRITE = "media.write"
    NOTIFICATIONS_SEND = "notifications.send"
    EVENTS_SUBSCRIBE = "events.subscribe"
    PLUGIN_STORAGE = "plugin.storage"
    PLUGIN_SETTINGS = "plugin.settings"


class CapabilityRef(ContractModel):
    """A capability plus the version of its semantics."""

    name: Capability
    version: int = Field(default=1, ge=1)


class VersionNegotiationRequest(ContractModel):
    """Versions a caller can speak, in preference order."""

    supported_versions: tuple[ApiVersion, ...] = Field(min_length=1)


class VersionNegotiationResponse(ContractModel):
    """Version selected by the gateway."""

    selected_version: ApiVersion
    deprecated: bool = False


class PluginIdentity(ContractModel):
    """Stable identity of an installed plugin."""

    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    installation_id: UUID
    version: str = Field(min_length=1, max_length=64)


class UserRepresentation(ContractModel):
    """Stable, non-sensitive user representation for plugin DTOs."""

    id: UUID
    username: str = Field(min_length=1, max_length=255)


class GameRepresentation(ContractModel):
    """Stable game representation exposed by plugin-facing DTOs."""

    id: UUID
    title: str = Field(min_length=1, max_length=512)


class MediaRepresentation(ContractModel):
    """Stable media representation exposed by plugin-facing DTOs."""

    id: UUID
    title: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=64)


class UserContext(ContractModel):
    """The minimum authenticated user context carried by a request."""

    user_id: UUID
    authenticated: bool = True


class RequestContext(ContractModel):
    """Identity and authorization context attached to a gateway request."""

    request_id: UUID
    application_id: UUID
    plugin: PluginIdentity
    user: UserContext | None = None
    requested_capability: CapabilityRef


class ErrorCode(StrEnum):
    """Stable machine-readable API error categories."""

    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


class ErrorDetail(ContractModel):
    """Safe structured validation/detail information."""

    field: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=1024)
    code: str | None = Field(default=None, max_length=128)


class ErrorEnvelope(ContractModel):
    """Stable error response without internal exception details."""

    api_version: ApiVersion = ApiVersion.V1
    code: ErrorCode
    message: str = Field(min_length=1, max_length=1024)
    request_id: UUID
    details: tuple[ErrorDetail, ...] = ()


class Pagination(ContractModel):
    """Cursor pagination shared by list endpoints."""

    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=512)


ItemT = TypeVar("ItemT")


class Page(ContractModel, Generic[ItemT]):
    """A page of stable DTOs without query/database state."""

    items: tuple[ItemT, ...]
    next_cursor: str | None = Field(default=None, max_length=512)


class EventEnvelope(ContractModel, Generic[ItemT]):
    """Versioned event delivered across the plugin boundary."""

    api_version: ApiVersion = ApiVersion.V1
    event_id: UUID
    event_type: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    event_version: int = Field(ge=1)
    occurred_at: Timestamp
    source: str = Field(min_length=1, max_length=128)
    user_id: UUID | None = None
    payload: ItemT

    @field_validator("occurred_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        """Require an explicit timezone and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)


class EventSubscription(ContractModel):
    """Filter for events a plugin is authorized to receive."""

    event_types: tuple[str, ...] = ()
    user_ids: tuple[UUID, ...] = ()
    max_events_per_minute: int = Field(default=60, ge=1, le=10_000)


class EventAck(ContractModel):
    """Acknowledgement of one delivered event."""

    event_id: UUID
    accepted: bool
    error: ErrorEnvelope | None = None


class JsonValue(ContractModel):
    """Explicit wrapper for plugin-owned structured values."""

    value: dict[str, Any]


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_semver(value: str) -> tuple[int, int, int]:
    """Parse a strict semantic version."""
    match = SEMVER_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())


def _validate_range_part(part: str) -> None:
    """Validate one AND-separated semantic-version range expression."""
    expression = part.strip()
    if expression in {"", "*"}:
        return
    if expression.startswith("^") or expression.startswith("~"):
        parse_semver(expression[1:])
        return
    operator = next((op for op in (">=", "<=", ">", "<", "=") if expression.startswith(op)), "")
    version = expression[len(operator):] if operator else expression
    if version.endswith((".x", ".*")):
        prefix = version[:-2]
        if prefix and any(not item.isdigit() for item in prefix.split(".")):
            raise ValueError(f"invalid semantic version range: {part!r}")
        if not prefix:
            raise ValueError(f"invalid semantic version range: {part!r}")
        return
    parse_semver(version)


def validate_version_range(value: str) -> str:
    """Validate a deterministic, dependency-safe semantic version range."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("version range must not be empty")
    for part in normalized.split(","):
        _validate_range_part(part)
    return normalized


def _satisfies_constraint(version: tuple[int, int, int], constraint: str) -> bool:
    expression = constraint.strip()
    if expression in {"", "*"}:
        return True
    if expression.startswith("^"):
        lower = parse_semver(expression[1:])
        if lower[0] > 0:
            upper = (lower[0] + 1, 0, 0)
        elif lower[1] > 0:
            upper = (0, lower[1] + 1, 0)
        else:
            upper = (0, 0, lower[2] + 1)
        return lower <= version < upper
    if expression.startswith("~"):
        lower = parse_semver(expression[1:])
        return lower <= version < (lower[0], lower[1] + 1, 0)

    operator = next((op for op in (">=", "<=", ">", "<", "=") if expression.startswith(op)), "")
    value = expression[len(operator):] if operator else expression
    if value.endswith((".x", ".*")):
        parts = value[:-2].split(".")
        prefix = tuple(int(item) for item in parts)
        return version[:len(prefix)] == prefix
    target = parse_semver(value)
    return {
        "": version == target,
        "=": version == target,
        ">=": version >= target,
        "<=": version <= target,
        ">": version > target,
        "<": version < target,
    }[operator]


def version_satisfies(version: str, version_range: str) -> bool:
    """Return whether a semantic version satisfies every range constraint."""
    parsed = parse_semver(version)
    validate_version_range(version_range)
    return all(_satisfies_constraint(parsed, part) for part in version_range.split(","))


class PermissionDeclaration(ContractModel):
    """A human-readable permission request tied to a capability."""

    capability: CapabilityRef
    rationale: str = Field(min_length=1, max_length=1024)


class PluginDependency(ContractModel):
    """A required or optional dependency on another installed plugin."""

    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version_range: str
    optional: bool = False

    @field_validator("version_range")
    @classmethod
    def validate_dependency_range(cls, value: str) -> str:
        return validate_version_range(value)


class PluginUiDeclaration(ContractModel):
    """Declarative identifiers exposed to the native frontend."""

    settings: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    pages: tuple[str, ...] = ()
    menus: tuple[str, ...] = ()


class StorageRequirements(ContractModel):
    """Plugin-owned storage requirements; quotas never grant core DB access."""

    quota_mb: int | None = Field(default=None, ge=1, le=1_048_576)


class IntegrityMetadata(ContractModel):
    """Package integrity metadata validated before plugin activation."""

    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    signature: str | None = Field(default=None, min_length=1, max_length=16_384)
    key_id: str | None = Field(default=None, min_length=1, max_length=256)


class PluginManifest(ContractModel):
    """Static plugin manifest validated without importing or executing the plugin."""

    manifest_version: int = Field(default=1, ge=1, le=1)
    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=128)
    version: str
    description: str = Field(default="", max_length=2_000)
    entrypoint: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*(?::[A-Za-z_][A-Za-z0-9_]*)?$",
    )
    sdk_version_range: str
    application_version_range: str
    capabilities: tuple[CapabilityRef, ...] = ()
    permissions: tuple[PermissionDeclaration, ...] = ()
    dependencies: tuple[PluginDependency, ...] = ()
    ui: PluginUiDeclaration = PluginUiDeclaration()
    storage: StorageRequirements = StorageRequirements()
    integrity: IntegrityMetadata

    @field_validator("version")
    @classmethod
    def validate_plugin_version(cls, value: str) -> str:
        parse_semver(value)
        return value

    @field_validator("sdk_version_range", "application_version_range")
    @classmethod
    def validate_compatibility_range(cls, value: str) -> str:
        return validate_version_range(value)

    @model_validator(mode="after")
    def validate_unique_declarations(self) -> "PluginManifest":
        dependency_ids = [dependency.plugin_id for dependency in self.dependencies]
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError("manifest contains duplicate dependency declarations")
        capability_names = [capability.name for capability in self.capabilities]
        if len(capability_names) != len(set(capability_names)):
            raise ValueError("manifest contains duplicate capability declarations")
        permission_names = [permission.capability.name for permission in self.permissions]
        if len(permission_names) != len(set(permission_names)):
            raise ValueError("manifest contains duplicate permission declarations")
        return self


class CompatibilityStatus(StrEnum):
    """Static compatibility outcome before any plugin code is executed."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    INVALID = "invalid"


class CompatibilityDecision(ContractModel):
    """Actionable result for installation/activation decisions."""

    status: CompatibilityStatus
    reason: str
    action: str


def evaluate_manifest_compatibility(
    manifest: PluginManifest,
    sdk_version: str,
    application_version: str,
) -> CompatibilityDecision:
    """Classify a manifest without executing plugin code."""
    try:
        sdk_ok = version_satisfies(sdk_version, manifest.sdk_version_range)
        app_ok = version_satisfies(application_version, manifest.application_version_range)
    except ValueError as exc:
        return CompatibilityDecision(
            status=CompatibilityStatus.INVALID,
            reason=str(exc),
            action="reject",
        )
    if not sdk_ok:
        return CompatibilityDecision(
            status=CompatibilityStatus.INCOMPATIBLE,
            reason="plugin SDK version is outside the declared compatibility range",
            action="quarantine",
        )
    if not app_ok:
        return CompatibilityDecision(
            status=CompatibilityStatus.INCOMPATIBLE,
            reason="application version is outside the declared compatibility range",
            action="quarantine",
        )
    return CompatibilityDecision(
        status=CompatibilityStatus.COMPATIBLE,
        reason="manifest is compatible with the current SDK and application",
        action="allow",
    )


def migrate_manifest_data(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate the known legacy manifest shape to manifest version 1.

    This is a pure data migration. It never imports, loads, or executes plugin code.
    Unknown/ambiguous legacy values are rejected rather than guessed.
    """
    migrated = dict(data)
    version = migrated.get("manifest_version", 0)
    if version == 1:
        return migrated
    if version not in {0, None}:
        raise ValueError(f"unsupported manifest version: {version!r}")

    aliases = {
        "id": "plugin_id",
        "display_name": "name",
        "entry_point": "entrypoint",
        "sdk_version": "sdk_version_range",
        "app_version": "application_version_range",
    }
    for old_key, new_key in aliases.items():
        if old_key in migrated:
            if new_key in migrated:
                raise ValueError(f"ambiguous manifest fields: {old_key!r} and {new_key!r}")
            migrated[new_key] = migrated.pop(old_key)

    for key in ("sdk_version_range", "application_version_range"):
        value = migrated.get(key)
        if value is not None and SEMVER_RE.fullmatch(str(value)):
            migrated[key] = f"={value}"

    migrated["manifest_version"] = 1
    return migrated


class DependencyResolutionError(ValueError):
    """Raised when plugin dependencies cannot be resolved safely."""


def resolve_plugin_dependencies(
    manifests: tuple[PluginManifest, ...],
) -> tuple[str, ...]:
    """Return a deterministic dependency-first installation order."""
    by_id = {manifest.plugin_id: manifest for manifest in manifests}
    if len(by_id) != len(manifests):
        raise DependencyResolutionError("duplicate plugin IDs cannot be installed together")

    for manifest in manifests:
        for dependency in manifest.dependencies:
            target = by_id.get(dependency.plugin_id)
            if target is None:
                if dependency.optional:
                    continue
                raise DependencyResolutionError(
                    f"{manifest.plugin_id} requires missing plugin {dependency.plugin_id}"
                )
            if not version_satisfies(target.version, dependency.version_range):
                if dependency.optional:
                    continue
                raise DependencyResolutionError(
                    f"{manifest.plugin_id} requires {dependency.plugin_id} "
                    f"matching {dependency.version_range}, found {target.version}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []

    def visit(plugin_id: str, path: tuple[str, ...]) -> None:
        if plugin_id in visiting:
            cycle = " -> ".join((*path, plugin_id))
            raise DependencyResolutionError(f"dependency cycle detected: {cycle}")
        if plugin_id in visited:
            return
        visiting.add(plugin_id)
        manifest = by_id[plugin_id]
        dependencies = sorted(
            (
                dependency.plugin_id
                for dependency in manifest.dependencies
                if dependency.plugin_id in by_id
                and not (
                    dependency.optional
                    and not version_satisfies(
                        by_id[dependency.plugin_id].version,
                        dependency.version_range,
                    )
                )
            ),
        )
        for dependency_id in dependencies:
            visit(dependency_id, (*path, plugin_id))
        visiting.remove(plugin_id)
        visited.add(plugin_id)
        order.append(plugin_id)

    for plugin_id in sorted(by_id):
        visit(plugin_id, ())
    return tuple(order)


__all__ = [
    "API_VERSION", "ApiVersion", "Capability", "CapabilityRef", "ErrorCode",
    "ErrorDetail", "ErrorEnvelope", "EventAck", "EventEnvelope",
    "EventSubscription", "GameRepresentation", "JsonValue", "MediaRepresentation",
    "Page", "Pagination", "PluginIdentity", "RequestContext", "Timestamp",
    "UserContext", "UserRepresentation", "VersionNegotiationRequest",
    "VersionNegotiationResponse", "PermissionDeclaration", "PluginDependency",
    "PluginUiDeclaration", "StorageRequirements", "IntegrityMetadata", "PluginManifest",
    "CompatibilityStatus", "CompatibilityDecision", "evaluate_manifest_compatibility",
    "migrate_manifest_data", "DependencyResolutionError", "resolve_plugin_dependencies",
    "parse_semver", "validate_version_range", "version_satisfies",
]
