# Plugin administration

Only administrators can install, update, enable, disable, retry, inspect diagnostics, revoke all grants, or uninstall plugins.

## Review rules

- Verify plugin ID, publisher, version, compatibility ranges, and dependencies.
- Deny capabilities without a clear, necessary rationale.
- Treat document/session reads as sensitive account data, session revocation as destructive, notification delivery as external disclosure, and `plugin.storage` secrets as write-only credentials.
- Do not enable unsigned packages unless you intentionally accept the untrusted-package warning.
- Re-review permissions introduced by an update.

## Diagnostics and recovery

The Diagnostics tab shows process state, last exit code, and up to 200 structured events. Secret-, token-, password-, and webhook-shaped values are redacted. Disable a misbehaving plugin before investigating. Revocation blocks subsequent gateway calls; uninstall additionally removes package/private storage and provider registrations.

Production deployments must use bubblewrap isolation and a unique `PLUGIN_RUNTIME_TOKEN`. `NONBUBBLE_ENV=true` is development-only and must not be used for untrusted plugins.
