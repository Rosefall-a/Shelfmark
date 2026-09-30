"""Capability authorization and scoped plugin/client identity contracts."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from .capabilities import capability_implies
from .contracts import CapabilityRef, ContractModel, RequestContext


class PermissionDecision(StrEnum):
    """Stable authorization outcomes."""

    ALLOWED = "allowed"
    DENIED = "denied"


class PermissionGrant(ContractModel):
    """A grant scoped to one plugin installation and optionally one user/device."""

    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    installation_id: UUID
    capability: CapabilityRef
    user_id: UUID | None = None
    device_id: UUID | None = None
    granted_at: datetime
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class AuthorizationDecision(ContractModel):
    """Safe result of gateway capability evaluation."""

    decision: PermissionDecision
    reason: str = Field(min_length=1, max_length=512)


def authorize_request(context: RequestContext, grants: tuple[PermissionGrant, ...]) -> AuthorizationDecision:
    """Apply default-deny authorization to an authenticated request."""
    if context.user is None or not context.user.authenticated:
        return AuthorizationDecision(
            decision=PermissionDecision.DENIED,
            reason="authenticated user context is required",
        )
    requested = context.requested_capability
    for grant in grants:
        if not grant.active:
            continue
        if grant.plugin_id != context.plugin.plugin_id or grant.installation_id != context.plugin.installation_id:
            continue
        if grant.capability.version != requested.version or not capability_implies(
            grant.capability.name, requested.name
        ):
            continue
        if grant.user_id is not None and (
            context.user is None or not context.user.authenticated or grant.user_id != context.user.user_id
        ):
            continue
        if grant.device_id is not None and grant.device_id != context.device_id:
            continue
        return AuthorizationDecision(decision=PermissionDecision.ALLOWED, reason="matching capability grant is active")
    return AuthorizationDecision(
        decision=PermissionDecision.DENIED,
        reason="no active grant matches plugin, installation, capability and scope",
    )


class ClientIdentity(ContractModel):
    """A user/device identity scoped to one plugin installation."""

    client_id: UUID = Field(default_factory=uuid4)
    plugin_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    installation_id: UUID
    user_id: UUID
    device_id: UUID
    name: str = Field(min_length=1, max_length=128)
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedClientCredential:
    """One-time client credential; only its hash is persisted."""

    client: ClientIdentity
    token: str


def issue_client_credential(
    *, plugin_id: str, installation_id: UUID, user_id: UUID, device_id: UUID, name: str,
    now: datetime | None = None,
) -> IssuedClientCredential:
    """Create a high-entropy credential bound to user/device/plugin identity."""
    issued_at = now or datetime.now(timezone.utc)
    client = ClientIdentity(
        plugin_id=plugin_id, installation_id=installation_id, user_id=user_id,
        device_id=device_id, name=name, created_at=issued_at,
    )
    return IssuedClientCredential(
        client=client,
        token="pmc1." + str(client.client_id) + "." + secrets.token_urlsafe(48),
    )


__all__ = [
    "AuthorizationDecision", "ClientIdentity", "IssuedClientCredential",
    "PermissionDecision", "PermissionGrant", "authorize_request",
    "issue_client_credential",
]
