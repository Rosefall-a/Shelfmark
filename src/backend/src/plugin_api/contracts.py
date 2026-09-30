"""Versioned, implementation-independent Plugin API v1 contracts."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Generic, TypeVar, cast
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

    USERS = "users"
    USERS_READ = "users.read"
    USERS_PROFILE_READ = "users.profile.read"
    GAMES = "games"
    GAMES_READ = "games.read"
    GAMES_WRITE = "games.write"
    MEDIA = "media"
    MEDIA_READ = "media.read"
    MEDIA_WRITE = "media.write"
    DOCUMENTS = "documents"
    DOCUMENTS_READ = "documents.read"
    SESSIONS = "sessions"
    SESSIONS_READ = "sessions.read"
    SESSIONS_REVOKE = "sessions.revoke"
    SESSIONS_ADMIN = "sessions.admin"
    NOTIFICATIONS_SEND = "notifications.send"
    NOTIFICATIONS = "notifications"
    NOTIFICATION_PROVIDERS = "notification_providers"
    NOTIFICATION_PROVIDERS_REGISTER = "notification_providers.register"
    NOTIFICATION_PROVIDERS_DELIVER = "notification_providers.deliver"
    EVENTS_SUBSCRIBE = "events.subscribe"
    TASKS_BACKGROUND = "tasks.background"
    SESSIONS_ADMIN_READ = "sessions.admin.read"
    SESSIONS_ADMIN_REVOKE = "sessions.admin.revoke"
    MEDIA_IMPORT = "media.import"
    PLUGIN_STORAGE = "plugin.storage"
    PLUGIN_SETTINGS = "plugin.settings"
    FRONTEND_NAVIGATION = "frontend.navigation"
    FRONTEND_NAVIGATION_MAIN = "frontend.navigation.main"
    FRONTEND_NAVIGATION_SETTINGS = "frontend.navigation.settings"
    FRONTEND_NAVIGATION_ADMIN = "frontend.navigation.admin"
    FRONTEND_CONTEXT_GAME = "frontend.context.game"
    FRONTEND_CONTEXT_MEDIA = "frontend.context.media"
    FRONTEND_SETTINGS = "frontend.settings"
    FRONTEND_OVERLAY = "frontend.overlay"
    FRONTEND_DIALOG = "frontend.dialog"
    FRONTEND_PAGE_EXTEND = "frontend.page.extend"
    FRONTEND_PAGE_REPLACE_HOME = "frontend.page.replace.home"
    FRONTEND_PAGE_REPLACE_SETTINGS = "frontend.page.replace.settings"
    FRONTEND_ROUTES = "frontend.routes"
    FRONTEND_NATIVE = "frontend.native"
    BACKEND_ROUTES = "backend.routes"
    BACKEND_ROUTES_PLUGIN = "backend.routes.plugin"
    BACKEND_ROUTES_HOST = "backend.routes.host"
    NETWORK_OUTBOUND = "network.outbound"
    FULL_API = "api.full"


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


class PluginPackageIdentity(ContractModel):
    """Software identity used when deciding whether installation grants may continue."""

    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    publisher_key_id: str | None = Field(default=None, min_length=1, max_length=256)


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


class DocumentRepresentation(ContractModel):
    """Safe game-document metadata exposed without host filesystem paths."""

    id: UUID
    game_id: UUID
    game_title: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0)
    created_at: int = Field(ge=0)


class DocumentContentRepresentation(ContractModel):
    """Bounded document content encoded for the JSON Plugin API transport."""

    document: DocumentRepresentation
    encoding: str = Field(pattern=r"^base64$")
    content: str = Field(max_length=7_000_000)


class SessionRepresentation(ContractModel):
    """Non-sensitive user session metadata; credentials are never exposed."""

    id: UUID
    created_at: int = Field(ge=0)
    expires_at: int = Field(ge=0)
    active: bool


class NotificationProviderRegistration(ContractModel):
    """A plugin-owned provider registered with the core delivery coordinator."""

    provider_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    name: str = Field(min_length=1, max_length=128)
    action_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )


class NotificationDeliveryRepresentation(ContractModel):
    """Minimized delivery work sent from the core coordinator to a provider."""

    notification_id: UUID
    kind: str = Field(min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10_000)
    media_type: str = Field(min_length=1, max_length=32)
    media_id: UUID
    event_at: int = Field(ge=0)


class NotificationDeliveryResult(ContractModel):
    """Provider result interpreted by core-owned retry and terminal-state logic."""

    success: bool
    retryable: bool = False
    error: str | None = Field(default=None, max_length=512)


class UserContext(ContractModel):
    """The minimum authenticated user context carried by a request."""

    user_id: UUID
    authenticated: bool = True


class RequestContext(ContractModel):
    """Identity and authorization context attached to a gateway request."""

    request_id: UUID
    application_id: UUID
    gateway_id: UUID
    plugin: PluginIdentity
    user: UserContext | None = None
    device_id: UUID | None = None
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


class StorageEntry(ContractModel):
    """Stable metadata for one plugin-owned storage value."""

    key: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)


class StorageMetadata(ContractModel):
    """Stable plugin storage namespace metadata."""

    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    schema_version: int = Field(ge=1)
    quota_bytes: int = Field(ge=1)
    used_bytes: int = Field(ge=0)


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_semver(value: str) -> tuple[int, int, int]:
    """Parse a strict semantic version."""
    match = SEMVER_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid semantic version: {value!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _validate_range_part(part: str) -> None:
    """Validate one AND-separated semantic-version range expression."""
    expression = part.strip()
    if expression in {"", "*"}:
        return
    if expression.startswith("^") or expression.startswith("~"):
        parse_semver(expression[1:])
        return
    operator = next((op for op in (">=", "<=", ">", "<", "=") if expression.startswith(op)), "")
    version = expression[len(operator) :] if operator else expression
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
    value = expression[len(operator) :] if operator else expression
    if value.endswith((".x", ".*")):
        parts = value[:-2].split(".")
        prefix = tuple(int(item) for item in parts)
        return version[: len(prefix)] == prefix
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


class PluginFrontendDeclaration(ContractModel):
    """Sandboxed frontend entrypoint bundled inside the plugin package."""

    entry: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]*$",
    )


class PluginNativeFrontendDeclaration(ContractModel):
    """Privileged host-native Vue/JavaScript/CSS bundle declaration.

    Loading this bundle is intentionally reserved for the later native frontend
    implementation. Merely declaring it never grants native execution.
    """

    entry: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]*$",
    )
    styles: tuple[str, ...] = ()


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
    frontend: PluginFrontendDeclaration | None = None
    native_frontend: PluginNativeFrontendDeclaration | None = None

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
        capability_versions = {
            capability.name: capability.version for capability in self.capabilities
        }
        for permission in self.permissions:
            declared_version = capability_versions.get(permission.capability.name)
            if declared_version is None or declared_version != permission.capability.version:
                raise ValueError(
                    f"permission {permission.capability.name.value} v{permission.capability.version} "
                    "is not declared by the plugin"
                )
        if self.native_frontend is not None and Capability.FRONTEND_NATIVE not in capability_names:
            raise ValueError("native_frontend requires the frontend.native capability")
        return self


class UiSchemaVersion(StrEnum):
    """Versioned declarative UI schema semantics."""

    V1 = "v1"


class UiFieldType(StrEnum):
    """Native field controls supported by the v1 renderer."""

    TEXT = "text"
    TEXTAREA = "textarea"
    PASSWORD = "password"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"
    MULTISELECT = "multiselect"


class UiValidation(ContractModel):
    """Safe client/server validation constraints for a declarative field."""

    pattern: str | None = Field(default=None, max_length=256)
    min_length: int | None = Field(default=None, ge=0, le=10_000)
    max_length: int | None = Field(default=None, ge=0, le=10_000)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "UiValidation":
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("min_length cannot exceed max_length")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError("pattern must be a valid regular expression") from exc
        return self


class UiOption(ContractModel):
    """A non-executable option rendered by a select control."""

    value: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=256)


class UiField(ContractModel):
    """One declarative settings value; secrets are write-only at the host boundary."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(min_length=1, max_length=256)
    type: UiFieldType
    description: str = Field(default="", max_length=2_000)
    required: bool = False
    secret: bool = False
    default: str | int | float | bool | tuple[str, ...] | None = None
    options: tuple[UiOption, ...] = ()
    validation: UiValidation | None = None

    @model_validator(mode="after")
    def validate_options(self) -> "UiField":
        if self.type in {UiFieldType.SELECT, UiFieldType.MULTISELECT} and not self.options:
            raise ValueError("select fields require options")
        if self.type not in {UiFieldType.SELECT, UiFieldType.MULTISELECT} and self.options:
            raise ValueError("only select fields may declare options")
        option_values = [option.value for option in self.options]
        if len(option_values) != len(set(option_values)):
            raise ValueError("select fields cannot contain duplicate option values")
        if self.type is UiFieldType.PASSWORD and not self.secret:
            raise ValueError("password fields must be marked secret")
        if self.secret and self.default is not None:
            raise ValueError("secret fields cannot expose default values")
        if self.default is not None:
            expected = {
                UiFieldType.TEXT: (str,),
                UiFieldType.TEXTAREA: (str,),
                UiFieldType.PASSWORD: (str,),
                UiFieldType.NUMBER: (int, float),
                UiFieldType.BOOLEAN: (bool,),
                UiFieldType.SELECT: (str,),
                UiFieldType.MULTISELECT: (tuple,),
            }[self.type]
            if self.type is UiFieldType.NUMBER:
                valid_number = isinstance(self.default, (int, float)) and not isinstance(
                    self.default, bool
                )
                if not valid_number:
                    raise ValueError(f"default value does not match field type {self.type.value}")
            elif not isinstance(self.default, expected):
                raise ValueError(f"default value does not match field type {self.type.value}")
            if self.type is UiFieldType.MULTISELECT:
                default_values = cast(tuple[str, ...], self.default)
                if not all(isinstance(value, str) for value in default_values):
                    raise ValueError("multiselect defaults must contain only strings")
                if any(value not in option_values for value in default_values):
                    raise ValueError("default value must use declared options")
            elif self.type is UiFieldType.SELECT:
                default_value = cast(str, self.default)
                if default_value not in option_values:
                    raise ValueError("default value must use declared options")
        return self


