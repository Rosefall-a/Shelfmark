"""Canonical hierarchical capability registry for Plugin API v1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .contracts import Capability, CapabilityRef, ContractModel, PluginPackageIdentity


class CapabilityRisk(StrEnum):
    """Stable risk bands shown during permission review."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """Display and hierarchy metadata for one grantable capability."""

    capability: Capability
    category: str
    title: str
    parent: Capability | None = None
    risk: CapabilityRisk = CapabilityRisk.MEDIUM
    highly_privileged: bool = False


class PermissionDelta(ContractModel):
    """Exact permission changes between installed and candidate manifests."""

    retained: tuple[CapabilityRef, ...] = ()
    removed: tuple[CapabilityRef, ...] = ()
    newly_requested: tuple[CapabilityRef, ...] = ()
    existing_grants: tuple[CapabilityRef, ...] = ()
    newly_requested_grants: tuple[CapabilityRef, ...] = ()


_PARENTS: dict[Capability, Capability] = {
    Capability.USERS_READ: Capability.USERS,
    Capability.USERS_PROFILE_READ: Capability.USERS,
    Capability.GAMES_READ: Capability.GAMES,
    Capability.GAMES_WRITE: Capability.GAMES,
    Capability.MEDIA_READ: Capability.MEDIA,
    Capability.MEDIA_WRITE: Capability.MEDIA,
    Capability.MEDIA_IMPORT: Capability.MEDIA,
    Capability.DOCUMENTS_READ: Capability.DOCUMENTS,
    Capability.SESSIONS_READ: Capability.SESSIONS,
    Capability.SESSIONS_REVOKE: Capability.SESSIONS,
    Capability.SESSIONS_ADMIN: Capability.SESSIONS,
    Capability.SESSIONS_ADMIN_READ: Capability.SESSIONS_ADMIN,
    Capability.SESSIONS_ADMIN_REVOKE: Capability.SESSIONS_ADMIN,
    Capability.SESSIONS_GEOIP_READ: Capability.SESSIONS,
    Capability.SESSIONS_GEOIP_CONFIGURE: Capability.SESSIONS,
    Capability.NOTIFICATIONS_SEND: Capability.NOTIFICATIONS,
    Capability.NOTIFICATION_PROVIDERS: Capability.NOTIFICATIONS,
    Capability.NOTIFICATION_PROVIDERS_REGISTER: Capability.NOTIFICATION_PROVIDERS,
    Capability.NOTIFICATION_PROVIDERS_DELIVER: Capability.NOTIFICATION_PROVIDERS,
    Capability.FRONTEND_NAVIGATION_MAIN: Capability.FRONTEND_NAVIGATION,
    Capability.FRONTEND_NAVIGATION_SETTINGS: Capability.FRONTEND_NAVIGATION,
    Capability.FRONTEND_NAVIGATION_ADMIN: Capability.FRONTEND_NAVIGATION,
    Capability.FRONTEND_CONTEXT_GAME: Capability.FRONTEND_NAVIGATION,
    Capability.FRONTEND_CONTEXT_MEDIA: Capability.FRONTEND_NAVIGATION,
    Capability.FRONTEND_CONTEXT_DOCUMENTS: Capability.FRONTEND_NAVIGATION,
    Capability.BACKEND_ROUTES_PLUGIN: Capability.BACKEND_ROUTES,
    Capability.BACKEND_ROUTES_HOST: Capability.BACKEND_ROUTES,
}

_FULL_API_IMPLIED = frozenset(
    {
        Capability.USERS,
        Capability.USERS_READ,
        Capability.USERS_PROFILE_READ,
        Capability.GAMES,
        Capability.GAMES_READ,
        Capability.GAMES_WRITE,
        Capability.MEDIA,
        Capability.MEDIA_READ,
        Capability.MEDIA_WRITE,
        Capability.MEDIA_IMPORT,
        Capability.DOCUMENTS,
        Capability.DOCUMENTS_READ,
        Capability.SESSIONS,
        Capability.SESSIONS_READ,
        Capability.SESSIONS_REVOKE,
        Capability.SESSIONS_ADMIN,
        Capability.SESSIONS_ADMIN_READ,
        Capability.SESSIONS_ADMIN_REVOKE,
        Capability.SESSIONS_GEOIP_READ,
        Capability.SESSIONS_GEOIP_CONFIGURE,
        Capability.NOTIFICATIONS,
        Capability.NOTIFICATIONS_SEND,
        Capability.NOTIFICATION_PROVIDERS,
        Capability.NOTIFICATION_PROVIDERS_REGISTER,
        Capability.NOTIFICATION_PROVIDERS_DELIVER,
        Capability.EVENTS_SUBSCRIBE,
        Capability.TASKS_BACKGROUND,
        Capability.PLUGIN_STORAGE,
        Capability.PLUGIN_SETTINGS,
        Capability.BACKEND_ROUTES,
        Capability.BACKEND_ROUTES_PLUGIN,
        Capability.BACKEND_ROUTES_HOST,
    }
)

_CRITICAL = frozenset(
    {
        Capability.FULL_API,
        Capability.FRONTEND_NATIVE,
        Capability.BACKEND_ROUTES_HOST,
    }
)
_HIGH = frozenset(
    {
        Capability.GAMES_WRITE,
        Capability.MEDIA_WRITE,
        Capability.MEDIA_IMPORT,
        Capability.SESSIONS_REVOKE,
        Capability.SESSIONS_ADMIN,
        Capability.SESSIONS_ADMIN_READ,
        Capability.SESSIONS_ADMIN_REVOKE,
        Capability.SESSIONS_GEOIP_READ,
        Capability.SESSIONS_GEOIP_CONFIGURE,
        Capability.NOTIFICATIONS_SEND,
        Capability.NOTIFICATION_PROVIDERS,
        Capability.NOTIFICATION_PROVIDERS_REGISTER,
        Capability.NOTIFICATION_PROVIDERS_DELIVER,
        Capability.FRONTEND_OVERLAY,
        Capability.FRONTEND_DIALOG,
        Capability.FRONTEND_PAGE_REPLACE_HOME,
        Capability.FRONTEND_PAGE_REPLACE_SETTINGS,
        Capability.BACKEND_ROUTES,
        Capability.NETWORK_OUTBOUND,
    }
)
_LOW = frozenset(
    {
        Capability.FRONTEND_NAVIGATION,
        Capability.FRONTEND_NAVIGATION_MAIN,
        Capability.FRONTEND_NAVIGATION_SETTINGS,
        Capability.FRONTEND_NAVIGATION_ADMIN,
        Capability.FRONTEND_CONTEXT_GAME,
        Capability.FRONTEND_CONTEXT_MEDIA,
        Capability.FRONTEND_CONTEXT_DOCUMENTS,
        Capability.FRONTEND_SETTINGS,
        Capability.FRONTEND_PAGE_EXTEND,
        Capability.FRONTEND_ROUTES,
    }
)


def _category(capability: Capability) -> str:
    value = capability.value
    if value.startswith(("users", "games", "media", "documents", "sessions")):
        return "User data"
    if value.startswith("frontend"):
        return "Frontend"
    if value.startswith("backend") or capability is Capability.FULL_API:
        return "Backend"
    if value.startswith("notification"):
        return "Notifications"
    if value.startswith("network"):
        return "External"
    return "Plugin runtime"


def _title(capability: Capability) -> str:
    return capability.value.replace("_", " ").replace(".", " / ").title()


def capability_definition(capability: Capability | str) -> CapabilityDefinition:
    """Return canonical hierarchy and review metadata for a capability."""
    resolved = capability if isinstance(capability, Capability) else Capability(capability)
    risk = CapabilityRisk.MEDIUM
    if resolved in _CRITICAL:
        risk = CapabilityRisk.CRITICAL
    elif resolved in _HIGH:
        risk = CapabilityRisk.HIGH
    elif resolved in _LOW:
        risk = CapabilityRisk.LOW
    return CapabilityDefinition(
        capability=resolved,
        category=_category(resolved),
        title=_title(resolved),
        parent=_PARENTS.get(resolved),
        risk=risk,
        highly_privileged=resolved in _CRITICAL,
    )


def capability_children(capability: Capability | str) -> tuple[Capability, ...]:
    """Return direct children in stable identifier order."""
    resolved = capability if isinstance(capability, Capability) else Capability(capability)
    return tuple(
        sorted((child for child, parent in _PARENTS.items() if parent is resolved), key=str)
    )


def capability_ancestors(capability: Capability | str) -> tuple[Capability, ...]:
    """Return grantable ancestors from nearest to furthest."""
    resolved = capability if isinstance(capability, Capability) else Capability(capability)
    ancestors: list[Capability] = []
    while parent := _PARENTS.get(resolved):
        ancestors.append(parent)
        resolved = parent
    return tuple(ancestors)


def capability_implies(granted: Capability | str, requested: Capability | str) -> bool:
    """Return whether one grant authorizes the requested capability."""
    granted_capability = granted if isinstance(granted, Capability) else Capability(granted)
    requested_capability = requested if isinstance(requested, Capability) else Capability(requested)
    if granted_capability is requested_capability:
        return True
    if granted_capability is Capability.FULL_API:
        return requested_capability in _FULL_API_IMPLIED
    return granted_capability in capability_ancestors(requested_capability)


def capability_grant_candidates(capability: Capability | str) -> tuple[str, ...]:
    """Return persisted grant names that can authorize a requested leaf."""
    try:
        resolved = capability if isinstance(capability, Capability) else Capability(capability)
    except ValueError:
        return ()
    candidates = [resolved, *capability_ancestors(resolved)]
    if resolved in _FULL_API_IMPLIED:
        candidates.append(Capability.FULL_API)
    return tuple(item.value for item in candidates)


def expand_capabilities(capabilities: Iterable[Capability | str]) -> tuple[str, ...]:
    """Expand persisted parent grants into the exact capabilities they authorize."""
    granted: list[Capability] = []
    for value in capabilities:
        try:
            granted.append(value if isinstance(value, Capability) else Capability(value))
        except ValueError:
            continue
    effective = {
        candidate.value
        for candidate in Capability
        if any(capability_implies(grant, candidate) for grant in granted)
    }
    return tuple(sorted(effective))


def calculate_permission_delta(
    previous_requested: Iterable[CapabilityRef],
    new_requested: Iterable[CapabilityRef],
    existing_grants: Iterable[CapabilityRef],
) -> PermissionDelta:
    """Compare exact capability/version identities without auto-granting additions."""

    def keyed(values: Iterable[CapabilityRef]) -> dict[tuple[str, int], CapabilityRef]:
        return {(value.name.value, value.version): value for value in values}

    previous = keyed(previous_requested)
    candidate = keyed(new_requested)
    grants = keyed(existing_grants)

    def ordered(keys: set[tuple[str, int]], source: dict[tuple[str, int], CapabilityRef]):
        return tuple(source[key] for key in sorted(keys))

    previous_keys = set(previous)
    candidate_keys = set(candidate)
    grant_keys = set(grants)
    newly_requested = candidate_keys - previous_keys
    return PermissionDelta(
        retained=ordered(previous_keys & candidate_keys, candidate),
        removed=ordered(previous_keys - candidate_keys, previous),
        newly_requested=ordered(newly_requested, candidate),
        existing_grants=ordered(grant_keys, grants),
        newly_requested_grants=ordered(newly_requested, candidate),
    )


def package_identity_can_retain_grants(
    previous: PluginPackageIdentity,
    candidate: PluginPackageIdentity,
) -> bool:
    """Require the same software ID and verified publisher before grants continue."""
    return (
        previous.plugin_id == candidate.plugin_id
        and previous.publisher_key_id is not None
        and previous.publisher_key_id == candidate.publisher_key_id
    )


__all__ = [
    "CapabilityDefinition",
    "CapabilityRisk",
    "PermissionDelta",
    "calculate_permission_delta",
    "capability_ancestors",
    "capability_children",
    "capability_definition",
    "capability_grant_candidates",
    "capability_implies",
    "expand_capabilities",
    "package_identity_can_retain_grants",
]
