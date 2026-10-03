# Plugin Runtime

This directory contains the production Plugin Runtime container and its
per-plugin sandbox supervisor.

## Runtime contract

The runtime is a separate service from the core application. Plugins are
untrusted extensions and receive neither the core process environment nor core
credentials. The supervisor launches each plugin as a separate process group
inside an unprivileged bubblewrap sandbox.

Each sandbox gets:
- a private PID, IPC, UTS and network namespace;
- a private writable plugin directory;
- read-only runtime libraries;
- a private /tmp;
- a minimal device/proc view;
- explicit, non-inherited environment variables;
- CPU, address-space, open-file and process-count limits.

The Docker service additionally has no core database-network membership, no host port,
no host filesystem or Docker socket, a read-only root filesystem, dropped
capabilities, no-new-privileges, and bounded container resources.

## Development fallback: `NONBUBBLE_ENV`

If bubblewrap cannot run in a development/test environment, set `NONBUBBLE_ENV=true` on the **Plugin Runtime** service. This launches plugin processes directly instead of using the per-plugin bubblewrap namespace and filesystem sandbox. Resource limits, plugin environment filtering, the runtime service/container boundary, package verification, permissions, and gateway authorization still apply, but the per-plugin bwrap isolation does not.

This is a **development troubleshooting escape hatch, not a production security mode**. Do not enable it for deployments that run untrusted plugins. Remove the variable or set it to a false value to restore the normal bubblewrap sandbox. Accepted true values are `1`, `true`, `yes`, and `on` (case-insensitive).

For Docker Compose development, add `NONBUBBLE_ENV: "true"` to the `plugin-runtime.environment` section and recreate the runtime container.

## Network policy

Outbound network access is default-deny. A plugin declaration may name
allowed hosts and ports, but the runtime rejects the declaration unless the
gateway has granted the network.outbound capability.

The sandbox itself always starts with an isolated network namespace, so a
plugin cannot bypass the policy with a raw socket or by resolving Docker
services. An approved egress broker/proxy is a separate integration point; it
must be the only mechanism used to turn an approved declaration into external
connectivity.

## Security boundaries

- #265 owns authenticated core/gateway trust and transport.
- #266 owns capability authorization and revocation.
- #267 owns the runtime isolation contract.
- #268 owns persistent per-plugin storage.
- #270 owns lifecycle, health, quarantine and safe mode.

The runtime never treats a plugin manifest as a capability grant.


## Persistent plugin storage

Persistent data is owned by the runtime under `/var/lib/unnamed-tracking/plugins` and is mounted as a dedicated Docker volume. Each plugin is bound to its own namespace by `PluginStorage`; the plugin cannot choose another namespace.

The storage API provides atomic byte writes, reads, deletion, deterministic key listing, schema-version metadata, quota enforcement, namespace-bound backup/restore and uninstall cleanup. It rejects path traversal and symlinks and never exposes PostgreSQL or core application filesystem paths.

The runtime storage volume is intentionally not mounted into the core application service. Deployment backup procedures must include the plugin storage volume alongside the application data and PostgreSQL backup.