class UiSettingsSection(ContractModel):
    """A declarative group of settings fields."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2_000)
    fields: tuple[UiField, ...] = ()

    @model_validator(mode="after")
    def validate_unique_fields(self) -> "UiSettingsSection":
        ids = [field.id for field in self.fields]
        if len(ids) != len(set(ids)):
            raise ValueError("settings section contains duplicate field IDs")
        return self


class UiAction(ContractModel):
    """A declarative action dispatched through the authenticated gateway."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(min_length=1, max_length=256)
    handler: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*(?::[A-Za-z_][A-Za-z0-9_]*)?$",
    )
    capability: CapabilityRef | None = None
    confirmation: str | None = Field(default=None, max_length=512)
    external_navigation: bool = False


class UiTableColumn(ContractModel):
    """A table column mapped to a response property, never executable code."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(min_length=1, max_length=256)


class UiTable(ContractModel):
    """A declarative read-only table."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=256)
    columns: tuple[UiTableColumn, ...] = ()
    empty_message: str = Field(default="No data available.", max_length=512)


class UiDialog(ContractModel):
    """A declarative dialog whose actions still execute through the gateway."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=4_000)
    actions: tuple[str, ...] = ()


class UiMenuItem(ContractModel):
    """A native navigation item; arbitrary external URLs are not supported."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(min_length=1, max_length=256)
    page_id: str | None = None
    action_id: str | None = None

    @model_validator(mode="after")
    def require_target(self) -> "UiMenuItem":
        if (self.page_id is None) == (self.action_id is None):
            raise ValueError("menu item must target exactly one page or action")
        return self


