# Notification providers

Unnamed Tracking App keeps its normal in-app notifications and can also deliver those notifications through configured providers.

## Providers

### Email (SMTP)
SMTP is deployment-wide infrastructure. It sends to the email address already stored on each user account.

A user can enable or disable SMTP delivery from Settings → Notification Providers. SMTP is only available when the deployment has a working SMTP configuration.

### Discord
Discord uses a webhook configured by the individual user from Settings → Notification Providers.

The webhook is stored encrypted. The application does not return the webhook URL after it is saved. Use Replace webhook to change it or Revoke to remove it.

## Delivery behavior

Provider delivery is asynchronous. Creating an in-app notification does not wait for SMTP or Discord. Provider failures are recorded and retried a limited number of times.

Current notification preferences still apply when delivery is processed. Disabling a notification type therefore prevents queued delivery of that type.

### Per-provider routing

In **Settings → Notification Providers**, each user can choose which notification types go to each provider independently. For example, episode alerts can be sent by email while movie-release alerts are sent to Discord. Routing is checked again immediately before delivery, so it also applies to notifications already queued.

No provider secret is displayed in the UI or written to normal delivery failure messages.
