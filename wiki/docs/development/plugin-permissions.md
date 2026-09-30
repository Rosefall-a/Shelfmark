# Plugin Permissions & Scoped Identities

The permission gateway is default-deny and is enforced at the gateway rather than by plugin UI.

## Administrator workflow
1. The Plugin Manager statically verifies an uploaded package and displays its identity, publisher trust, dependencies, UI contribution summary, and every requested capability before installation.
2. An administrator explicitly allows or denies each capability in the contextual install dialog. Permissions default to denied.
3. The package is uploaded again for installation, re-verified, and rejected if the approved capability keys do not match its manifest.
4. Later requests (for example, permissions introduced by an update) are reviewed in that plugin's **Settings → Permissions** tab.
5. Active grants can be revoked at any time from the same dialog.
6. Grants are scoped to the plugin installation and may be narrowed to a user or device.

Manifest declarations never grant access by themselves.

## Scoped clients
Supported integrations can create a client identity bound to a plugin installation, application user and device. The credential is returned only at creation and its SHA-256 hash is stored. Client revocation is independent from user API keys.

The client identity is deliberately separate from plugin installation identity (#283) and gateway authentication (#265).

## Policy
The authorization function requires exact plugin/installation/capability/version matches and enforces optional user/device scope. No matching grant means denial.


## Audit and security
Permission requests, grants, revocations, and audit records are persisted. The production gateway resolves the current installed package and requires an active grant matching plugin ID, installation ID, capability, capability version, and optional user scope. Disabled installations cannot dispatch actions.

The policy is default-deny and rejects requests without authenticated user context. A grant with no user scope means any authenticated user; a scoped grant must match the authenticated user exactly.

The permission layer is intentionally independent of transport. Gateway authentication from #265 supplies trusted plugin and installation identity; this layer evaluates whether that identity is permitted to perform the requested capability.


## Permission risk display
The administrator approval view classifies requested capabilities before approval:
- **High risk:** write/destructive capabilities, session revocation, external delivery, and notification sending.
- **Medium risk:** document/session reads and event subscriptions.
- **Low risk:** plugin-owned settings/storage capabilities.

Risk is a presentation aid for administrator review; it never changes authorization. The gateway still requires an explicit grant and applies the same default-deny policy regardless of the displayed risk.


## Installation review

Installation is a preview-and-commit flow. Preview never installs or executes the package. The administrator's choices are persisted as resolved permission requests during installation, with grants created only for explicitly allowed capabilities. Unsigned or untrusted packages require a separate warning acknowledgement in the same dialog.

Permission management is contextual to each plugin; there is no separate global permission-review page. Pending requests must be approved before actions requiring those capabilities can succeed.
