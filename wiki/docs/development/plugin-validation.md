# Plugin integration validation

Issue #272 is validated by contract-level examples for notification, metadata,
Discord and Playnite integrations.

These examples intentionally remain outside the core runtime path. They consume
the stable Plugin API v1 contracts through a test gateway harness, which prevents
validation code from becoming a second provider registry or a bypass around
authentication, permissions, storage or lifecycle boundaries.

See the repository Plugin integration validation documentation for the complete
contract matrix and security notes.

## Validation matrix

- Notification: NotificationProvider + notifications.send.
- Metadata: MetadataProvider + normalized MetadataCandidate results.
- Discord: EventEnvelope/EventSubscription + events.subscribe + plugin.storage.
- Playnite: PluginIdentity + user/device-scoped RequestContext + game capabilities.

The test suite also proves default-deny authorization, user-scoped event delivery
and independent plugin storage namespaces.
