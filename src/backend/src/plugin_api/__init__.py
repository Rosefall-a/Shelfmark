"""Stable public contracts for Plugin API v1.

This package contains data contracts only. It must not import application
database models, request handlers, or implementation-specific services.
"""

from .contracts import (
    API_VERSION,
    Capability,
    ErrorCode,
    ErrorEnvelope,
    EventEnvelope,
    Page,
    Pagination,
    PluginIdentity,
    RequestContext,
    Timestamp,
)
from .coordinators import (
    MetadataProvider,
    MetadataProviderRequest,
    NotificationProvider,
    NotificationRequest,
)

__all__ = [
    "API_VERSION", "Capability", "ErrorCode", "ErrorEnvelope",
    "EventEnvelope", "Page", "Pagination", "PluginIdentity",
    "RequestContext", "Timestamp", "MetadataProvider",
    "MetadataProviderRequest", "NotificationProvider", "NotificationRequest",
]
