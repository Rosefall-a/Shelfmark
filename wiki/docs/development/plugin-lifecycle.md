# Plugin lifecycle

Plugin lifecycle management spans the application Plugin Manager and the isolated runtime.

The manager previews and validates manifests, verifies and installs packages, resolves required dependencies deterministically, and delegates process execution to the isolated runtime. It never imports plugin code into the core backend.

## Lifecycle and failure states

The manager distinguishes discovery, validation, installation, starting/running, stopping/disabling, install/start/stop failures, unhealthy state, and quarantine. Invalid or incompatible manifests never activate. Installation failures and runtime stop failures remain observable failure states instead of being silently rewritten as successful lifecycle transitions.

Repeated start, install, stop, or health failures reach the configured quarantine threshold; quarantine disables the plugin, stops its runtime process when one is running, and requires explicit administrator recovery.

## Health and recovery

Health checks track consecutive failures and reset the counter after a successful check. Recovery clears lifecycle failure counters only; it does not change capability grants, compatibility decisions, or package integrity requirements.

## Runtime and security boundaries

Execution is delegated through the isolated runtime boundary from #267. The lifecycle manager does not import plugin code or bypass gateway authorization. Package integrity is checked before installation.

## Safe mode and diagnostics

Global plugin safe mode prevents activation while keeping the core application available for diagnosis. Startup activation contains individual plugin failures so a broken extension cannot block core startup. Structured lifecycle logs provide bounded administrator diagnostics without exposing plugin secrets.

## Application integration

The application exposes the lifecycle endpoints under /api/plugins and delegates execution to plugin-runtime through src/backend/src/plugin_api/runtime_client.py. The runtime persists enabled state in its plugin volume and restores enabled packages after restart. Plugin failures are returned as contained lifecycle errors and do not make core application startup depend on plugin health.


## Installation and activation

The canonical installer records the administrator's explicit permission choices and resolves dependencies before preparing a package in the runtime. Prepared installations remain disabled until permission decisions commit and the runtime transaction completes. New installations then start automatically and receive a health check; updates restart only when the predecessor was enabled. Failed activation remains observable as `failed_activation` or `unhealthy`. Runtime start and stop preserve installation identity, publisher trust, and acquisition source metadata. `running` is reported only while the isolated plugin process is alive; an enabled plugin whose process exits is reported as `failed` rather than falsely as healthy.

An interrupted installation transaction remains disabled across runtime restarts and cannot be enabled before completion. See [Plugin updates](plugin-updates.md) for transaction recovery and grant-retention rules.

## Contribution lifecycle

Contributions execute only while their installation is enabled, compatible and running. Starting, stopping, failed, disabled and quarantined plugins retain reserved backend routes, but cannot execute them. Their navigation, Settings contributions, overlays, dialogs, contextual actions, page extensions and replacements disappear. Event polling, provider registration/discovery/delivery, and supervised workers also stop. Provider records and grants remain available for reactivation of the same installation.

The frontend reconciles lifecycle state every five seconds and after local Plugin Manager operations. Server execution checks take effect immediately. Removing a privileged native frontend bundle reloads the frontend to terminate its JavaScript realm; native cleanup callbacks alone cannot stop arbitrary retained code. Stop/disable preserve quarantine.

Duplicate IDs within a plugin document and duplicate route paths are rejected. IDs are scoped to their plugin. Replacement conflicts resolve by ascending order, plugin ID, then contribution ID using lexicographic comparisons. Plugin host-route claims cannot overlap existing plugins or the application's registered routes, including catchalls; disabled and quarantined owners still reserve their declarations.
