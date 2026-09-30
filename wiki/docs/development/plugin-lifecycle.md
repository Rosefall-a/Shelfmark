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

Newly installed plugins are disabled by default. Installation records the administrator's contextual consent choices and does not activate the plugin. An administrator must explicitly enable it. `running` is reported only while the isolated plugin process is alive; an enabled plugin whose process exits is reported as `stopped` rather than falsely as healthy.
