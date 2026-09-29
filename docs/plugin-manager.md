# Plugin Manager — implementation roadmap

This document is the working implementation plan for the plugin platform described by issue #262. It intentionally starts with architecture, contracts, isolation, permissions, storage, UI, and lifecycle rather than immediately shipping third-party plugins.

## Design goal

Unnamed Tracking should become an extension platform without requiring third-party code to run inside the core backend or receive core environment variables, database credentials, application secrets, or unrestricted filesystem access.

The initial production topology should be:

```
Unnamed Tracking
  ├── frontend
  └── backend
          │
          │ authenticated Plugin Gateway protocol
          ▼
    Plugin Runtime container
      ├── Plugin Manager/Gateway
      └── isolated plugin runtimes
```

The plugin runtime owns plugin execution. The core application owns the authoritative data/services. Plugins communicate through a versioned, capability-scoped API.

## Non-negotiable requirements

- [ ] Every plugin runs outside the core backend process.
- [ ] The plugin runtime is a separate production container/service.
- [ ] Plugins cannot receive the core application's environment wholesale.
- [ ] Plugins cannot directly access the core database.
- [ ] Plugins cannot access the Docker socket or arbitrary host files.
- [ ] Plugin communication uses an authenticated, versioned gateway protocol.
- [ ] Every plugin has a stable identity and installation identity.
- [ ] Every permission is explicit, inspectable, and revocable.
- [ ] Plugins request capabilities; administrators grant them.
- [ ] Core application services remain the authority for users, games, media, notifications, authorization, configuration, and jobs.
- [ ] Plugin persistent data is namespaced per plugin.
- [ ] Plugin UI is a first-class protocol, not an afterthought.
- [ ] Plugins can expose declarative settings/forms/actions/pages through schemas rendered by the native frontend.
- [ ] Arbitrary plugin frontend code, if supported later, is separately sandboxed and cannot bypass the plugin gateway.
- [ ] Plugin failures cannot take down the core application.
- [ ] Plugin updates are staged and rollback-capable.
- [ ] Incompatible or repeatedly failing plugins can be quarantined automatically.
- [ ] Plugin code cannot alter the core Alembic migration graph.
- [ ] The public Plugin SDK is versioned independently of the application version.

## Required implementation areas

### A. Plugin protocol and manifest

- [ ] Define manifest format.
- [ ] Define plugin ID, installation ID, display metadata, version, SDK compatibility and capability declarations.
- [ ] Define application compatibility rules.
- [ ] Define capability API versions independently from application versions.
- [ ] Define plugin dependency and optional-dependency metadata.
- [ ] Define permission declarations and human-readable explanations.
- [ ] Define plugin UI declarations.
- [ ] Define storage requirements and optional quotas.
- [ ] Define integrity/signature/checksum metadata.
- [ ] Validate manifests without executing plugin code.

### B. Plugin gateway

- [ ] Define authenticated core ↔ gateway handshake.
- [ ] Give the application a stable installation identity.
- [ ] Give the gateway its own trust identity.
- [ ] Do not treat a configured URL/IP as sufficient authentication.
- [ ] Define gateway protocol version negotiation.
- [ ] Define plugin authentication to the gateway.
- [ ] Define request identity: application, plugin, installation, user context.
- [ ] Define request authorization from granted capabilities.
- [ ] Define rate limits and payload limits.
- [ ] Define audit logging.
- [ ] Define API error contracts.
- [ ] Define compatibility/error behavior when a core API is unavailable.

### C. Capability API

Initial capability families should be deliberately small:

- [ ] users.read
- [ ] users.profile.read
- [ ] games.read
- [ ] games.write
- [ ] media.read
- [ ] media.write
- [ ] notifications.send
- [ ] events.subscribe
- [ ] plugin.storage
- [ ] plugin.settings

Later candidates:

- [ ] calendar
- [ ] import/export
- [ ] achievements
- [ ] game actions
- [ ] scheduled tasks
- [ ] metadata providers
- [ ] notification providers
- [ ] authentication integrations

The gateway must expose stable DTOs/service contracts rather than SQLAlchemy models or database queries.

### D. Central extension coordinators

Core functionality must own orchestration while plugins provide implementations.

- [ ] NotificationCoordinator
  - [ ] Keep notification generation in core.
  - [ ] Keep user notification preferences in core.
  - [ ] Keep retries/delivery state in core.
  - [ ] Allow plugin notification providers to register through the gateway.
- [ ] MetadataProviderRegistry
  - [ ] Keep provider selection/priority semantics in core.
  - [ ] Allow plugin metadata providers through the gateway.
- [ ] EventBus
  - [ ] Define stable event DTOs.
  - [ ] Prevent live ORM objects crossing the boundary.
  - [ ] Support filtered subscriptions.
- [ ] Import/export coordinator.
- [ ] Calendar/integration coordinators where appropriate.
- [ ] Job/task coordinator for approved plugin jobs.

Existing PRs #238 (notification providers) and #242 (metadata provider work) should be treated as reference extension seams. Do not duplicate those registries in the plugin framework.

### E. Namespaced storage

