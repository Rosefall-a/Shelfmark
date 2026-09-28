# Startup and Troubleshooting

The production container separates startup diagnostics from the normal application frontend. Nginx can continue serving the diagnostic layer when application startup fails.

## Startup sequence

1. Initialise status and diagnostic files.
2. Start Nginx with the startup configuration.
3. Validate database configuration.
4. Wait for PostgreSQL.
5. Run Alembic migrations.
6. Start Uvicorn on `127.0.0.1:8000`.
7. Wait for `/health`.
8. Render and validate the production Nginx configuration.
9. Switch Nginx to the ready configuration and reload it.
10. Verify the compiled frontend.
11. Monitor the backend process.

## Health semantics

The Docker healthcheck reads the file-backed startup status rather than treating the diagnostic Nginx page as readiness.

`overall=starting` means the container is alive but the application is not ready. `overall=failed` means the operator should inspect the diagnostics. Only `overall=ready` is healthy.

A backend crash after readiness changes the status to `BACKEND_CRASHED` and makes the healthcheck fail while keeping diagnostics available.

## Failure states

Startup records:

- `CONFIGURATION_FAILED`
- `DATABASE_FAILED`
- `MIGRATION_FAILED`
- `BACKEND_FAILED`
- `BACKEND_TIMEOUT`
- `FRONTEND_FAILED`
- `BACKEND_CRASHED`

Inspect:

```text
/_startup/status.json
/_startup/details.txt
/_startup/backend.log
```

These are operational diagnostics, not durable log storage.

## TLS failures

TLS is enabled only when `NGINX_TLS_ENABLED=true`. With both certificate variables empty, a self-signed localhost certificate/key pair is generated automatically.

Check that:

1. the certificate and private key are mounted at the configured paths;
2. both files are readable by the Nginx master;
3. the certificate chain is in the expected PEM order;
4. the certificate and key match;
5. port 443 is published by the deployment;
6. `AUTH_COOKIE_SECURE=true` is set for an HTTPS public URL.

The renderer reports missing/unreadable files without printing private-key contents. Nginx validation catches malformed or mismatched certificate/key material.

If TLS configuration fails during startup, the diagnostic HTTP listener remains available because the HTTPS configuration is activated only during the ready handoff.

## OIDC and proxy URLs

Nginx forwards `X-Forwarded-Proto` and Uvicorn trusts that header only from the local Nginx hop. This allows request-derived OIDC callback URLs to use `https` when clients connect through embedded TLS.

If another reverse proxy is placed in front of the container, ensure it preserves the external HTTPS scheme and that the deployment’s proxy trust boundary remains limited to the expected internal hop.

## Shutdown

Docker stop sends SIGTERM to PID 1. PID 1 forwards shutdown to FastAPI, waits for it, and then asks Nginx to quit. If shutdown behavior is incorrect in a deployment, inspect the container logs for the entrypoint’s shutdown messages.

End-to-end runtime shutdown and PostgreSQL/application smoke testing are tracked separately in #206.
