# SMTP configuration

SMTP is configured as deployment-wide infrastructure through the existing setup/configuration UI and the **Settings → SMTP / Email** page for administrators. Both use the same existing application integration settings; the settings page does not create a second SMTP configuration store.

If an SMTP value is supplied through the deployment environment, the settings page marks that field **Managed by .env** and prevents editing. This uses the existing environment-resolution rules, so environment configuration remains authoritative.

The available fields are:

- Enable SMTP notifications
- SMTP host
- SMTP port
- SMTP username
- SMTP password
- SMTP sender address
- SMTP security: None, STARTTLS, or SSL/TLS

SMTP is optional. Leaving it disabled does not affect normal in-app notifications.

SMTP passwords are encrypted at rest. Environment-owned configuration remains authoritative when supplied through the deployment environment.

SMTP notifications use each user's existing account email address; there is no second email identity system. Administrators can use **Send test email** to verify the deployment configuration.


The Notification providers settings also provides a **Test email** control. Select a generic test or a notification type to verify the currently enabled SMTP configuration.
