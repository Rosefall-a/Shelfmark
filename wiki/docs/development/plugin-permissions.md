# Plugin Permissions & Scoped Identities

The permission gateway is default-deny and is enforced at the gateway rather than by plugin UI.

## Administrator workflow
1. A plugin submits a capability/version request with a human-readable rationale.
2. An administrator reviews it in **Settings → Plugin Permissions**.
3. The administrator approves or denies the request.
4. Active grants can be revoked at any time.
5. Grants are scoped to the plugin installation and may be narrowed to a user or device.

Manifest declarations never grant access by themselves.

## Scoped clients
Supported integrations can create a client identity bound to a plugin installation, application user and device. The credential is returned only at creation and its SHA-256 hash is stored. Client revocation is independent from user API keys.

The client identity is deliberately separate from plugin installation identity (#283) and gateway authentication (#265).

## Policy
The authorization function requires exact plugin/installation/capability/version matches and enforces optional user/device scope. No matching grant means denial.


## Audit and security
The database model for authorization audit records exists, but persistence-backed authorization/audit is not yet wired into the production gateway; this remains tracked by #336.

The policy is default-deny and rejects requests without authenticated user context. A grant with no user scope means any authenticated user; a scoped grant must match the authenticated user exactly.

The permission layer is intentionally independent of transport. Gateway authentication from #265 supplies trusted plugin and installation identity; this layer evaluates whether that identity is permitted to perform the requested capability.


## Permission risk display
The administrator approval view classifies requested capabilities before approval:
- **High risk:** write capabilities and notification sending.
- **Medium risk:** read capabilities and event subscriptions.
- **Low risk:** plugin-owned settings/storage capabilities.

Risk is a presentation aid for administrator review; it never changes authorization. The gateway still requires an explicit grant and applies the same default-deny policy regardless of the displayed risk.