class HostExtensionSlot(StrEnum):
    """Host-owned locations that accept declarative plugin contributions."""

    HOME_AFTER_WIDGETS = "home.after-widgets"
    GAME_OVERVIEW_AFTER_HEADER = "game.overview.after-header"
    APP_GLOBAL = "app.global"
    HOME_REPLACE = "home.replace"


class UiNavigationLocation(StrEnum):
    """Host-owned navigation locations available to plugin contributions."""

    MAIN_SIDEBAR = "main.sidebar"
    SETTINGS_SIDEBAR = "settings.sidebar"
    ADMINISTRATION = "administration"
    GAME_CONTEXT = "game.context"
    MEDIA_CONTEXT = "media.context"


class UiContextLocation(StrEnum):
    """Host contexts that can expose a plugin action."""

    GAME = "game"
    MEDIA = "media"


class HostPage(StrEnum):
    """Host pages with explicit page-scoped replacement permissions."""

    HOME = "home"
    SETTINGS = "settings"


class UiVisibility(ContractModel):
    """Host-evaluated visibility conditions; plugins cannot evaluate code here."""

    admin_only: bool = False


class UiPageNavigation(ContractModel):
    """Optional host navigation metadata for a native plugin page."""

    sidebar: bool = False
    label: str | None = Field(default=None, min_length=1, max_length=64)
    order: int = Field(default=0, ge=-1_000, le=1_000)


