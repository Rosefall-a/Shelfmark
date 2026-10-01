# Plugin contribution lifecycle audit

Audit base: `plugin-manager` at `08f93511`. This audit changes host/runtime infrastructure and contract tests only; it does not implement reference plugins or advance stages 5–7.

Publication integrates the subsequent authorization fixes on `plugin-manager` at `51f3ef50`, preserving user, registration and live capability checks. Both backend execution helpers delegate to the same lifecycle predicate.

## Activation rule

Enablement expresses the administrator's preference. Every executable contribution requires an enabled, compatible installation whose status is `running` and whose health is `healthy` or `unknown`. An enabled installation that has not started is inactive. Unknown statuses and missing affirmative lifecycle metadata fail closed.

| Lifecycle state | Backend ownership reserved | Executable contributions |
| --- | --- | --- |
| Enabled / installed / stopped | Yes | None |
| Starting | Yes | None |
| Running, compatible and healthy | Yes | Granted contributions |
| Stopping | Yes | None |
| Disabled | Yes | None |
| Failed, including start/stop failures | Yes | None |
| Quarantined | Yes | None |
| Uninstalled | No | None |

The backend applies this rule to UI documents, sandbox/native frontend assets, actions, backend route dispatch, runtime gateway requests, and notification provider discovery/delivery. Gateway requests also require the current installation identity, so an old worker cannot reuse a new installation's grants. Durable provider records and grants are preserved during disable; their registrations are suspended from discovery and delivery until the same installation runs again.

The runtime publishes `starting` and `stopping` before process operations, preserves installation/source/trust metadata, and revokes execution before waiting for cleanup. Only local configuration/storage reads and the ready handshake are permitted during startup; executable contributions remain blocked. It tracks action/route subprocesses as well as the main process. Stop terminates every tracked worker and its process group, and attempts remaining workers/plugins even if one cleanup fails. Start failures attempt partial-process cleanup. Quarantine cannot be cleared by stop or disable, including when cleanup fails. The async lifecycle manager serializes startup, shutdown and health checks per plugin so pending startup cannot revive workers after disable.

Production events currently use `events.poll`, rather than a separate durable subscription registry. Polling is gated at both runtime and host boundaries. Background work runs in supervised plugin processes; stopping those processes stops their polling loops and tasks. This audit does not add a new event bus or background scheduler.

## Frontend reconciliation

All navigation, Settings sections, overlays, dialogs, contextual actions, extension slots, routes and replacements derive from the same active installation set. Open dialogs and directly opened plugin pages are also withdrawn. Registry refreshes ignore stale responses and clear contributions when authoritative state cannot be obtained. Logout clears all contributions and invalidates outstanding requests.

The authenticated frontend refreshes lifecycle state every five seconds; local Plugin Manager operations also refresh immediately after completion. The server enforces lifecycle state on every request, independently of that polling delay.

Native Vue bundles are privileged modules in the host browser realm. Removing an imported or pending production native bundle reloads the frontend to terminate that realm, including arbitrary timers and retained code outside SDK cleanup callbacks. Pending activation and retained SDK methods are revoked immediately; registered components, styles and cleanup callbacks are removed. Failed native imports remain tracked so subsequent disable/quarantine still tears down their realm. Plugin authors should register cleanup callbacks, but lifecycle shutdown does not rely exclusively on their cooperation. Native bundle removal/update can therefore cause a full frontend reload.

## Conflict policy

* Backend routes of disabled and quarantined installations remain reserved. Multiple matching declarations fail with a conflict; no owner is selected by enumeration order. Installation rejects method/path overlaps between plugins and with the application's registered routes, including host catchalls. Install/update mutations serialize ownership checks with package changes.
* Frontend routes use `/plugins/<plugin-id>/...`. Duplicate IDs and paths inside one plugin are rejected. A route cannot shadow a different page's direct identifier. Multiple aliases of one page choose the lexically smallest path.
* Navigation and extension IDs are scoped to their plugin; equal IDs in different plugins can coexist. Duplicate IDs inside one document are rejected. Settings' existing global section conflicts keep host sections reserved and select plugin contributions using the explicit order below.
* Page replacements select by ascending `order`, then lexicographic plugin ID, then contribution ID. The same policy sorts extension slots, including legacy Home replacements. Generated replacement slot keys have a separate prefix to prevent collisions with extension keys. Comparisons do not depend on locale or discovery order.

## Regression coverage

`src/backend/tests/test_plugin_contribution_lifecycle_e2e.py` runs host HTTP requests against a real authenticated runtime HTTP service and its production registry. It checks route execution, UI/native assets, action dispatch, event polling, provider registration/discovery, ownership retention, and quarantine preservation across lifecycle transitions. Only process execution and database/authentication dependencies are substituted.

`src/frontend/src/tests/pluginExtensions.test.ts` exercises the HTTP-client-to-registry/native reconciliation path across transitions and reversed plugin discovery order. `pluginNative.test.ts` covers delayed import/activation cancellation, revoked host methods, cleanup, and production realm teardown. Runtime regressions include cancellation of a real in-flight subprocess and cleanup failure containment. Conflict tests permute declaration order and cover duplicate navigation/extension IDs, duplicate route IDs/paths, and host route overlap.

The HTTP and registry regressions do not substitute for a production Linux/container smoke run. Windows cannot verify Unix storage mode bits or the existing Linux `preexec_fn` sandbox test.

## Validation

Validated on the Windows development host:

* Backend plugin suite after integration: 214 passed, 2 skipped (external plugin repository not configured), 150 unrelated tests deselected.
* Runtime suite after integration: 50 passed; the 2 existing Unix-only failures were reproduced on the unchanged `plugin-manager` baseline and excluded from the Windows run.
* Frontend: 58 tests passed; TypeScript, ESLint, formatting and production build checks passed.
* Backend mypy: all 186 source files passed. Focused Ruff checks passed; broader Ruff still reports existing FastAPI argument-default and lifecycle duplicate-helper import findings. Pylint on touched backend modules reported no errors/fatal findings; the repository still has existing convention/refactor/warning findings.

No production container smoke test was run because Docker is unavailable on this host.
