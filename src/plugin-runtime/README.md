# Plugin Runtime

This directory contains the isolated production Plugin Runtime container
introduced by issue #287.

The runtime is deliberately a separate service from the core application.
The current process is only a bootstrap/health boundary; plugin execution and
the authenticated gateway are implemented by later Plugin Manager issues.

## Isolation guarantees

The production Compose service:
- has its own dedicated Docker network marked internal;
- is not attached to the core application/database network;
- receives no core environment, database URL, application secret, or host data volume;
- does not mount the Docker socket;
- runs as an unprivileged user;
- uses a read-only root filesystem with a small temporary filesystem;
- drops all Linux capabilities and enables no-new-privileges;
- has bounded PID, CPU, and memory resources;
- exposes no host port.

The absence of a shared core network is intentional. Authenticated
core-to-gateway transport will be wired by issue #265; this issue does not
create an unauthenticated network path from plugins into the core application.

## Future work

Issue #288 defines per-plugin process isolation and crash/resource containment.
Issue #289 defines declared outbound network access and its approval policy.
Issue #265 owns authenticated core/gateway trust and transport.
Issue #266 owns capability authorization.
