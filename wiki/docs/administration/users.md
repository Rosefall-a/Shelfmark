# Users

Administrators can list, create, update, and delete local users from Settings. A user has a unique username/email identity, an active state, and an administrator flag. Deactivation prevents normal access without immediately deleting library data.

The configured primary user is reconciled at application startup when `PRIMARY_USER_USERNAME`, `PRIMARY_USER_EMAIL`, and `PRIMARY_USER_PASSWORD` are present. Treat those values as deployment secrets and rotate them through the supported configuration path.

Users can update their own profile and manage their own API keys. API-key values are shown only when created; revoke unused keys rather than sharing them. OIDC-linked identities follow the configured provider and claim rules.

Deleting a user is destructive and can affect user-owned library data. Take a verified backup first. Plugin grants scoped to one user do not authorize another user, and a plugin session/document request is checked again against the authenticated user at the gateway.
