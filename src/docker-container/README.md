# Production container

This directory contains the single-container production packaging for Unnamed Tracking. It is separate from the development frontend/backend images.

The image contains the compiled Vue frontend, FastAPI, Nginx, and the independent startup/diagnostic layer. FastAPI listens only on the container loopback interface; Nginx is the public edge.

## Startup and readiness

PID 1 starts Nginx with the diagnostic configuration before PostgreSQL or FastAPI are ready. It then validates database configuration, waits for PostgreSQL, applies migrations, starts FastAPI, selects `ready.conf` (HTTP), `readytls.conf` (HTTPS), or `readytlsredirect.conf` (HTTPS plus HTTP redirect), renders TLS certificate paths when required, copies the selected production configuration to `/etc/nginx/nginx.conf`, validates it, reloads Nginx, and verifies the frontend.

The Docker healthcheck is intentionally stricter than “Nginx is alive”: it is healthy only when the file-backed status reports `overall=ready`. During startup and after controlled startup failures the container can remain alive so operators can inspect the diagnostics, but Docker health remains unhealthy.

SIGTERM and SIGINT are handled by PID 1. The backend receives SIGTERM and is waited on before Nginx is asked to quit. This keeps the startup diagnostics available during failures without leaving child processes behind during normal container shutdown.

## Runtime permissions

The Nginx master remains privileged because the production image binds ports 80/443 and controls the Nginx process lifecycle. Nginx workers run as `www-data`.

The FastAPI process remains under the container entrypoint’s runtime user because it must retain access to the application and deployment-mounted state. Do not assume a rootless container until the persistent-data and Nginx lifecycle requirements have been validated for the target deployment.

Runtime status and diagnostics live under `/run/unnamed-tracking`. Application data is mounted separately at `/data`; PostgreSQL data is owned by the database service.

## Logs and persistence

Startup details and the backend startup log are file-backed under `/run/unnamed-tracking` and are therefore ephemeral container diagnostics. Nginx access/error logs are written under the container’s Nginx log directory.

For persistent operational logging, use the container runtime’s logging driver or an external log collector. Do not treat the container’s ephemeral log directory as a durable archive.

The Compose deployment persists `./data:/data` and PostgreSQL’s named volume. Backups should cover application data and PostgreSQL data according to the deployment’s backup policy.

## Nginx

The production configuration keeps the startup diagnostics available after readiness. API requests are proxied to FastAPI with Host, client-address, forwarded-for, and forwarded-protocol headers. Proxy timeouts are bounded.

Nginx hides its version and emits security headers for the production frontend/HTTPS edge. HSTS is emitted only by the HTTPS server.

## Optional embedded HTTPS/TLS

HTTP-only is the default. Embedded TLS is enabled through environment variables. If TLS is enabled without certificate/key paths, the image first uses a complete certificate/key pair already present at `/etc/nginx/tls/tls.crt` and `/etc/nginx/tls/tls.key`; otherwise it generates a self-signed localhost certificate/key pair under `/run/unnamed-tracking/tls`. The conventional `/etc/nginx/tls` paths also fall back to the generated pair when those files are not mounted. Explicit non-default certificate/key paths remain supported for production. TLS itself remains disabled by default.

Set:

```text
NGINX_TLS_ENABLED=true
NGINX_TLS_CERTIFICATE=/etc/nginx/tls/tls.crt
NGINX_TLS_PRIVATE_KEY=/etc/nginx/tls/tls.key
NGINX_TLS_REDIRECT_HTTP=true
```

`NGINX_TLS_REDIRECT_HTTP` is optional and defaults to false. When enabled, HTTP redirects to HTTPS after the production configuration is activated. During startup failure, the diagnostic HTTP listener remains available so a broken certificate does not hide the diagnostic page.

Mount externally managed certificates read-only, for example:

```yaml
volumes:
  - ./tls:/etc/nginx/tls:ro
```

The private key should be readable only by the container runtime/Nginx master as appropriate for the deployment. Never commit certificate or key material.

TLS configuration accepts TLS 1.2 and TLS 1.3. Missing, unreadable, malformed, or mismatched certificate/key files cause production Nginx validation to fail and are reported through startup diagnostics. Private-key contents are not logged.

For HTTPS deployments, set `AUTH_COOKIE_SECURE=true`. Nginx forwards the original protocol to FastAPI and Uvicorn trusts that header only from the local Nginx hop, allowing request-derived OIDC callback URLs to retain the HTTPS scheme.

Certificate rotation does not require rebuilding the image: replace the mounted files and restart/reload the production container according to the deployment’s certificate-management procedure.

## Resource guidance

Production sizing depends on the number of users, scheduled jobs, metadata work, media operations, and PostgreSQL workload. Start with at least 2 CPU cores and 2 GiB RAM for a small deployment and monitor actual CPU, memory, database, and disk usage before tightening limits. PostgreSQL and application workloads should be sized independently when traffic grows.

Runtime smoke testing of PostgreSQL, migrations, frontend/API handoff, and controlled shutdown is tracked separately in #206.
