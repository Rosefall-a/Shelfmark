# Plugin integration validation

This page documents the first production-quality Plugin API v1 validation
integrations delivered for #272.

The examples are deliberately contract-level fixtures rather than code imported
into the core application at runtime. They prove that an integration can be
implemented against the stable gateway boundary without importing ORM models,
database sessions, application secrets, or private provider registries.

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
state. The provider cannot reach those internals through this contract.

## Metadata provider

The reference provider consumes a normalized search request and returns
MetadataCandidate DTOs. Provider selection and result persistence remain
core-owned. The example therefore does not recreate the metadata registry.

## Discord

The Discord example maps a Discord user ID to a core user ID in its own plugin
namespace and subscribes only to selected event types for that user. Event
delivery is filtered before it reaches the plugin, demonstrating the expected
events.subscribe boundary.

## Playnite

The Playnite example uses a PluginIdentity plus installation, authenticated
user context and a device ID. It does not introduce a Playnite-specific broad
API token. This is the contract shape intended for future Playnite migration
away from the current user API-key integration.

## Security and compatibility

The validation gateway applies the existing default-deny authorization function
for every operation. Manifest capability declarations remain requests, not
grants. Storage is keyed by plugin ID, and event subscriptions are user-scoped.

These examples do not create a new wire protocol. The in-memory gateway is a
test harness for the existing Plugin API v1 contract. A production transport
must expose the same DTOs and authorization semantics.

## Test coverage

src/backend/tests/test_plugin_validation_integrations.py covers:

- notification delivery through the core-owned coordinator contract;
- normalized metadata results;
- Discord event filtering and plugin-owned storage;
- Playnite scoped identity;
- default-deny and user-scope enforcement;
- per-plugin storage isolation.

No core provider registry is duplicated and no existing application behavior is
removed or weakened.
