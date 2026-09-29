# Plugin Runtime Isolation

Issue #287 establishes the production container and network boundary for the
Plugin Runtime.

## Topology

The production Compose deployment keeps the Plugin Runtime on a dedicated
Docker network:

    core application + PostgreSQL
             |
             | no shared runtime network
             X
             |
       Plugin Runtime
             |
             +-- plugin_runtime (internal Docker network)

The runtime is intentionally not attached to the application's default/core
network. This prevents plugins from resolving or directly connecting to the
core backend or PostgreSQL through Docker service discovery.

Authenticated gateway transport is deliberately left for issue #265; this
issue does not introduce an unauthenticated shortcut merely to make the
bootstrap container reachable.

## Container hardening

The production service runs with:
- an unprivileged UID/GID;
- a read-only root filesystem;
- a tmpfs for temporary files;
- all Linux capabilities dropped;
- no-new-privileges;
- bounded PIDs, memory and CPU;
- no host filesystem or Docker socket mounts;
- no host port publication;
- no core environment variables.

The runtime image contains only Python and the bootstrap runtime process. It
does not install application dependencies or copy the core backend.

## Scope boundaries

Issue #287 establishes the outer container boundary only.
- #288 defines per-plugin process isolation and crash/resource containment.
- #289 defines declared outbound network access and its approval policy.
- #265 owns authenticated core/gateway trust and transport.
- #266 owns capability authorization once a trusted request reaches the gateway.
