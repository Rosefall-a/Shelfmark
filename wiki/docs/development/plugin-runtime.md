# Plugin Runtime Isolation

Issue #267 defines the complete production runtime isolation contract. The
outer Docker boundary was introduced by #287; this page documents the
additional per-plugin process and network controls now implemented by the
runtime supervisor.

## Topology

Production Compose keeps the Plugin Runtime on a dedicated Docker network
marked internal:

    core application + PostgreSQL
             |
             | no shared runtime network
             X
             |
       Plugin Runtime
             |
             +-- plugin_runtime (internal Docker network)
                    |
                    +-- per-plugin bubblewrap sandbox

Docker's internal network has no default route to external networks, and the
runtime is not attached to the core application's network. This prevents
Docker service discovery from becoming an accidental backend/database access
path.

## Per-plugin process isolation

PluginSupervisor launches every plugin separately. Plugin IDs are validated,
duplicate processes are rejected, and each plugin receives a private
directory.

Bubblewrap creates separate mount, user, PID, IPC, UTS and network namespaces.
The plugin sees only the runtime libraries explicitly mounted read-only, its
own working directory, a minimal device/proc view and a private /tmp.

Each process also gets:
- CPU time limit;
- address-space limit;
- open-file limit;
- child-process limit;
- independent process group for termination;
- parent-death handling through bubblewrap.

The outer Docker service retains its container-level PID, CPU and memory
limits, so the process-level limits are defense in depth.

## Environment and data isolation

Plugin subprocesses receive a fresh environment rather than inheriting the
runtime environment. Core credentials such as DATABASE_URL, SECRET_KEY,
database passwords, Docker host configuration and gateway credentials are
explicitly rejected.

There are no host filesystem mounts, application-data mounts or Docker socket
mounts on the production runtime service. Plugin storage is a separate
contract owned by #268.

## Outbound network policy

Outbound access is default-deny.

A plugin may declare:
- allowed DNS hostnames;
- allowed destination ports;
- the network.outbound capability requested for administrator approval.

A declaration without an active gateway grant is rejected. An empty
declaration remains valid and receives no external network.

The sandbox uses an isolated network namespace, which means the plugin cannot
directly reach PostgreSQL, the core backend, Docker DNS, the host network or
the public internet. Docker's internal runtime network also has no external
default gateway.

Approved external access must be implemented through a dedicated egress
broker/proxy. The runtime contract does not grant direct network sharing to a
plugin merely because its manifest requests it. This prevents a future
network implementation from accidentally turning an approved host list into
unrestricted socket access.

DNS is therefore deny-by-default rather than merely filtered after
resolution. This also prevents a plugin from using an unapproved Docker
service name or raw IP address as an alternate route.

## Gateway and permission boundaries

The runtime does not replace the authenticated gateway:

- #265 authenticates application-to-gateway traffic and binds trusted
  application/plugin/installation context.
- #266 evaluates capability grants using that authenticated context.
- The runtime consumes the resulting policy and never treats a manifest
  declaration as authorization.

Plugin UI/browser traffic must continue through the authenticated gateway;
plugin processes are never published as browser-facing ports.

## Failure and compatibility behavior

Invalid plugin IDs, empty commands, reserved environment variables, invalid
resource limits and unapproved network declarations are rejected before a
process is started.

Stopping a plugin terminates its process group and removes its private
working directory. A crashed plugin therefore does not share a process group
with another plugin.

The runtime image is deliberately independent of the core backend Python
environment. Future plugin SDK/gateway changes can evolve behind the
existing #263-#266 contracts without granting plugins direct application
access.

## Tests and CI

src/plugin-runtime/tests/test_runtime.py covers:
- core-secret environment rejection;
- plugin ID and command validation;
- default-deny networking;
- administrator capability requirement for declared outbound access;
- port validation;
- resource-limit validation.

The backend CI job runs this suite in addition to the existing backend tests,
migration validation, mypy and pylint. Production Docker CI also builds the
runtime image, including its bubblewrap dependency.
