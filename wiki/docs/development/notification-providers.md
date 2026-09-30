# Plugin notification providers

The notification coordinator is core-owned. Plugins can add delivery behavior, but cannot create arbitrary delivery rows, inspect notification tables, override user preferences, or control retry state.

## Registration

An enabled plugin calls `notification_providers.register` with:

```json
{
  "provider_id": "example.provider.destination",
  "name": "Destination name",
  "action_id": "deliver"
}
```

The provider ID must begin with `<plugin_id>.`. Registration is bound to the current installation ID. Disable makes the action unavailable; permission revocation or uninstall revokes the registration.

## Delivery lifecycle

1. Core creates an in-app `Notification`.
2. Core creates one pending delivery per active provider without duplicates.
3. The job loop rechecks the user's provider preference and the installation's `notification_providers.deliver` grant.
4. Core invokes the registered action with a minimized DTO: notification ID, kind, title, body, media type/ID, event time, and destination user ID.
5. The action returns `success`, `retryable`, and an optional bounded error.
6. Core records success, terminal failure, or exponential retry. The current maximum is three attempts.

Secrets are stored separately through the `plugin.storage` write-only secret route. They are not included in delivery work, ordinary settings, frontend state, or diagnostics.

The reference Discord provider uses the runtime's narrowly scoped HTTPS sender. It accepts only Discord webhook hosts/paths, caps content at 2,000 characters, and requires `PLUGIN_RUNTIME_DISCORD_EGRESS=true`; arbitrary plugin network access remains disabled.
