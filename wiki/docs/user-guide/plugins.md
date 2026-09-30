# Plugins

Plugins are independently packaged `.utp` extensions. An administrator installs and updates them from **Settings → Plugins**.

## Installation consent

1. Select a package, enter a public package URL, or choose an enabled catalogue entry. A harmless filename-extension mismatch is allowed because the archive content is inspected.
2. The host verifies the archive and shows plugin identity, version, publisher trust, dependencies, UI contributions, and every requested permission.
3. Review each permission and its rationale. Permissions default to denied.
4. Unsigned or unknown-key packages require a separate acknowledgement. An invalid signature is blocked.
5. Highly privileged grants to an unverified package require administrator password re-entry and explicit dangerous-capability confirmation.
6. Confirm installation. The host installs, activates, and reports the initial health result.

Preview and package validation never execute plugin code. Activation happens only after validation, dependency checks, permission review, any required reauthentication, and the explicit commit. Denied capabilities stay unavailable even if they appear in the manifest.

## Pages and settings

Enabled plugins may add host-owned sidebar routes under `/plugins/{plugin_id}/{page_id}`. Native extensions can appear only in allowlisted host slots. A custom frontend runs in a sandboxed iframe and cannot access host cookies, local storage, Vue state, or the host DOM.

Plugin settings, permissions, and diagnostics are in the plugin's own settings dialog. Permissions are grouped into expandable categories; selecting a parent selects its requested descendants. Secrets are write-only: saving replaces the value, but neither the browser nor later API responses can read it back.

## Revoking or removing access

Revoking a grant takes effect on the next gateway request. Disable stops the plugin and removes its pages/slots. Uninstall stops it, removes its package and private plugin storage, and revokes its notification-provider registrations. Updates are previewed before replacement, show changelog/dependency/permission changes, and cannot silently acquire newly requested permissions. Administrators can check configured sources for updates; available updates appear in the existing notification feed.

The official reference plugins demonstrate [document viewing](../development/reference-plugins.md#scoped-document-viewer), [self-service sessions](../development/reference-plugins.md#self-service-session-manager), and [external notification delivery](../development/reference-plugins.md#external-discord-delivery-provider).
