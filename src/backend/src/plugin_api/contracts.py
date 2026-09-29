"""Versioned, implementation-independent Plugin API v1 contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


__all__ = [
    "API_VERSION", "ApiVersion", "Capability", "CapabilityRef", "ErrorCode",
    "ErrorDetail", "ErrorEnvelope", "EventAck", "EventEnvelope",
    "EventSubscription", "GameRepresentation", "JsonValue", "MediaRepresentation",
    "Page", "Pagination", "PluginIdentity", "RequestContext", "Timestamp",
    "UserContext", "UserRepresentation", "VersionNegotiationRequest",
    "VersionNegotiationResponse",
]
