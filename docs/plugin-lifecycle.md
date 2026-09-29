# Plugin lifecycle, health and recovery

Issue #270 owns lifecycle orchestration after the API, manifest, gateway, permission and isolated-runtime contracts.

## State machine

Static manifests are discovered before plugin code is loaded:

```text
DISCOVERED -> VALIDATING -> INSTALLED -> STARTING -> RUNNING
     |            |             |            |          |
   INVALID   INCOMPATIBLE     failure    FAILED_START  FAILED_STOP
                    |                       |
                    |                    UNHEALTHY
                    |
             FAILED_INSTALL
                                             |
                                      repeated failures
                                             v
                                        QUARANTINED

INSTALLED/RUNNING/STOPPED <-> DISABLED
```

Invalid and incompatible manifests are contained as data errors and never execute plugin code.

## Runtime and installation boundaries

`PluginLifecycleManager` owns lifecycle state and delegates execution through the `RuntimeController` boundary to the isolated runtime from #267. It does not import plugin modules, pass core credentials, or bypass gateway authorization.

Package integrity is checked against the manifest before the separate `PackageInstaller` boundary is invoked. Plugin storage remains owned by #268.

## Dependency-aware activation

Required dependencies must be installed and running before a dependent plugin starts. API v1 dependency resolution supplies deterministic dependency-first ordering and rejects missing, incompatible or cyclic required dependencies.

## Health, quarantine and recovery

Every health check records its timestamp and resets consecutive failures after a successful check. Repeated start or health failures reach the configurable quarantine threshold; the plugin is then disabled and cannot be started until an administrator explicitly recovers it.

Recovery clears lifecycle failure counters only. It does not grant permissions, change manifest compatibility, or bypass package verification.

## Safe mode and core-startup safety

Global plugin safe mode prevents plugin activation while leaving the core application available for diagnosis. `start_enabled()` contains individual plugin failures and continues processing other plugins, so a broken plugin cannot prevent core startup.

Structured lifecycle logs expose state transitions, failures and recovery events without exposing plugin secrets or internal exceptions to plugins.


## Runtime observability and one-shot plugins

The Plugin Runtime keeps a bounded per-plugin log buffer and exposes it through the authenticated host API. Plugin `stderr` is diagnostic output; plugin `stdout` is reserved for the v1 request/response protocol and is bridged by the runtime.

A one-shot plugin that exits successfully is reported as **completed** rather than being mistaken for a failed/stopped plugin. A non-zero exit is reported as failed with its exit code retained for diagnosis. Enabling a plugin records the administrator user scope used by gateway requests.
