# Plugin Runtime Isolation

Issue #267 defines the complete production runtime isolation contract. The
outer Docker boundary was introduced by #287; this page documents the
additional per-plugin process and network controls now implemented by the
runtime supervisor.

## Topology

Production Compose keeps the Plugin Runtime off the core database network and
connects it to the host through the internal `plugin_gateway` network. The runtime
also has a separate `plugin_egress` network for approved broker operations:

    application + PostgreSQL --- core network
          |
          +--- plugin_gateway (internal Docker network) --- Plugin Runtime
                                                            |
                                                            +-- per-plugin bubblewrap sandbox
                                                            +-- plugin_egress (runtime broker)

The internal network itself has no external default route. The separate egress
attachment does not grant sandboxed workers network access: Bubblewrap creates a
private network namespace for each worker. Runtime HTTP is an implementation
adapter; configured URLs can use local processes or container service names
without changing the packaged SDK. See [gateway and transport](plugin-platform.md).

The repository-root development Compose file supplies a development-only
fallback runtime token. Set `PLUGIN_RUNTIME_DEV_TOKEN` to test a specific
local token. Deployments must always set a unique `PLUGIN_RUNTIME_TOKEN`;
`src/docker-container/compose.yaml` rejects a missing value before startup.

## Development fallback: `NONBUBBLE_ENV`

At startup the runtime executes a real Bubblewrap namespace probe. Its health
response reports probe status, Bubblewrap usability, active isolation mechanism,
sandbox availability, reduced-isolation policy and probe error. Plugin Settings
displays this report when first opened; details and diagnostics show process
status and errors. An unavailable runtime is never reported as fully isolated.

A failed probe blocks plugin start unless the existing explicit fallback is
enabled. Administrators can continue inspecting Plugin Manager and using the
core application and follow its help link here. Fallback reports reduced
process isolation even if the Bubblewrap binary itself is usable.

Inspect probe stderr and runtime container logs, ensure Bubblewrap is installed
in the image, and check host user-namespace and container security policies.
Linux user-namespace/AppArmor restrictions and incompatible container policies
can prevent namespace creation. Adjust deployment policy for that operating
system, recreate the runtime and confirm a successful startup probe before
relying on per-plugin isolation. Binary presence or a running Docker container
does not prove Bubblewrap works.

If bubblewrap cannot run in a development/test environment, set `NONBUBBLE_ENV=true` on the **Plugin Runtime** service. Plugin processes are then launched directly rather than through the per-plugin bubblewrap namespace/filesystem sandbox. Resource limits, environment filtering, package verification, permissions, and the authenticated gateway still apply, as does the outer Docker/container boundary, but the per-plugin bwrap isolation does not.

This is a **development troubleshooting escape hatch, not a production security mode**. Do not enable it when running untrusted plugins. Remove the variable or set it to a false value to restore normal bubblewrap isolation. Accepted true values are `1`, `true`, `yes`, and `on`, case-insensitive.

For repository-root Docker Compose development, add `NONBUBBLE_ENV: "true"` under `plugin-runtime.environment`, then recreate the runtime container.

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

Plugin API v1 defines the host-controlled `network.outbound` capability, but the
current gateway does not expose a general-purpose network forwarding method.
A declaration or approved scope does not create arbitrary socket access in a
Bubblewrap sandbox.

The sandbox uses an isolated network namespace, which means the plugin cannot
directly reach PostgreSQL, the core backend, Docker DNS, the host network or
the public internet. The runtime broker's separate egress network is not shared
with that namespace.

Approved external access is implemented through runtime-owned, narrowly
validated senders rather than direct plugin networking. The current reference
provider can request Discord webhook delivery only when
`PLUGIN_RUNTIME_DISCORD_EGRESS=true`; the runtime validates HTTPS host/path and
message limits before sending. A manifest declaration never grants direct
network sharing to a plugin.

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


## Audit hardening

Plugin package verification enforces bounded compressed package size, entry count, per-file payload size, aggregate uncompressed size, and compression ratio. These limits are configurable on PluginPackageVerifier and apply before plugin execution.

The supervisor drains stdout through the JSON-line gateway bridge and stderr
through structured redacted diagnostics. Diagnostic buffers retain the newest
200 events. Plugin protocol output and stderr are separate streams, not an
unconsumed output sink.

Lifecycle disable and quarantine operations stop running plugin processes through the RuntimeController boundary. Uninstall has explicit package and plugin-storage cleanup boundaries so executable artifacts and namespaced data are not silently orphaned.


## Runtime logs and gateway bridge

The runtime exposes `/plugins/{plugin_id}/logs` to the authenticated host. The application route is administrator-only and the per-plugin Settings dialog displays process status, last exit code, and structured events.

Every event has a monotonic sequence, UTC timestamp, level, stable event name, source, plugin ID, optional correlation ID, message, and bounded scalar metadata. The in-memory buffer retains the newest 200 events per plugin. Lifecycle start/stop/exit, one-shot actions, gateway failures, readiness, and plugin stderr are recorded. Token-, password-, secret-, and webhook-shaped values are redacted before storage or display.

Plugin stdout is reserved for the request protocol and diagnostics belong on stderr; both streams are drained so noisy plugins cannot deadlock. Core operations are forwarded through the private host gateway and are checked against active plugin permission grants.

One-shot action handlers use the same JSON-line mediation. The runtime supplies the initial action values, services any Plugin API requests emitted by the action, and accepts one bounded structured result envelope. This allows a UI action to call domain APIs without receiving the runtime token or bypassing grant checks.

## Plugin frontends

A plugin may declare a frontend bundle in its manifest:

    "frontend": {"entry": "frontend/index.html"}

The runtime serves files from that package through the authenticated application route. The Plugin Manager mounts the entry page in a sandboxed iframe with scripts enabled but without allow-same-origin. This lets a plugin ship a real Vue/Vite application while preventing the plugin page from reading or modifying the host Vue application's DOM, cookies, or local storage.

Frontend code communicates with the host through a small validated postMessage bridge. Supported operations are deliberately narrow: save ordinary settings, save a secret into plugin storage, run a declared plugin action, and request basic plugin context. The parent validates the message source against the specific iframe before processing it.

The existing ui.json declarative UI remains supported for lightweight plugins. A plugin with a frontend declaration uses its own frontend instead of the declarative renderer.

## Plugin secrets and persistent data

Frontend secrets must not be placed in ordinary settings or browser storage. The host exposes a plugin-scoped secret write operation that requires the plugin.storage permission. The value is written through the runtime's namespaced PluginStorage implementation under secrets/<key>.

Plugin storage is quota-limited, path-confined, persistent across package updates,
and owned by the runtime broker. Metadata and stored values have owner-only file
permissions. In Bubblewrap, `/plugin-data` is an empty private filesystem and the
package's legacy settings file is masked. Persistent storage and secrets are
accessible through granted `storage.*`/`settings.get` operations, not a direct
filesystem mount. Each operation rechecks the host grant so revocation applies
to subsequent calls. Deleting a plugin removes package, configuration and storage.

The secret-write bridge stores credentials under `secrets/<key>`. Plugins retrieve
them through the authorized broker; credentials must not be ordinary action
arguments or browser-local storage. Runtime-mediated Discord delivery performs
its own grant, URL and message checks.

NONBUBBLE_ENV=true intentionally weakens this filesystem boundary for development troubleshooting, so it must not be used as a production security mode.
