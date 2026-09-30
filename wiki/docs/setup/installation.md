# Installation

For the recommended self-hosted deployment, use the [Arcane setup guide](index.md).

Arcane lets you create the Compose stack and provide its environment variables directly in the two fields provided by the stack editor.

For a basic deployment, the required environment values are:

```dotenv
POSTGRES_PASSWORD=change-this-database-password
AUTH_COOKIE_SECURE=false
```

See [Environment Variables](environment-variables.md) for optional configuration.

## Deployment requirements

- Docker
- Arcane connected to the Docker host
- Persistent storage for application data
- Persistent PostgreSQL storage

The application and PostgreSQL containers should both use persistent storage so rebuilding or replacing containers does not remove application data.

For HTTPS deployments behind a reverse proxy, set `AUTH_COOKIE_SECURE=true`. See [OIDC / SSO](../integrations/oidc.md) for additional reverse-proxy considerations.
