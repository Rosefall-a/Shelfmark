# Production Docker Image

The production deployment is an additional packaging target under `src/docker-container/`. It does not replace the existing development frontend/backend images.

## Architecture

The image is multi-stage: Node 22 builds the Vue frontend; the runtime contains Python 3.12, FastAPI/Uvicorn, Nginx, the compiled frontend and the static startup/diagnostic layer.

## Startup and readiness

PID 1 starts diagnostic Nginx before the application is ready, validates database configuration, waits for PostgreSQL, runs Alembic migrations, starts FastAPI, waits for `/health`, renders/validates the selected production Nginx configuration, reloads Nginx, verifies the frontend and monitors the backend.

The Docker healthcheck is healthy only when `/_startup/status.json` reports `overall=ready`. Nginx remaining alive for diagnostics does not mean the application is healthy.

## Diagnostics and logs

The startup page is static HTML/CSS/JavaScript and works without Vue, FastAPI or PostgreSQL.

Structured diagnostics are exposed at:

```text
/_startup/status.json
/_startup/details.txt
```

Raw backend and migration logs are not public HTTP resources. Operators can use Docker logs or the retained files:

```text
/run/unnamed-tracking/backend.log
/run/unnamed-tracking/migration.log
```

Backend and migration streams are redacted before retained/operator-facing output. The redactor targets common database-password, password/secret/token/API-key/client-secret/webhook/private-key/SMTP and bearer-authorization forms.

## Production Compose and persistence

Use `src/docker-container/compose.yaml`. The default host mapping is port 8080 to container port 80. Application data is persisted through `./data:/data`; PostgreSQL uses a named `pgdata` volume.

Keep both storage locations when recreating the deployment.

## Failure states

The startup model distinguishes `CONFIGURATION_FAILED`, `DATABASE_FAILED`, `MIGRATION_FAILED`, `BACKEND_FAILED`, `BACKEND_TIMEOUT`, `FRONTEND_FAILED` and `BACKEND_CRASHED`.

On failure the diagnostic Nginx layer remains available so operators can inspect the state.

## Embedded TLS

HTTP-only is the default. Set `NGINX_TLS_ENABLED=true` for embedded HTTPS and `NGINX_TLS_REDIRECT_HTTP=true` to redirect HTTP to HTTPS. Redirect is rejected when TLS is disabled.

For explicit certificates, configure `NGINX_TLS_CERTIFICATE` and `NGINX_TLS_PRIVATE_KEY` together and mount them read-only. If both are omitted, an existing conventional `/etc/nginx/tls/tls.crt` + `tls.key` pair is used when present; otherwise a self-signed localhost pair is generated under `/run/unnamed-tracking/tls`. The generated fallback is for local/diagnostic use, not trusted public HTTPS.

TLS material is validated before the ready configuration is activated. For public HTTPS, set `AUTH_COOKIE_SECURE=true`.

Nginx forwards `X-Forwarded-Proto`, and Uvicorn trusts forwarded headers only from the local Nginx hop so request-derived OIDC callback URLs preserve the external HTTPS scheme.

## Shutdown

PID 1 handles SIGTERM/SIGINT, sends SIGTERM to FastAPI and waits for it, then asks Nginx to quit.

## CI

The production image workflow validates image/Nginx/TLS configuration. The PostgreSQL/application runtime smoke suite is a separate workflow; see [Production Runtime Smoke Tests](production-runtime-smoke.md).