Logical plugin storage must be isolated:

```
plugins/<plugin-id>/
    data/
    cache/
    generated/
```

The exact host/container paths may differ; the plugin must only see its own namespace.

- [x] Define storage API.
- [x] Define quotas.
- [x] Define backup/restore semantics.
- [x] Define uninstall cleanup semantics.
- [x] Define plugin data versioning.
- [x] Define the initial byte-oriented storage API; structured JSON remains a plugin-owned encoding.
- [x] Never expose the core database through the storage API.
- [x] Never allow plugin-controlled migrations against core tables.

### F. Plugin UI protocol

Plugin UI is required from the first usable SDK.

- [ ] Define declarative schema for settings.
- [ ] Define native form controls.
- [ ] Define secrets/password controls.
- [ ] Define validation rules.
- [ ] Define select/multi-select controls.
- [ ] Define test/submit actions.
- [ ] Define tables/lists.
- [ ] Define dialogs and confirmations.
- [ ] Define plugin menu entries.
- [ ] Define plugin pages.
- [ ] Define plugin actions.
- [ ] Define loading/error/empty states.
- [ ] Define UI API versioning.
- [ ] Render schemas with native frontend components.
- [ ] Ensure frontend never receives plugin secrets unless explicitly required.
- [ ] Later: define a separate sandboxed custom-frontend protocol for genuinely complex plugin UIs.

### G. Plugin lifecycle

Required state machine:

```
DISCOVERED
  ↓
VALIDATING
  ↓
INSTALLED
  ↓
STARTING
  ↓
HEALTHY / RUNNING

Failure states:
INVALID
INCOMPATIBLE
FAILED_START
UNHEALTHY
DISABLED
QUARANTINED
```

- [ ] Implement discovery.
- [ ] Implement validation.
- [ ] Implement install.
- [ ] Implement enable/disable.
- [ ] Implement start/stop/restart.
- [ ] Implement health checks.
- [ ] Implement structured plugin logs.
- [ ] Track consecutive failures.
- [ ] Automatically quarantine repeatedly failing plugins.
- [ ] Ensure a quarantined plugin cannot block core startup.
- [ ] Add global plugin safe mode.
- [ ] Add admin controls to retry/unquarantine plugins.

### H. Packaging, updates and rollback

- [x] Define plugin package format.
- [x] Verify package integrity and publisher signatures before activation.
- [x] Validate dependencies before activation.
- [x] Stage new versions without replacing the active version.
- [x] Start and health-check staged versions.
- [x] Atomically activate only after validation.
- [x] Retain the previous known-good version.
- [x] Automatically roll back failed upgrades.
- [x] Keep plugin data independent from plugin executable versions.
- [x] Define SDK/application compatibility handling.
- [x] Do not block a core application update because a plugin is incompatible; disable/quarantine the plugin and report why.

### I. Permissions and scoped identity

- [ ] Define permission vocabulary.
- [ ] Define administrator approval flow.
- [ ] Display requested permissions before installation.
- [ ] Store grants per plugin installation.
- [ ] Allow individual grants to be revoked.
- [ ] Enforce permissions at the gateway, not merely in plugin UI.
- [ ] Define user-context permissions.
- [ ] Define whether a plugin acts as itself, as a user, or both.
- [ ] Replace broad user API tokens for supported integrations with scoped plugin identities where practical.
- [ ] Define short-lived gateway credentials where appropriate.
- [ ] Audit sensitive plugin actions.

Example:

```
Discord plugin

Requested:
  users.read
  games.read
  notifications.send
  events.subscribe
  plugin.storage

Granted:
  users.read
  games.read
  notifications.send

Denied:
  events.subscribe
```

### J. Container/network isolation

- [ ] Define Docker production topology.
- [ ] Core backend/frontend communicate with Plugin Gateway.
- [ ] Individual plugins do not need direct core-backend access.
- [ ] Plugin runtime does not receive core environment variables by default.
- [ ] Plugin runtime cannot access the core database network endpoint directly.
- [ ] Plugin runtime cannot access Docker socket.
- [ ] Plugin filesystem is isolated.
- [ ] Define outbound network policy.
- [ ] Default arbitrary outbound network access to denied/restricted unless explicitly declared and approved.
- [ ] Define CPU/memory/process/resource limits.
- [ ] Decide whether plugins run as separate processes inside the plugin runtime or separate nested containers.
- [ ] Preserve the one-plugin-runtime-container deployment model while keeping individual plugin isolation strong enough to prevent one plugin from compromising another.

### K. Frontend integration

- [ ] Add plugin discovery/status to Settings.
- [ ] Display plugin version and compatibility.
- [ ] Display requested/granted permissions.
- [ ] Display health/failure/quarantine state.
- [ ] Render plugin settings schemas.
- [ ] Render plugin actions/pages.
- [ ] Allow enable/disable/restart where safe.
- [ ] Show plugin logs/errors to administrators.
- [ ] Do not let plugin UI bypass gateway authorization.

### L. Testing and security validation

