# Administration

Administrators manage users, deployment settings, provider credentials, scheduled jobs, imports/exports, backups, and plugins from Settings.

## Operational checklist

1. Configure HTTPS, secure cookies, a unique Fernet `SECRET_KEY`, database credentials, and a unique plugin-runtime token.
2. Create only the users and API keys that are needed.
3. Configure metadata/OIDC credentials through deployment settings or environment variables; environment-managed values remain authoritative.
4. Review scheduled-job intervals and backup status.
5. Install plugins only from a reviewed package, inspect every requested permission, and keep untrusted-package confirmation enabled.
6. Monitor application logs and per-plugin structured diagnostics without copying secrets into support reports.

See [Users](users.md), [Scheduled tasks](tasks.md), [Plugin administration](plugins.md), and [Startup and troubleshooting](../deployment/startup-and-troubleshooting.md).
