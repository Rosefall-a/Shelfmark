# Production Docker Image

The production deployment is an additional packaging target under src/docker-container/. It does not replace the existing development frontend/backend images.

## Image

The Dockerfile is a multi-stage build: Node 22 builds the Vue frontend; a Python 3.12 runtime contains FastAPI and its dependencies; Nginx, the compiled frontend, startup assets, and the entrypoint are then added to the runtime image.

Node and the Vite development server are not required at runtime.

Published images use ghcr.io/rosefall-a/unnamed_tracking_app:<tag>. The workflow also publishes ghcr.io/rosefall-a/unnamed_tracking_app:sha-<commit-sha>.

## Production Compose

Use src/docker-container/compose.yaml.

The application service maps host port 8080 to container port 80 by default, persists ./data to /data, requires SECRET_KEY and PRIMARY_USER_PASSWORD, and supplies PostgreSQL connection configuration. The default bootstrap username is admin and the default bootstrap email is admin@example.invalid.

PostgreSQL uses PostgreSQL 18 and a named pgdata volume.

UNNAMED_TRACKING_APP_VERSION selects the image tag and UNNAMED_TRACKING_APP_PORT selects the host port.

### Required production values

    POSTGRES_PASSWORD=change-this-database-password
    SECRET_KEY=replace-with-a-stable-secret
    PRIMARY_USER_PASSWORD=replace-with-the-initial-admin-password
    AUTH_COOKIE_SECURE=false

For HTTPS access, use AUTH_COOKIE_SECURE=true.

Keep SECRET_KEY stable for an existing installation. If it is omitted from the environment, preserve the persistent generated key under /data/config instead.

## Startup lifecycle

The entrypoint starts Nginx before the application stack is ready.

1. Initialize status and diagnostic files.
2. Start Nginx with the startup configuration.
3. Validate database configuration.
4. Wait for PostgreSQL with bounded retries.
5. Run alembic upgrade heads with bounded retries.
6. Start Uvicorn on 127.0.0.1:8000.
7. Wait for /health.
8. Validate the ready Nginx configuration.
9. Replace the active configuration and reload Nginx.
10. Verify that the compiled frontend is served.
11. Monitor the backend process.

If startup fails, the entrypoint deliberately keeps Nginx alive so the diagnostic page remains available.

## Startup diagnostics

The startup page is static HTML/CSS/JavaScript served directly by Nginx. It does not depend on Vue, FastAPI, or PostgreSQL.

It displays the lifecycle phase, database status, migration status, backend status, frontend status, the current message, and expandable startup details.

Diagnostic endpoints are /_startup/status.json, /_startup/details.txt, and /_startup/backend.log.

The startup JavaScript polls asynchronously and slows down after READY. When a failure is reported, the loading animation stops and the diagnostic details open.

## Failure states

The current status model distinguishes CONFIGURATION_FAILED, DATABASE_FAILED, MIGRATION_FAILED, BACKEND_FAILED, BACKEND_TIMEOUT, FRONTEND_FAILED, and BACKEND_CRASHED.

The diagnostic files remain available while Nginx is held in the failure state.

## Nginx hand-off

Before readiness, Nginx serves the startup page.

After the backend is healthy, the entrypoint validates ready.conf, copies it over the active nginx.conf, and runs nginx -s reload.

The ready configuration proxies /api/ to FastAPI on 127.0.0.1:8000, serves the compiled Vue SPA from /srv/frontend, and retains the startup diagnostic endpoints.

## Persistence

The production Compose deployment persists application data through ./data:/data and PostgreSQL data through the named pgdata volume.

Do not remove these storage locations when recreating the production container.

## CI and publishing

.github/workflows/docker-container.yml builds the production image on pull requests and pushes images for non-pull-request events. For non-PR events it pushes both a ref-derived tag and a sha-<commit> tag to GHCR.

The current workflow does not perform a full PostgreSQL/application runtime smoke test after building the image. Its failure diagnostics are Docker log commands if a workflow step fails.

## TLS

TLS, certificate generation, ACME/Let's Encrypt, and certificate management are outside the production image. Use an external HTTPS reverse proxy when TLS is required.
