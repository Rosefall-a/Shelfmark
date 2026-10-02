# Plugin platform architecture

The host owns the Plugin API v1, installation policy and gateway. Plugin packages
are independent consumers. They do not import host Python modules, SQLAlchemy
models, database sessions or application filesystem paths.

## Boundaries and authoritative state

| Component | Responsibility | Persistent state |
| --- | --- | --- |
| Host Plugin Manager | Package verification, consent, inventory, catalogue tracking, update policy and recovery | Atomic manager/catalogue files in the host data volume; staged package bytes |
| Host PostgreSQL | Installation-scoped grants, permission requests, scoped clients, provider registrations and lifecycle commit receipts | Application database |
| Host gateway | Authenticated identity, live installation checks, method/capability mapping and user ownership | Uses host-owned grants; exposes public representations |
| Plugin Runtime | Verified executable packages, workers, process health, brokered configuration, storage and secrets | Separate runtime volume, active packages and retained package history |
| Plugin | Declared operations and its own data schema | Plugin-scoped keys through the granted API |
| Browser manager | Render backend inventory and host-owned permission review | No authority to create grants or infer installation from a running process |

`GET /api/plugins` reconciles runtime observations with durable host inventory.
An unreachable runtime leaves identity, installed version/digest, enablement,
source, staged releases and grants available. Live status and health become
unknown, runtime availability becomes false, and active isolation is unavailable.
Remote catalogues enrich the UI independently; a slow or failed catalogue must
not hide an installed plugin. Explicit uninstall removes its inventory record.

## Deployed gateway path

1. The packaged SDK emits one JSON object on stdout and reads one response from stdin.
2. The runtime supplies the persisted plugin/installation and authenticated action
   user, or the activation user for a background worker. Plugins never receive the
   runtime token. Caller payloads cannot replace this identity.
3. Runtime-local storage/settings operations call the host's `capabilities.check`
   before accessing the broker's private state. Domain calls use the same host
   gateway at `/api/plugins/runtime/gateway`.
4. The host checks transport authentication, executable installation, installation
   identity, active user, method/capability compatibility and persisted scoped grant.
5. The host returns a bounded public representation. A declaration, UI checkbox,
   capability hierarchy or reachable hostname is not authorization by itself.

This retains the existing JSON-line and HTTP adapters. Container DNS and addresses
are deployment settings, not Plugin API concepts. `PLUGIN_RUNTIME_URL` configures
host-to-runtime HTTP; `PLUGIN_GATEWAY_URL` configures runtime-to-host HTTP;
`PLUGIN_RUNTIME_TOKEN` authenticates that private transport. Localhost, Compose
service names and other configured addresses carry the same wire contract.

The contract-only bootstrap authenticator and negotiation DTOs remain available
in the host library. The deployed runtime uses the dedicated shared runtime token;
it does not currently provision bootstrap/session credentials for each worker.

## Version, correlation and errors

Workers may send `api_version: "v1"` and a UUID `request_id`. Legacy v1 workers may
omit both: v1 is the default and the runtime generates correlation. An unsupported
major version is rejected before dispatch. Capability semantic versions are checked
independently through existing grants. `capabilities.check` returns an affirmative
decision only for an authorized capability; it does not enumerate secret grant state.

Success keeps the existing `payload` field and adds `api_version` and `request_id`.
Host failures retain their HTTP status and `detail`, with a structured `ErrorEnvelope`
under `error`. The runtime preserves its `code`, safe `message` and correlation as
`error_detail`, and retains a string `error` for existing SDKs:

```json
{
  "api_version": "v1",
  "request_id": "f61c263e-305b-4b4e-b6e4-9b1cd87c4ffc",
  "error": "permission games.read has not been granted",
  "error_detail": {
    "api_version": "v1",
    "request_id": "f61c263e-305b-4b4e-b6e4-9b1cd87c4ffc",
    "code": "forbidden",
    "message": "permission games.read has not been granted",
    "details": []
  }
}
```

Invalid input, incompatibility, lifecycle conflicts, denied permission, unavailable
services and internal failures remain distinct. Unexpected exceptions produce a
safe generic message, with correlated diagnostics in host logs. Requests rejected
by HTTP body/model validation may fail before this gateway envelope is constructed.

Host domain dispatch has an eight-second deadline, inside the runtime bridge's
ten-second HTTP timeout. Worker actions have a separate bounded execution deadline.
Read-only synchronous metadata-provider work runs outside the host event loop;
timing out that await does not forcibly terminate the provider's thread. See
[capability-specific limits](plugin-capabilities.md).

Runtime health advertises `api_version`, `supported_api_versions`, private HTTP
transport and worker JSON-line transport alongside the actual isolation probe.
Worker `lifecycle.ready` is recorded as a diagnostic event. Startup health checks
process survival after a grace period; they cannot certify every operation's
semantic correctness. Conformance tests additionally exercise readiness and real
plugin operations.

## Lifecycle and third-party compatibility

All acquisition paths use the existing verifier and consent flow. Package
publication and data deletion are separate transactions. New scopes stage an
update while the old release runs; denial persists for that candidate digest.
Rollback changes executable packages and preserves plugin data. Reinstall uses
the exact installed release. Uninstall and confirmed purge remove owned persistent
state. Neither disable nor an ordinary update resets secrets or re-grants revoked scopes.

See [lifecycle](plugin-lifecycle.md), [updates and rollback](plugin-updates.md),
[permissions](plugin-permissions.md), [storage](plugin-storage.md),
[runtime isolation](plugin-runtime.md), [UI](plugin-ui.md),
[remote management](plugin-management-api.md), [plugin development](plugin-development.md)
and [conformance](plugin-conformance.md).
