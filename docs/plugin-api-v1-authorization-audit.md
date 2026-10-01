# Plugin API v1 authorization audit

Scope: runtime capability enforcement only. Stages 5–7, external plugin implementations,
deployment redesign, and new client-authentication transports are not started by this audit.

## Actual request trace

The HTTP integration tests exercise both runtime and frontend requests:

1. A browser sends `POST /api/plugins/{plugin_id}/actions/{action_id}` with its real
   persisted session cookie. `get_current_user` resolves the application user. The
   host replaces browser-supplied `_plugin_context` and passes the authenticated user
   separately to the runtime action transport.
2. `PluginRegistry.action` passes that user to `PluginSupervisor.execute`. The broker
   handles the plugin's `sessions.list` request and attaches installation identity
   from its own installation map. Plugin payloads cannot supply the broker's user
   or installation identity.
3. `POST /api/plugins/runtime/gateway` validates the runtime token, resolves the live
   registry installation, requires an executable lifecycle state, matches the exact
   installation UUID, and checks that the application user is active.
4. `dispatch_gateway_request` maps `sessions.list` to `sessions.read`. The caller's
   requested capability must imply that operation's capability.
5. `has_capability_grant` queries persisted `PluginPermissionGrant` rows, matching
   plugin ID, installation UUID, capability version, active revocation state, user
   scope, and device scope. Canonical parent grants can match a child; children
   cannot match parents or siblings. `api.full` requires its own explicit grant.
6. The session domain query adds `UserSession.user_id == user_id`. Only minimized
   session metadata is returned. Possession of a grant does not select another user's
   domain rows through a payload override.

The runtime broker-to-host transport in the tests sends actual HTTP requests through
FastAPI's ASGI transport. Authentication, grant resolution, revocation endpoints, and
domain SQL are real. SQLite holds real production ORM rows; a small async adapter
wraps its synchronous driver. Only the isolated runtime transport/process output is
substituted; no grant lookup or authorization decision is mocked.

## Findings and corrections

| Before the audit | Enforced behavior |
| --- | --- |
| Persisted grant lookup omitted device scope. | A device-bound grant requires matching authenticated device context. Browser/runtime requests have no authenticated device and can use only device-unscoped grants. |
| The runtime gateway accepted an old installation UUID if that UUID still had a grant. | Every request matches the current live installation before querying grants. |
| Runtime domain dispatch did not check disabled/failed/quarantined installations. | Host entrypoints share an affirmative lifecycle policy; unknown/missing state fails closed. |
| UI/list effective grants included device-bound grants and unavailable installations. | Browser effective capabilities exclude device-bound grants and are empty for unavailable installations. Native assets require `frontend.native`; replacements require the exact home/settings capability. |
| Action requests ignored capability versions and used the installation activator's user for runtime domain calls. | Action capability versions are validated and matched; the authenticated request user travels separately through action execution. |
| Local storage used manifest permission declarations, and local settings did not query grants. | The broker calls the host's `capabilities.check` before each local operation. The operation chooses its required capability; changing a request's capability cannot change this requirement. |
| Persistent storage was directly mounted into plugin sandboxes. | Persistent storage remains broker-owned. `/plugin-data` is ephemeral, and mutable `.settings.json` is masked in the sandbox. |
| Runtime Discord delivery checked only manifest capability declarations. | Delivery rechecks its own `notifications.send` or `notification_providers.deliver` persisted grant before egress. One does not substitute for the other. |
| Provider delivery relied on an earlier destination lookup. | Delivery rechecks the active registration, user, live installation and delivery grant, including revocation/reinstallation between lookup and delivery. |

Manifest declarations, permission requests, UI documents, and backend route declarations
describe requested behavior. None creates an authorization decision. Backend route
ownership is resolved before grant checks, and namespaced/host routes require
`backend.routes.plugin`/`backend.routes.host` respectively. A route grant does not
authorize domain operations issued from its handler.

## Regression coverage

`src/backend/tests/test_plugin_authorization_http.py` covers declaration-only denial,
stale installations, exact plugin/installation/user/version scope, device denial and
spoof rejection, parent/child direction, explicit `api.full`, real HTTP revocation,
disabled/failed/quarantined/incompatible/unknown lifecycle states, frontend activation
and page-specific replacements, both backend route scopes, notification persistence,
provider registration/delivery, frontend-to-runtime user propagation, and runtime-local
storage/settings and Discord egress through the HTTP host gateway.

`src/plugin-runtime/tests/test_authorization.py` additionally checks malformed/negative
host decisions, loss of host configuration, and absence of direct persistent storage
or settings mounts. Existing unit and Linux process tests retain their assertions.

Run backend checks with the repository's PostgreSQL test database and environment:

```sh
cd src/backend
python -m pytest tests -q
mypy --config-file pyproject.toml src
pylint --rcfile=pyproject.toml src
```

Run the runtime suite on Linux:

```sh
cd src/plugin-runtime
PYTHONPATH=. python -m pytest tests -q
```

Validation for this audit: the complete backend suite passed with 341 tests and two
existing skips against an isolated PostgreSQL database; the runtime suite passed all
45 tests on Linux. Mypy passed all 186 source files. Pylint scored 9.14/10, above the
unchanged CI threshold of 9.0. Focused Ruff checks passed; the route module retains
its 60 pre-existing FastAPI-default warnings with no new findings. CI files were not
changed.

## Limits and compatibility

- `capabilities.check` is a side-effect-free host authorization query for the broker.
  Its response is not a reusable grant; each subsequent operation rechecks authorization.
- Runtime action transport now carries the authenticated user separately. Deploy
  matching host/runtime versions together.
- Direct filesystem persistence through `PLUGIN_DATA_DIR` is no longer supported in
  the sandbox. Consumers must use granted `storage.*` and `settings.get` APIs.
- Device client credentials are issued/persisted, but no production request transport
  authenticates them yet. A caller-supplied device UUID is not accepted as evidence of
  device identity. Adding that transport remains outside this audit.
- Revocation stops the next authorization check. It cannot undo a completed operation
  or retract data already returned, and it does not cancel an already executing operation.
- `frontend.native` intentionally executes privileged code in the host document;
  capability checks gate activation/assets and mediated operations. This audit does
  not claim that already loaded native JavaScript becomes a security sandbox.
- `NONBUBBLE_ENV` remains the existing explicit development escape hatch. It disables
  filesystem/process isolation and must not be used for untrusted plugins. The
  authoritative API checks still run, but arbitrary direct filesystem access in this
  mode is outside the mediated API guarantee. No stages 5–7 isolation work is introduced.
