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
