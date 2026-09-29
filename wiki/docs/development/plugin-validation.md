# Plugin integration validation

Issue #272 introduced contract-level validation examples for notification,
metadata, Discord and Playnite integrations.

## Current audit status

The current examples on this branch are **contract/in-process validation
fixtures**, not production external plugins. They consume the stable Plugin API
v1 contracts through the in-memory `ValidationGateway` harness.

This is useful for validating DTOs, capability decisions, event scoping and
provider contracts, but it does **not** prove the complete production flow
through the application, authenticated gateway transport, isolated runtime,
installation manager, persistence or external plugin packages.

The production host/runtime integration is tracked by #320. The real
third-party-style examples belong in
`Rosefall-a/unnamed_tracking_app_plugins` and are tracked by #321 and that
repository's issue #1.

## Validation matrix

- Notification: `NotificationProvider` + `notifications.send`.
- Metadata: `MetadataProvider` + normalized `MetadataCandidate` results.
- Discord: `EventEnvelope/EventSubscription` + `events.subscribe` +
  `plugin.storage`.
- Playnite: `PluginIdentity` + user/device-scoped `RequestContext` +
  game capabilities.

The test suite proves default-deny authorization, user-scoped event delivery,
secret-field handling and independent plugin storage namespaces at the
contract/harness boundary.

## What is currently verified

- Static manifest/API contracts can be validated without executing plugin code.
- Capability authorization is default-deny and installation/user/device scoped.
- Package integrity/signature verification has dedicated unit coverage.
- Lifecycle failure, quarantine and safe-mode behavior have unit coverage.
- Runtime policy validation has unit coverage for secret environment rejection,
  default-deny network declarations and resource limits.
- Declarative plugin UI validation has frontend unit coverage.

## What is not yet verified

The following require the production integration tracked by #320/#321:

- real external plugin package installation;
- authenticated application-to-runtime gateway transport;
- execution of an external plugin process through the production lifecycle;
- real enable/disable/re-enable behavior through application APIs;
- restart/reconciliation of persisted plugin state;
- production UI/settings/API routing;
- permission enforcement over the real gateway transport;
- staged update and rollback through the running runtime;
- complete uninstall and plugin-owned storage cleanup;
- cross-repository end-to-end execution of the example plugins.

Until those checks pass, #272 should be considered contract-level validation
rather than proof of production readiness.