class UiPage(ContractModel):
    """A native plugin page composed only from approved declarative primitives."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2_000)
    settings: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()
    dialogs: tuple[str, ...] = ()
    navigation: UiPageNavigation | None = None


class UiExtension(ContractModel):
    """A native plugin page mounted into one allowlisted host extension slot."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    slot: HostExtensionSlot
    page_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    order: int = Field(default=0, ge=-1_000, le=1_000)


class UiNavigationContribution(ContractModel):
    """A first-class host navigation entry targeting a declared plugin page."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    location: UiNavigationLocation
    label: str = Field(min_length=1, max_length=64)
    page_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    icon: str | None = Field(default=None, min_length=1, max_length=64)
    order: int = Field(default=0, ge=-1_000, le=1_000)
    visibility: UiVisibility = UiVisibility()


class UiSettingsContribution(ContractModel):
    """A plugin-provided Settings section, separate from plugin configuration."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(min_length=1, max_length=64)
    page_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    icon: str | None = Field(default=None, min_length=1, max_length=64)
    order: int = Field(default=0, ge=-1_000, le=1_000)
    visibility: UiVisibility = UiVisibility()


class UiOverlayContribution(ContractModel):
    """A host-level overlay rendered from a declared plugin page."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    page_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    order: int = Field(default=0, ge=-1_000, le=1_000)


class UiDialogContribution(ContractModel):
    """A host-level dialog backed by an existing declarative dialog."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    dialog_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")


class UiContextualAction(ContractModel):
    """An action exposed only in a declared game or media context."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    location: UiContextLocation
    label: str = Field(min_length=1, max_length=64)
    action_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    icon: str | None = Field(default=None, min_length=1, max_length=64)
    order: int = Field(default=0, ge=-1_000, le=1_000)


class UiPluginRoute(ContractModel):
    """A plugin-owned route under the host-controlled plugin route namespace."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    path: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9/_-]*$")
    page_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")


