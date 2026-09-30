# Plugin package updates and rollback

Issue #271 owns secure package updates after the API, manifest, isolated-runtime, and lifecycle contracts.

## Package format v1

A plugin update is a ZIP archive containing only:

- `manifest.json`
- `payload/<plugin files...>`

Paths are validated as POSIX paths and reject traversal, absolute paths, duplicate entries, unexpected files, and unsupported filesystem entries.

The manifest remains the authoritative API v1 manifest. `integrity.sha256` is the SHA-256 digest of a deterministic stream of sorted payload paths and bytes. The digest excludes `manifest.json`.

## Publisher verification

Packages are integrity-checked before staging. Production verification requires a publisher signature by default.

Signatures use Ed25519 and cover:

`plugin-package-v1:<sha256>`

The manifest supplies a publisher `key_id`; keys in the reviewed publisher trust registry can establish verified publisher identity. The host's bundled registry is a bootstrap policy. Deployments may supply a reviewed replacement file through `PLUGIN_TRUSTED_PUBLISHER_REGISTRY`; raw key/value environment entries are not accepted. Each record binds a key to a publisher, status and permitted plugin-ID prefixes. Active and retiring keys verify existing packages during a planned overlap. Invalid signatures are rejected. Unsigned, unknown-key, revoked-key, and out-of-scope packages remain explicitly unverified and require administrator consent; dangerous grants additionally require password reauthentication.

Rotate a publisher key by first adding its successor as `active`, switching release signing to it, and changing the predecessor to `retiring` only for the documented overlap. After all supported consumers have moved, change the predecessor to `revoked`. A revocation is an incident response action: block new packages immediately, preserve audit evidence and review installed versions signed by that key before enabling them again.

Unsigned packages are therefore not silently accepted by the production verifier. Tests/development can explicitly opt out of the signature requirement.

## Staged installation

A verified update is extracted into a temporary directory and atomically renamed into a version-specific plugin directory. Staging does not change the active version.

Plugin executable versions are independent of plugin-owned storage.

## Dependency-aware planning

Before activation, the candidate manifest is combined with the installed manifest set and resolved through the API v1 deterministic dependency resolver. Missing, incompatible, or cyclic required dependencies reject the update. Optional dependencies do not make the update invalid when unavailable.

An application update must not be blocked by an incompatible plugin; the plugin remains outside activation and can be reported/quarantined by lifecycle management.

## Health-tested activation

Activation follows:

1. verify package integrity/signature;
2. statically validate application/SDK compatibility;
3. stage the new version;
4. validate the complete dependency graph;
5. stop the current version;
6. atomically point the plugin at the staged version;
7. start through the isolated runtime boundary;
8. require a successful runtime health check.

The core backend never imports or executes plugin code.

## Atomic rollback

The active pointer retains the previous known-good version. If staged startup or health checking fails, the manager restores the previous pointer and attempts to restart that version. A failed rollback is surfaced as an update activation error rather than being hidden.

Manual rollback follows the same stop → atomic switch → start → health-check sequence. If the rollback target fails health validation, the prior active version is restored.

## Security and compatibility

Package contents are treated as untrusted data until integrity and publisher checks pass. Archive extraction rejects traversal and unsupported entries. Update execution remains delegated to the isolated runtime from #267 and lifecycle/quarantine remains authoritative under #270.

The update layer does not grant permissions, bypass gateway authentication, expose core storage, or alter core migrations.
