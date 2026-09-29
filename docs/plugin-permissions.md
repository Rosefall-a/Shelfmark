# Plugin Permissions & Scoped Identities

This page documents the capability gateway implemented for #266 and children #284–#286.

## Authorization
Authorization is default-deny. An active grant must match plugin ID, installation ID, capability name/version, and any user/device scope. Revoked grants never authorize requests. Manifest declarations request capabilities but do not grant them.

## Administrator approval
Plugins can submit permission requests with a capability, version and human-readable rationale. Administrators review pending requests in **Settings → Plugin Permissions**, approve or deny them, and revoke active grants later.

## Scoped client identities
A supported client can create an identity bound to one plugin installation, application user and device. The one-time credential is high entropy and only its SHA-256 hash is stored. Revocation is per client identity. This is intended for integrations such as Playnite so they can use a scoped identity rather than a broad user API key.

## Security boundary
The policy engine consumes authenticated RequestContext plus active grants and does not inspect ORM objects, database sessions, application secrets or broad API tokens.


## Audit trail
Authorization decisions include a stable request ID and can be recorded with plugin/installation identity, capability/version, user/device scope, decision, reason and timestamp. The policy remains default-deny and requires authenticated user context.

### Compatibility
The permission contract is additive to Plugin API v1: existing request DTOs retain their fields, with `device_id` optional. Manifest capability declarations remain requests, not grants. No existing application API token is expanded or repurposed.
