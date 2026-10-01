# Plugin updates

Plugin updates use the same verification, compatibility, permission, and runtime boundaries as installation.

## Package verification

Plugin package v1 is a ZIP containing `manifest.json` and `payload/`. Paths are constrained to the package namespace. The verifier rejects traversal, exact or semantic duplicate paths, repeated separators, dot segments, drive-like paths, unexpected files and unsupported filesystem entries.

The manifest integrity field contains a deterministic SHA-256 digest of sorted payload paths and bytes. An Ed25519 publisher signature over `plugin-package-v1:<sha256>` is verified when present, with `key_id` resolving to an explicitly trusted publisher key. The installer preserves four distinct states: signed/trusted, signed/unknown-key, signed/invalid, and unsigned. Invalid signatures are blocked. Unsigned or unknown-key packages require explicit administrator acknowledgement; highly privileged grants additionally require backend-enforced password reauthentication and explicit confirmation.

## Staging and activation

Updates are verified and extracted into version-specific directories without changing the active version. Activation validates SDK/application compatibility and the full dependency graph, then stops the old version, atomically changes the active pointer, starts through the isolated runtime and requires a healthy runtime check.

The previous known-good version remains retained in the active pointer.

## Rollback

Failed activation automatically restores the previous version and attempts to restart and health-check it. Manual rollback uses the same health-tested atomic switch. Failure to restore the previous version is surfaced rather than hidden.

Plugin storage is independent of executable versions, so rolling executable versions back does not require rolling core database migrations.

## Security boundary

The update layer never imports plugin code, grants capabilities, bypasses gateway authentication, or exposes the core database. Execution remains delegated to the isolated runtime and lifecycle/quarantine rules remain authoritative.

Dependency failures reject installation/activation rather than allowing an invalid dependency graph to run. Required and optional constraints, cycles, installed versions, and catalogue-advertised versions are reported. A dependency is installed and permissioned independently; it never inherits the dependent plugin's grants.


## Update invariants

- The source package is re-read into a private snapshot before extraction so verification and staged contents refer to the same package bytes.
- A package is never activated directly from its archive; activation uses the versioned staged directory.
- If an activation attempt has no previous known-good version, a failed attempt leaves no active pointer.


## End-user `.utp` installation

Administrators install a plugin from **Settings → Plugins → Install plugin** by upload, public URL, or enabled catalogue. Acquisition only produces a bounded local file; every source then uses `PluginInstaller` in `src/backend/src/plugin_api/installer.py` for inspection, trust, dependency resolution, permission delta, confirmation, installation, activation, and health. Upload and remote updates use that same service. File contents identify the v1 ZIP package, including `.utp`, `.zip`, and downloads without those extensions. The backend limits packages to 64 MiB and enforces entry/file/uncompressed/compression-ratio limits, safe POSIX paths, duplicate rejection, and symlink rejection. Invalid signatures are hard failures, including malformed signatures with unknown keys; unsigned and unknown-publisher packages remain distinct consent states.

The authenticated runtime prepares the package with a unique operation ID, validates the archive and digest again, and keeps it disabled while PostgreSQL permission decisions commit. The host then completes the runtime transaction before starting the plugin and checking health. A definitive database rejection aborts the prepared package and restores its predecessor. Runtime updates retain their backup until completion and compare the installed version with the planned version to reject concurrent stale updates. Prepared packages cannot satisfy another plugin's required dependencies. Unfinished transactions survive runtime restart and cannot activate through enable or retry. If the host loses the database commit acknowledgement or runtime finalization response, administrators can inspect the disabled installation and remove/reinstall it; the host does not guess whether grants committed or restore old unverified code with potentially new grants. Host and runtime must be upgraded together; older runtimes reject the preparation endpoint before modifying a package.

Installed URL/catalogue packages retain source metadata. On-demand checks compare semantic versions, expose source-agnostic release notes/changelogs, and create deduplicated `plugin_update` rows in the existing notification system for administrators. Catalogue configuration is persisted with name, URL, enabled state, priority, provenance metadata, last success, and last error. Catalogue provenance never changes signature trust.

Discovered URL/catalogue updates can be previewed and applied directly through the same bounded acquisition path. A verified update from the same trusted key may retain previously reviewed grants only when the installed package was also verified. An unsigned or otherwise unverified update inherits no grants: every requested permission is reviewed again, and dangerous selections require password reauthentication and explicit confirmation. Becoming trusted does not carry forward unverified grants. A different publisher cannot take over an installation signed by a trusted publisher. Dependency resolution checks direct and transitive dependencies, cycles, and installed dependents' version constraints before activation. Dependency permissions never contribute to the candidate's requested or granted permissions.

Official reference publisher keys are trusted by default. Development builds from the plugin repository are deliberately unsigned and exercise the untrusted-package consent path. Release builds use a private reviewed key scoped to the `example.` namespace. Additional publisher trust is configured through `PLUGIN_TRUSTED_PUBLISHER_REGISTRY`.
