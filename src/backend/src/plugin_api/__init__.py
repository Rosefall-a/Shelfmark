"""Stable public contracts for Plugin API v1."""

from .contracts import (
    API_VERSION,
    ApiVersion,
    Capability,
    CapabilityRef,
    CompatibilityDecision,
    CompatibilityStatus,
    DependencyResolutionError,
    IntegrityMetadata,
    PermissionDeclaration,
    PluginDependency,
    PluginManifest,
    PluginUiDeclaration,
    StorageRequirements,
    evaluate_manifest_compatibility,
    migrate_manifest_data,
    resolve_plugin_dependencies,
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
    parse_semver,
    validate_version_range,
    version_satisfies,
)
from .gateway_auth import (
    ApplicationIdentity, BootstrapRequest, CredentialError, CredentialKind,
    GatewayAuthenticator, GatewayHandshake, GatewayIdentity, ReplayError,
)
from .coordinators import (
    MetadataProvider,
    MetadataProviderRequest,
    NotificationProvider,
    NotificationRequest,
)

__all__ = [
    "API_VERSION", "ApiVersion", "Capability", "CapabilityRef", "CompatibilityDecision",
    "CompatibilityStatus", "DependencyResolutionError", "IntegrityMetadata",
    "PermissionDeclaration", "PluginDependency", "PluginManifest", "PluginUiDeclaration",
    "StorageRequirements", "evaluate_manifest_compatibility", "migrate_manifest_data",
    "resolve_plugin_dependencies", "parse_semver", "validate_version_range",
    "version_satisfies", "ErrorCode",
    "ErrorEnvelope", "EventEnvelope", "Page", "Pagination", "PluginIdentity",
    "RequestContext", "Timestamp", "VersionNegotiationRequest",
    "VersionNegotiationResponse", "ApplicationIdentity", "BootstrapRequest",
    "CredentialError", "CredentialKind", "GatewayAuthenticator", "GatewayHandshake",
    "GatewayIdentity", "ReplayError", "MetadataProvider", "MetadataProviderRequest",
    "NotificationProvider", "NotificationRequest",
]