class UiPageReplacement(ContractModel):
    """A page-specific replacement with no replace-any-page escape hatch."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    page: HostPage
    page_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    order: int = Field(default=0, ge=-1_000, le=1_000)


class PluginUiDocument(ContractModel):
    """Complete versioned UI document consumed by the native frontend host."""

    schema_version: UiSchemaVersion = UiSchemaVersion.V1
    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=256)
    frontend: PluginFrontendDeclaration | None = None
    settings: tuple[UiSettingsSection, ...] = ()
    actions: tuple[UiAction, ...] = ()
    tables: tuple[UiTable, ...] = ()
    dialogs: tuple[UiDialog, ...] = ()
    menus: tuple[UiMenuItem, ...] = ()
    pages: tuple[UiPage, ...] = ()
    extensions: tuple[UiExtension, ...] = ()
    navigation: tuple[UiNavigationContribution, ...] = ()
    settings_sections: tuple[UiSettingsContribution, ...] = ()
    overlays: tuple[UiOverlayContribution, ...] = ()
    dialog_contributions: tuple[UiDialogContribution, ...] = ()
    contextual_actions: tuple[UiContextualAction, ...] = ()
    routes: tuple[UiPluginRoute, ...] = ()
    page_replacements: tuple[UiPageReplacement, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> "PluginUiDocument":
        def unique(values: list[str], kind: str) -> None:
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {kind} identifiers")

        setting_ids = [item.id for item in self.settings]
        action_ids = [item.id for item in self.actions]
        table_ids = [item.id for item in self.tables]
        dialog_ids = [item.id for item in self.dialogs]
        page_ids = [item.id for item in self.pages]
        extension_ids = [item.id for item in self.extensions]
        unique(setting_ids, "setting")
        unique(action_ids, "action")
        unique(table_ids, "table")
        unique(dialog_ids, "dialog")
        unique(page_ids, "page")
        unique(extension_ids, "extension")
        unique([item.id for item in self.navigation], "navigation contribution")
        unique([item.id for item in self.settings_sections], "settings contribution")
        unique([item.id for item in self.overlays], "overlay contribution")
        unique([item.id for item in self.dialog_contributions], "dialog contribution")
        unique([item.id for item in self.contextual_actions], "contextual action")
        unique([item.id for item in self.routes], "plugin route")
        unique([item.id for item in self.page_replacements], "page replacement")

        action_set = set(action_ids)
        table_set = set(table_ids)
        dialog_set = set(dialog_ids)
        setting_set = set(setting_ids)
        page_set = set(page_ids)
        for menu in self.menus:
            if menu.page_id is not None and menu.page_id not in page_set:
                raise ValueError(f"menu references unknown page: {menu.page_id}")
            if menu.action_id is not None and menu.action_id not in action_set:
                raise ValueError(f"menu references unknown action: {menu.action_id}")
        for page in self.pages:
            if any(value not in setting_set for value in page.settings):
                raise ValueError(f"page {page.id} references an unknown setting")
            if any(value not in action_set for value in page.actions):
                raise ValueError(f"page {page.id} references an unknown action")
            if any(value not in table_set for value in page.tables):
                raise ValueError(f"page {page.id} references an unknown table")
            if any(value not in dialog_set for value in page.dialogs):
                raise ValueError(f"page {page.id} references an unknown dialog")
        for extension in self.extensions:
            if extension.page_id not in page_set:
                raise ValueError(f"extension {extension.id} references an unknown page")

        def require_page(contribution_id: str, page_id: str) -> None:
            if page_id not in page_set:
                raise ValueError(f"contribution {contribution_id} references an unknown page")

        for navigation in self.navigation:
            require_page(navigation.id, navigation.page_id)
        for settings_section in self.settings_sections:
            require_page(settings_section.id, settings_section.page_id)
        for overlay in self.overlays:
            require_page(overlay.id, overlay.page_id)
        for route in self.routes:
            require_page(route.id, route.page_id)
        for replacement in self.page_replacements:
            require_page(replacement.id, replacement.page_id)
        for dialog_contribution in self.dialog_contributions:
            if dialog_contribution.dialog_id not in dialog_set:
                raise ValueError(
                    f"dialog contribution {dialog_contribution.id} references an unknown dialog"
                )
        for contextual_action in self.contextual_actions:
            if contextual_action.action_id not in action_set:
                raise ValueError(
                    f"contextual action {contextual_action.id} references an unknown action"
                )
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
    "API_VERSION",
    "ApiVersion",
    "Capability",
    "CapabilityRef",
    "ErrorCode",
    "ErrorDetail",
    "ErrorEnvelope",
    "EventAck",
    "EventEnvelope",
    "EventSubscription",
    "GameRepresentation",
    "JsonValue",
    "MediaRepresentation",
    "DocumentRepresentation",
    "DocumentContentRepresentation",
    "SessionRepresentation",
    "NotificationProviderRegistration",
    "NotificationDeliveryRepresentation",
    "NotificationDeliveryResult",
    "Page",
    "Pagination",
    "PluginIdentity",
    "PluginPackageIdentity",
    "RequestContext",
    "Timestamp",
    "UserContext",
    "UserRepresentation",
    "VersionNegotiationRequest",
    "VersionNegotiationResponse",
    "PermissionDeclaration",
    "PluginDependency",
    "PluginUiDeclaration",
    "StorageRequirements",
    "IntegrityMetadata",
    "PluginManifest",
    "UiSchemaVersion",
    "UiFieldType",
    "UiValidation",
    "UiOption",
    "UiField",
    "UiSettingsSection",
    "UiAction",
    "UiTableColumn",
    "UiTable",
    "UiDialog",
    "UiMenuItem",
    "UiPage",
    "PluginUiDocument",
    "PluginFrontendDeclaration",
    "PluginNativeFrontendDeclaration",
    "HostExtensionSlot",
    "HostPage",
    "UiContextLocation",
    "UiContextualAction",
    "UiDialogContribution",
    "UiExtension",
    "UiNavigationContribution",
    "UiNavigationLocation",
    "UiOverlayContribution",
    "UiPageNavigation",
    "UiPageReplacement",
    "UiPluginRoute",
    "UiSettingsContribution",
    "UiVisibility",
    "CompatibilityStatus",
    "CompatibilityDecision",
    "evaluate_manifest_compatibility",
    "migrate_manifest_data",
    "DependencyResolutionError",
    "resolve_plugin_dependencies",
    "parse_semver",
    "validate_version_range",
    "version_satisfies",
]
