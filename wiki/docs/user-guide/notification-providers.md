# Notification providers

In-app notifications remain the source of truth. External providers are optional destinations for eligible notifications.

Open notification settings to enable or disable each registered provider for your account. Providers are disabled by default. A plugin provider also requires an active installation grant; enabling the preference does not grant the plugin permission.

The core application owns delivery rows, deduplication, preference checks, attempt counts, exponential backoff, and terminal state. A provider receives only a minimized notification DTO after those checks. Delivery is best-effort and currently stops after three failed attempts.

For the reference Discord provider, save the webhook through the plugin's write-only secret field, then enable **Discord (plugin)** in notification provider settings. The destination is validated at delivery time and is never returned to the frontend or included in diagnostics.
