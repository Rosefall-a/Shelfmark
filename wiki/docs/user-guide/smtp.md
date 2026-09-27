# SMTP configuration

SMTP is configured as deployment-wide infrastructure through the existing setup/configuration UI.

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

SMTP notifications use each user's existing account email address; there is no second email identity system.
