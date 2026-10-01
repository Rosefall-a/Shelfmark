# Plugin Manifest, Compatibility & Dependencies

This document defines the static manifest and dependency rules implemented for Plugin Manager v1.

## Manifest

A manifest declares:

- stable plugin ID and semantic version;
- display name and description;
- safe plugin entrypoint;
- Plugin SDK compatibility range;
- application compatibility range;
- capability requests;
- human-readable permission rationales;
- required and optional plugin dependencies;
- declarative settings, actions, pages and menu identifiers;
- an optional sandboxed `frontend` bundle and optional privileged `native_frontend` bundle;
- namespaced storage quota;
- SHA-256 package integrity and optional signature metadata.

The manifest is validated as data before plugin code is loaded. Unknown fields and unsafe or malformed values are rejected.

## Compatibility

SDK and application compatibility are independent. A plugin must satisfy both ranges before activation.

Supported range forms are exact versions, comparisons, caret/tilde ranges, and bounded x/* minor/major wildcards. Invalid ranges are rejected.

An incompatible plugin is classified as incompatible and the activation decision is quarantine rather than execution. This prevents an incompatible extension from blocking core startup.

## Migration

Manifest version migration is a pure dictionary transformation. Known legacy field aliases are converted to the v1 names, while ambiguous fields or unsupported manifest versions are rejected. Migration never imports or executes plugin code.

## Dependencies

Permission declarations correspond one-to-one with declared capabilities and must use the same capability version. Dependencies identify another plugin and a semantic-version range. Required dependencies must exist and satisfy their range. Optional dependencies may be absent or incompatible without blocking the plugin.

The resolver:

1. validates dependency versions;
2. rejects missing required dependencies;
3. rejects required version conflicts;
4. detects dependency cycles;
5. produces deterministic dependency-first installation order.

Dependency resolution must complete before plugin activation.

## Security boundary

Manifest metadata does not grant capabilities. Gateway authorization remains responsible for enforcing grants. The application verifies package digest/signature/trust before installation, and the runtime independently verifies the archive/digest before atomically installing it. Plugin code is not imported during either verification pass.

The existing `frontend` declaration always means a sandboxed iframe bundle. A
`native_frontend` declaration is a separate, privileged contract and is valid only
when the manifest requests `frontend.native`. Its entry and styles live below
`native/`; the runtime serves them from a distinct endpoint, and the application
host only exposes that endpoint and activates the bundle while the exact grant is
effective for an enabled compatible installation.

These fields and capability names are additive Plugin API v1 contracts. Existing v1 manifests remain valid. Any future incompatible contract must use an explicit manifest/API migration rather than changing v1 interpretation in place.
