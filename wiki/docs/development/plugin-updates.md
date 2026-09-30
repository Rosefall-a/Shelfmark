# Plugin updates

Plugin updates use the same verification, compatibility, permission, and runtime boundaries as installation.

## Package verification

Plugin package v1 is a ZIP containing `manifest.json` and `payload/`. Paths are constrained to the package namespace. The verifier rejects traversal, exact duplicate entries, unexpected files and unsupported filesystem entries. Semantic ZIP path collisions such as repeated separators still require hardening; see #338.

The manifest integrity field contains a deterministic SHA-256 digest of sorted payload paths and bytes. An Ed25519 publisher signature over `plugin-package-v1:<sha256>` is verified when present, with `key_id` resolving to an explicitly trusted publisher key. Unsigned or untrusted packages require explicit administrator acknowledgement; release policy should require signatures.

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


## End-user `.utp` installation

Administrators install a plugin from **Settings → Plugins → Install plugin** by selecting its `.utp` package. The backend limits uploads to 64 MiB and verifies the v1 archive, canonical payload digest, and publisher signature/trust status before sending the package over the authenticated runtime connection. The runtime validates the archive and digest again and atomically creates the plugin directory; it never executes plugin code during installation.

Official reference publisher keys are trusted by default. Development builds from the plugin repository are deliberately unsigned and exercise the untrusted-package consent path. Release builds use a private reviewed key scoped to the `example.` namespace. Additional publisher trust is configured through `PLUGIN_TRUSTED_PUBLISHER_REGISTRY`.
