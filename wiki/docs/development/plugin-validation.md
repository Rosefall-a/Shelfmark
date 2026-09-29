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

## Current cross-layer verification

The plugin-manager branch now has explicit coverage at each package boundary:

- The host manifest contract accepts the optional `frontend.entry` declaration.
- The host upload path has a regression fixture using the UI Playground manifest shape.
- The plugin runtime rejects unsafe or missing declared frontend entries and serves a
  complete bundled frontend through its namespaced frontend endpoint.
- The frontend service covers the HTTP 409 untrusted-package response that drives the
  explicit confirmation flow.
- The plugin repository smoke-tests every real demo plugin's main logic, validates the
  UI Playground frontend entry, and checks that its webhook secret is never emitted by
  plugin code.
- Plugin CI builds fresh unsigned demo packages, verifies payload integrity, and checks
  every declared frontend entry against the package payload.
- The runner keeps Discord webhook secrets inside private plugin storage and performs
  host-side delivery only after the plugin requests it.

These are deterministic CI/unit/smoke checks; they are stronger than the former
contract-only fixtures but are not a claim that a particular user's running Docker
deployment has already been rebuilt and manually exercised. A deployment must use a
plugin-manager image containing these changes and a newly generated plugin package.
