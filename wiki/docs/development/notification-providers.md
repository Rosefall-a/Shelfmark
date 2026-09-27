# Notification provider architecture

Notification generation and delivery are separate concerns.

The existing Notification model remains the source of in-app notifications. A provider implementation is responsible for:

1. identifying itself;
2. resolving a user-specific destination;
3. determining whether that destination is usable;
4. delivering a NotificationMessage;
5. returning a success/failure result without raising provider errors into the originating application action.

Providers implement the generic contract in src/backend/src/features/notification_providers/base.py and are registered in registry.py.

The current providers are:

- smtp: resolves the existing User.email address and uses deployment-wide SMTP configuration.
- discord: resolves the encrypted per-user webhook destination.

Delivery state is stored in NotificationDelivery. Its unique notification/provider key prevents duplicate delivery records. The worker retries transient provider failures and records terminal failures without failing notification generation.

## Adding a provider

A new provider should:

- implement the provider contract;
- add itself to the registry;
- use an existing application identity field when possible;
- store provider-specific user destinations through NotificationProviderSetting rather than creating a second identity system;
- never expose secrets through read APIs;
- return generic, non-secret failure messages;
- add deterministic unit tests using mocks/fakes;
- document any new deployment or per-user configuration.

Notification generation should not contain provider-specific branching. New providers should be addable without changing the notification-generation layer.
