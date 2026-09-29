# Plugin Runtime

The plugin runtime is a separate, unprivileged service. The application backend is the only core component that can reach its management API.

## Runtime topology

Browser -> Vue frontend -> FastAPI backend -> authenticated HTTP -> plugin-runtime -> bubblewrap -> isolated plugin process.

Compose places plugin-runtime and the backend on an internal Docker network that is not shared with PostgreSQL or the frontend. The runtime is not published to the host. Its /health endpoint is unauthenticated only for the container health check; management endpoints require PLUGIN_RUNTIME_TOKEN.

Set the same high-entropy PLUGIN_RUNTIME_TOKEN for backend and plugin-runtime. The development Compose file supplies a development fallback, which must be replaced for production.

## Discovery and integrity

Installed packages live under the plugin_data volume. Each package directory contains manifest.json, the declared entrypoint, and optionally ui.json. The runtime validates the plugin ID and entrypoint before execution and computes a deterministic SHA-256 digest. Manifest metadata and runtime-owned settings are excluded from that digest so the expected hash remains stable.

A package whose digest does not match its manifest is reported as incompatible and cannot be started.

## Process isolation

Every plugin gets its own process and bubblewrap sandbox. The sandbox uses private mount, PID, IPC, UTS and network namespaces. Package files are read-only; a private writable process-data directory is provided separately.

The subprocess receives only a minimal environment. Core credentials, database credentials, Docker configuration and gateway credentials are explicitly rejected. CPU time, address space, open files and process count are bounded.

## Lifecycle and recovery

The runtime implements discovery/listing, start, stop, health, settings storage, declarative UI retrieval and declarative action dispatch. Enabled state is stored in the runtime volume and enabled plugins are restored after a runtime restart. A broken plugin during restore is contained so it cannot prevent runtime startup.

The application-level lifecycle manager remains the policy owner. The runtime is an execution boundary, not a replacement for host compatibility, permission or gateway contracts.

## UI boundary

GET /api/plugins/{plugin_id}/ui is served through the backend. The browser never talks directly to the runtime. Settings and actions use the same authenticated host-to-runtime path, and plugin code is never imported into the core backend process.

## Testing

Runtime policy tests run in src/plugin-runtime/tests/. Backend CI runs the runtime policy suite in addition to backend tests. With the supplied Compose stack, an empty plugin volume produces an empty plugin list instead of a 404 or a backend startup failure.
