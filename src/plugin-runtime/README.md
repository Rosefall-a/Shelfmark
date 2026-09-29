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
