# Plugin integration validation

This page documents the Plugin API v1 contract-validation integrations
associated with #272.

## Current audit status

The examples currently on this branch are deliberately contract-level fixtures,
not production external plugins. They prove that integration code can consume
the stable Plugin API v1 DTOs and authorization boundary without importing ORM
models, database sessions, application secrets or private provider registries.

They are backed by the in-memory `ValidationGateway` test harness. A production
transport and application-level plugin manager are still required before these
examples can be considered end-to-end validation. See #320 for host/runtime
integration and #321 for the real external examples.

## Validation targets

| Integration | Stable contract exercised | Security boundary |
| --- | --- | --- |
| Notification provider | NotificationProvider, NotificationRequest, NotificationResult | notifications.send |
| Metadata provider | MetadataProvider, MetadataProviderRequest, MetadataCandidate | games.read |
| Discord bot | EventEnvelope, EventSubscription, EventAck, plugin.storage | user-scoped events and namespaced storage |
| Playnite | RequestContext, PluginIdentity, games.read/write | installation + user + device identity |

## Notification provider

The reference provider receives only a normalized NotificationRequest and
returns a NotificationResult. The core remains responsible for notification
creation, provider selection, preferences, retries, persistence and delivery
state.

## Metadata provider

The reference provider consumes a normalized search request and returns
MetadataCandidate DTOs. Provider selection and result persistence remain
core-owned.

## Discord

The Discord example maps a Discord user ID to a core user ID in its own plugin
namespace and subscribes only to selected event types for that user. The
validation harness demonstrates user-scoped event delivery.

## Playnite

The Playnite example uses a PluginIdentity plus installation, authenticated
user context and a device ID. It does not introduce a Playnite-specific broad
API token.

## Security and compatibility

The validation gateway applies default-deny authorization for every operation.
Manifest capability declarations remain requests, not grants. Storage is keyed
by plugin ID, and event subscriptions are user-scoped.

These examples do not create a new wire protocol. The in-memory gateway is a
test harness for the existing Plugin API v1 contract. The production transport
must expose the same DTOs and authorization semantics.

## Test coverage

`src/backend/tests/test_plugin_validation_integrations.py` covers:

- notification delivery through the core-owned coordinator contract;
- normalized metadata results;
- Discord event filtering and plugin-owned storage;
- Playnite scoped identity;
- default-deny and user-scope enforcement;
- per-plugin storage isolation.

## Not yet verified end-to-end

The current suite does not prove:

- external package installation;
- production application-to-runtime gateway transport;
- execution of an external plugin process through the lifecycle manager;
- application-level plugin management endpoints;
- restart/reconciliation of installed plugin state;
- production UI/settings routing;
- staged update/rollback through the running runtime;
- complete uninstall/storage cleanup.

Those are tracked by #320, #321 and #322. The validation examples should not be
described as production-ready until those flows are verified.
