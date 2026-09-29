# Plugin updates

Issue #271 defines secure package updates, staged activation, dependency validation and rollback.

## Package verification

Plugin package v1 is a ZIP containing `manifest.json` and `payload/`. Paths are constrained to the package namespace. The verifier rejects traversal, duplicate entries, unexpected files and unsupported filesystem entries.

The manifest integrity field contains a deterministic SHA-256 digest of sorted payload paths and bytes. Production verification requires an Ed25519 publisher signature over `plugin-package-v1:<sha256>`, with the manifest's `key_id` resolving to an explicitly trusted publisher key.

## Staging and activation

Updates are verified and extracted into version-specific directories without changing the active version. Activation validates SDK/application compatibility and the full dependency graph, then stops the old version, atomically changes the active pointer, starts through the isolated runtime and requires a healthy runtime check.

The previous known-good version remains retained in the active pointer.

## Rollback

Failed activation automatically restores the previous version and attempts to restart and health-check it. Manual rollback uses the same health-tested atomic switch. Failure to restore the previous version is surfaced rather than hidden.

Plugin storage is independent of executable versions, so rolling executable versions back does not require rolling core database migrations.

## Security boundary

The update layer never imports plugin code, grants capabilities, bypasses gateway authentication, or exposes the core database. Execution remains delegated to the isolated runtime and lifecycle/quarantine rules remain authoritative.

Dependency failures reject activation rather than allowing an invalid dependency graph to run.


## Update invariants

- The source package is re-read into a private snapshot before extraction so verification and staged contents refer to the same package bytes.
- A package is never activated directly from its archive; activation uses the versioned staged directory.
- If an activation attempt has no previous known-good version, a failed attempt leaves no active pointer.
