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
    """Base model for wire contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Capability(StrEnum):
    """Stable capability identifiers exposed by the Plugin Gateway."""

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


class PluginIdentity(ContractModel):
    """Stable identity of an installed plugin."""

    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    installation_id: UUID
    version: str = Field(min_length=1, max_length=64)


class UserContext(ContractModel):
    """The minimum user identity a gateway request may carry."""

    user_id: UUID
    authenticated: bool = True


class RequestContext(ContractModel):
    """Identity and trace context attached to every gateway request."""

    request_id: UUID
    application_id: UUID
    plugin: PluginIdentity
    user: UserContext | None = None
    requested_capability: Capability


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
    """A safe, structured validation/detail entry."""

    field: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=1024)
    code: str | None = Field(default=None, max_length=128)


class ErrorEnvelope(ContractModel):
    """Stable error response; internal exception details must never be exposed."""

    api_version: str = API_VERSION
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
    """A page of stable DTOs without leaking query/database state."""

    items: tuple[ItemT, ...]
    next_cursor: str | None = Field(default=None, max_length=512)


class EventEnvelope(ContractModel, Generic[ItemT]):
    """Versioned event delivered across the plugin boundary."""

    api_version: str = API_VERSION
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
        """Require an explicit UTC timestamp on the wire."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)


class EventSubscription(ContractModel):
    """Filter for events a plugin is allowed to receive."""

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
    "API_VERSION", "Capability", "ErrorCode", "ErrorDetail", "ErrorEnvelope",
    "EventAck", "EventEnvelope", "EventSubscription", "JsonValue", "Page",
    "Pagination", "PluginIdentity", "RequestContext", "Timestamp", "UserContext",
]
