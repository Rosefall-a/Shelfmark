# Plugin updates and rollback

Updates use the same package verification, compatibility, dependencies, route ownership, publisher trust and permission boundaries as installation. Packages are bounded v1 ZIP archives containing manifest.json and payload/. Their canonical sorted payload paths/bytes determine SHA-256; Ed25519 signatures cover plugin-package-v1:<sha256>. Invalid signatures and malformed packages are hard failures. Catalogue provenance never substitutes for signature trust.

## Staging and permission review

Discovered releases are distinct from installed versions. A staged archive is stored on the backend persistent volume with downloaded, awaiting_permissions or denied status. Discovery/download never changes the active package or grants.

A candidate introducing new scopes remains staged until explicit approval. The existing working version keeps running. Denial retains it and does not activate new privileges. Review compares exact capability/version identities. Removed requests lose grants. Revoked permissions remain revoked across restart, disable/enable, reinstall, rollback and update; administrators can explicitly re-grant scopes declared by the active package without reinstalling.

Denial is durable for that staged version and digest: scheduled checks do not reset it or install that release automatically. Administrators may review and approve it later. Consent is bound to the reviewed package digest, so a changed staged package requires another review.

Only verified packages from the same verified publisher key inherit existing appropriate grants. Unsigned/unknown publisher updates receive a fresh permission review. Privileged unverified grants require confirmation and administrator password reauthentication. A publisher change requires the explicit Replace flow. Dependency permissions never transfer to a dependent plugin.

## Automatic updates

Automatic installation defaults off globally. Each installed plugin can Follow global, Enable or Disable it. These controls are independent of the Scheduled Tasks plugin_updates job, which defaults to daily discovery and can use the existing task scheduling controls.

Only installations tracking an enabled catalogue participate in the scheduled task. Uploaded and arbitrary URL packages have no assumed automatic release tracking. Manual update checks remain available for URL installations with source metadata.

The task discovers a newer semantic version, records an available update, notifies administrators, downloads and verifies the package, compares plugin ID/version and any catalogue digest, checks installability/dependencies and stages the release. Automatic activation additionally requires enabled global/per-plugin policy, a verified trusted package, no new permission scopes and both release metadata and manifest permitting automatic updates.

Rich catalogue entries can supply tags, publisher, documentation, build/package metadata and icons described by a safe relative path and SHA-256. The manager accepts legacy string icons too. The canonical payload digest (`sha256` or `digest`) and optional complete archive hash (`package_sha256`) are separate checks; automatic downloads validate both when present. Package previews extract bounded README and icon assets from the verified archive, with sanitized Markdown rendering in the browser.

The boolean automatic_update field defaults true and is release-specific. A catalogue release or package manifest may set it false for a breaking release. This does not permanently disable automatic updates for the plugin: later releases may opt in again. Disabled policy, release opt-out and new permissions leave a distinct staged download for manual review. Incompatible, corrupt or otherwise invalid candidates record an error and retain the active package.

Updates can be performed directly in Updates Available and the plugin detail view. Manual approval revalidates the staged bytes through the canonical installer before switching.

## Verification, failure and history

Activation retains the prior package until the new process passes startup/health verification. A failed automatic update restores and restarts the predecessor, records a last-update error and creates a deduplicated administrator failure notification. Installation failures are isolated per plugin so remaining catalogue installations are still checked. Application and runtime restarts preserve pending transaction metadata; database commit receipts support startup recovery.

Health verification checks that the supervised process survives a startup grace period. It does not prove semantic correctness of every plugin action. Data migrations remain plugin-owned; package rollback does not restore an earlier data backup.

At least one previous package is retained after successful replacement. Administrators can configure retention from 1 through 100 packages and delete individual retained versions. Manual rollback uses the same installer/health checks and preserves data. Rollback does not automatically re-grant scopes removed or revoked since the older version was installed; use explicit permission review to grant them again.

Reinstall reconstructs the active verified payload and manifest and requires the same version/digest. It does not fetch a mutable source URL. Retained package versions and staged downloads are executable release history, not snapshots of configuration, secrets, profiles or imported history.

See [Lifecycle](plugin-lifecycle.md), [Permissions](plugin-permissions.md) and [Management API](plugin-management-api.md).