- [ ] Unit-test manifest validation.
- [ ] Unit-test compatibility rules.
- [ ] Unit-test permission evaluation.
- [x] Unit-test storage isolation.
- [ ] Unit-test event filtering.
- [ ] Unit-test gateway authentication.
- [ ] Unit-test plugin/user identity handling.
- [ ] Test malicious/invalid plugin manifests.
- [ ] Test plugins attempting unauthorized API calls.
- [ ] Test plugins attempting core filesystem/database access.
- [ ] Test plugin crash/restart/quarantine.
- [ ] Test failed upgrades and rollback.
- [ ] Test core startup with broken plugins.
- [ ] Test plugin API version incompatibility.
- [ ] Test frontend rendering of invalid plugin schemas.
- [ ] Add integration tests for the complete install → grant → configure → run → revoke → uninstall lifecycle.

## In progress

- [ ] Architecture definition for the plugin platform.
- [ ] Identify existing application service boundaries that need to become stable plugin-facing contracts.
- [ ] Map current provider registries to future plugin capabilities.
- [ ] Decide final container/process isolation strategy.
- [ ] Define core ↔ plugin gateway authentication model.
- [ ] Define Plugin API v1 scope.

## Completed

- [x] Confirmed that the plugin system belongs in the main application repository for now.
- [x] Confirmed a separate plugin runtime/container is the intended production architecture.
- [x] Confirmed plugins should not run inside the core backend process.
- [x] Confirmed namespaced plugin storage as the persistence model.
- [x] Confirmed capability-scoped access instead of broad application API tokens.
- [x] Confirmed frontend plugin configuration/UI must be part of the initial architecture.
- [x] Confirmed notification and metadata providers are core extension points.
- [x] Identified issue #262 as the parent Plugin Hub/plugin-platform issue.
- [x] Created the dedicated implementation branch `feat/plugin-manager`.

## Dependency map

The implementation order should be:

```
Plugin API contracts
        │
        ├── Manifest + compatibility
        │
        ├── Identity + authentication
        │
        ├── Permission model
        │
        ├── Gateway
        │      │
        │      ├── Capability APIs
        │      ├── Event API
        │      ├── Storage API
        │      └── UI API
        │
        ├── Plugin runtime isolation
        │
        ├── Lifecycle/health/quarantine
        │
        ├── Packaging/update/rollback
        │
        └── Native frontend management
                    │
                    ▼
             First real plugin
                    │
          ┌─────────┴─────────┐
          │                   │
   Notification provider   Metadata provider
```

A sub-issue should not be considered implementation-ready until all of its blocking contracts are defined. Cross-cutting security and compatibility requirements are blockers for every plugin capability.

## First real plugin targets

The first plugins should exercise different parts of the platform:

1. Notification provider — validates provider registration, secrets, user context, delivery and settings UI.
2. Metadata provider — validates external API calls, provider registry integration, credentials and result DTOs.
3. Discord bot — validates events, user mapping, notifications, scoped permissions, persistent plugin data and deeper server integration.
4. Playnite integration — validates scoped application/device identity and demonstrates the replacement for broad user API tokens.

These should be separate validation targets; they should not force their provider-specific logic into the core plugin manager.

## Explicit non-goals for the first release

- Arbitrary plugin access to the core database.
- Plugin-controlled core Alembic migrations.
- Arbitrary backend imports into the core Python process.
- Arbitrary host filesystem access.
- Docker socket access.
- Automatic installation of arbitrary Python/npm/system dependencies into the core image.
- Unrestricted plugin frontend JavaScript.
- Plugin-to-plugin privileged communication.
- Marketplace/Plugin Hub distribution as a prerequisite for the runtime.
- Automatic third-party plugin updates without staged verification.
- Allowing an incompatible plugin to prevent the application from starting.

## Definition of done for Plugin Manager v1

The feature is not complete merely because plugins can be installed.

A v1 release requires:

- [ ] Isolated plugin runtime container.
- [ ] Authenticated gateway.
- [ ] Versioned Plugin API.
- [ ] Manifest validation.
- [ ] Capability/permission system.
- [x] Namespaced persistent storage.
- [ ] Declarative frontend UI.
- [ ] Lifecycle and health management.
- [ ] Automatic quarantine.
- [ ] Safe mode.
- [ ] Staged updates and rollback.
- [ ] Compatibility handling.
- [ ] Audit/logging.
- [x] Security/integration validation tests for the first four example integrations.
- [x] Four production-quality validation example integrations (notification, metadata, Discord, Playnite).
- [ ] Developer documentation sufficient for a third party to build a plugin without reading core internals.

## Lifecycle integrity hardening

The lifecycle manager uses the same canonical Plugin Package v1 payload digest as the package verifier. The digest covers sorted payload paths and bytes and excludes manifest.json, so installation and package inspection cannot disagree about a valid package.

Complete uninstall is coordinated through an authoritative storage-owner boundary. Storage cleanup runs before the lifecycle record is removed; if cleanup fails, uninstall reports the failure and retains the lifecycle record so the installation is not silently orphaned.

A running plugin is stopped before disable/uninstall completes. Runtime process output is redirected to a sink rather than an undrained pipe so noisy plugins cannot block on stdout/stderr.
