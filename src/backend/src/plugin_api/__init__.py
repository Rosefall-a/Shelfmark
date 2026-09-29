"""Stable public contracts for Plugin API v1."""

from .contracts import (
    API_VERSION,
    ApiVersion,
    Capability,
    CapabilityRef,
    ErrorCode,
    ErrorEnvelope,
    EventEnvelope,
    Page,
    Pagination,
    PluginIdentity,
    RequestContext,
    Timestamp,
    VersionNegotiationRequest,
    VersionNegotiationResponse,
)
from .coordinators import (
    MetadataProvider,
    MetadataProviderRequest,
    NotificationProvider,
    NotificationRequest,
)

__all__ = [
    "API_VERSION", "ApiVersion", "Capability", "CapabilityRef", "ErrorCode",
    "ErrorEnvelope", "EventEnvelope", "Page", "Pagination", "PluginIdentity",
    "RequestContext", "Timestamp", "VersionNegotiationRequest",
    "VersionNegotiationResponse", "MetadataProvider", "MetadataProviderRequest",
    "NotificationProvider", "NotificationRequest",
]
