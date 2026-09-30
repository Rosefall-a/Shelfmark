# Setup with Arcane

The easiest way to deploy Unnamed Tracking App with Arcane is to create a new Compose stack and paste the Compose configuration and environment variables directly into Arcane.

Arcane provides two text areas for a Compose stack:

- **Compose** — paste the Docker Compose configuration here.
- **Environment** — paste the environment variables here.

You do **not** need to create an `.env` file manually when using Arcane.

## Requirements

You will need:

- A server running Docker
- [Arcane](https://getarcane.app/) installed and connected to your Docker host
- A directory on the Docker host where application data can be stored

## 1. Create a new stack in Arcane

Open Arcane and create a new Compose stack.

Give the stack a name such as:

`unnamed-tracking-app`

When Arcane shows the Compose and Environment text boxes, use the configurations below.

## 2. Compose configuration

Paste the following into Arcane's **Compose** text box:

```yaml
services:
  app:
    image: ghcr.io/rosefall-a/unnamed_tracking_app:feat-central-config-handler
    restart: unless-stopped
    ports:
      - "${UNNAMED_TRACKING_APP_PORT:-8080}:80"
    env_file:
      - .env
    volumes:
      - ./data:/data

  db:
    image: postgres:18
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-unnamed_tracking}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
      POSTGRES_DB: ${POSTGRES_DB:-unnamed_tracking}
    volumes:
      - pgdata:/var/lib/postgresql
    healthcheck:
      test: [ "CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-unnamed_tracking} -d ${POSTGRES_DB:-unnamed_tracking}" ]
      interval: 5s
      timeout: 5s
      retries: 20

volumes:
  pgdata:
```

## 3. Required environment variables

Paste the following into Arcane's **Environment** text box:

```dotenv
POSTGRES_PASSWORD=change-this-database-password
AUTH_COOKIE_SECURE=false
```

Change `POSTGRES_PASSWORD` to a strong, unique password before deploying.

### AUTH_COOKIE_SECURE

This setting controls whether the application's authentication cookies require HTTPS.

- `false` — the application is **not** being accessed through HTTPS.
- `true` — the application **is** being accessed through HTTPS.

If you are putting Unnamed Tracking App behind a reverse proxy, such as Nginx, Caddy, Traefik, or another proxy that provides HTTPS, set:

```dotenv
AUTH_COOKIE_SECURE=true
```

If the application is being accessed directly over HTTP, leave it as:

```dotenv
AUTH_COOKIE_SECURE=false
```

The value should match how users access the application from their browser. For example, if the reverse proxy terminates HTTPS and forwards HTTP internally to the application, use `AUTH_COOKIE_SECURE=true`.

### Optional environment variables

The application supports additional environment variables for application behavior, uploads, metadata providers, integrations, OIDC/SSO, and other configuration.

You do **not** need to copy all of those variables into Arcane. Only add the variables you actually want to customize.

See the [Environment Variables](environment-variables.md) page for the complete list and an explanation of what each variable does.

OIDC is configured after installation from **Settings → OIDC / SSO**. See the [OIDC user guide](../user-guide/oidc.md) for that configuration.

## 4. Deploy the stack

After entering both the Compose and Environment configurations, deploy/start the stack from Arcane.

Arcane will create the application and PostgreSQL containers and manage the Compose stack for you.

## 5. Open the application

The example Compose configuration exposes the application on port `8080`.

Open:

```text
http://your-server:8080
```

If you need a different host port, add `UNNAMED_TRACKING_APP_PORT` to the Arcane Environment field.

For example:

```dotenv
UNNAMED_TRACKING_APP_PORT=9000
```

would make the application available at:

```text
http://your-server:9000
```

## 6. Complete initial setup

On the first launch, open the application in your browser and follow the setup process.

The first-time setup flow can also be used to configure OIDC if you want to enable it during the initial boot. This is supported for the initial configuration.

However, the **preferred method is to configure OIDC from Settings → OIDC / SSO after the application has been installed**. The Settings page is the normal place to manage OIDC providers and makes it easier to return to the configuration later.

See the [OIDC user guide](../user-guide/oidc.md) for the provider settings, callback URI, account matching, and troubleshooting.

The normal setup UI is preferred for creating the first user and configuring other initial application settings.

If you configured deployment-owned values in Arcane, those values are available to the application during setup.

## Updating

When a new application image is available, use Arcane to pull the updated image and redeploy/recreate the stack.

Review the release or deployment documentation for the appropriate image tag before updating a production installation.

## Stopping the application

Use Arcane's stack controls to stop or remove the stack.

Removing the stack does **not** remove the named PostgreSQL volume or the bind-mounted application data unless you explicitly remove those Docker volumes/files.

## Next steps

- See [Environment Variables](environment-variables.md) for all available configuration options.
- See [API Documentation](../development/api.md) for the automatically generated API documentation.

# Setup and Deployment

Unnamed Tracking App has a production Docker image and a separate development Compose stack.

## First setup

The setup UI is generated from the backend configuration registry. Environment-owned values are resolved and locked, while application-owned values can be persisted through setup.

The first administrator can be supplied through the bootstrap environment variables or created through the normal setup flow.

## Production Compose

The production Compose file is src/docker-container/compose.yaml.

The current file requires POSTGRES_PASSWORD, SECRET_KEY, and PRIMARY_USER_PASSWORD. It defaults POSTGRES_USER and POSTGRES_DB to unnamed_tracking, maps host port 8080 to container port 80, and persists application data at ./data:/data.

PostgreSQL uses a named pgdata volume.

See [Production Docker Image](../deployment/production-docker.md) for the complete deployment configuration and startup behavior.

## Development Compose

The root compose.yaml runs PostgreSQL, the backend, and the frontend separately. The frontend is exposed on port 5173.

Use [Installation](installation.md) for development startup commands.
