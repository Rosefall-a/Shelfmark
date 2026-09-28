# Production Docker Image

The production deployment is an additional packaging target under `src/docker-container/`. It does not replace the existing development frontend/backend images.

## Architecture

The image is built in stages: Node 22 compiles the Vue frontend, while the runtime image contains Python 3.12, FastAPI, Nginx, the compiled frontend, and the independent startup/diagnostic layer.

The request path is:

```text
Client -> Nginx -> FastAPI
             |
             +-> compiled Vue frontend
             +-> startup/diagnostic files
```

FastAPI listens on `127.0.0.1:8000`; it is not exposed directly by the container.

## Startup and health semantics

PID 1 starts the diagnostic Nginx configuration first, then waits for PostgreSQL, runs Alembic migrations, starts FastAPI, selects the production Nginx configuration (`ready.conf`, `readytls.conf`, or `readytlsredirect.conf`), validates it, copies the selected/rendered configuration to `/etc/nginx/nginx.conf`, reloads Nginx, and verifies the frontend.

The status model distinguishes starting, database failure, migration failure, backend failure/timeout, frontend/Nginx failure, readiness, and post-start backend crash.

The Docker healthcheck is healthy only when `/_startup/status.json` reports `overall=ready`. Therefore:

- Nginx alive + application starting = unhealthy
- Nginx alive + database/migration/backend failure = unhealthy
- application fully ready = healthy
- backend crashes after readiness = unhealthy

The diagnostic Nginx listener intentionally remains available during startup failures.

## Shutdown

PID 1 handles SIGTERM/SIGINT, sends SIGTERM to FastAPI, waits for it, then asks Nginx to quit. This is intended to give active requests a normal shutdown path without leaving orphaned child processes.

## Permissions and filesystem

Nginx workers run as `www-data`; the master retains the privileges required to bind ports 80/443 and control the process. Runtime status/log files are under `/run/unnamed-tracking`.

The Compose example persists `./data:/data` and PostgreSQL state in a named volume. Runtime diagnostics are ephemeral. Use Docker logging or an external collector when durable logs are required.

## Nginx security

The production edge disables version disclosure, keeps bounded proxy timeouts, forwards the original request protocol, and emits `X-Content-Type-Options`, `Referrer-Policy`, and `X-Frame-Options`. HSTS is emitted only on HTTPS.

## Optional embedded TLS

HTTP-only remains the default. TLS is deployment-only. If TLS is enabled without certificate/key paths, the container generates a self-signed localhost certificate/key pair under `/run/unnamed-tracking/tls`; explicit mounted certificate/key files remain supported for production.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NGINX_TLS_ENABLED` | `false` | Enable the embedded HTTPS listener. |
| `NGINX_TLS_CERTIFICATE` | `/etc/nginx/tls/tls.crt` | Mounted PEM certificate/chain. |
| `NGINX_TLS_PRIVATE_KEY` | `/etc/nginx/tls/tls.key` | Mounted PEM private key. |
| `NGINX_TLS_REDIRECT_HTTP` | `false` | Redirect HTTP to HTTPS after readiness. |

When enabled, publish container port 443 and mount the certificate directory read-only. Do not bake keys into the image.

`AUTH_COOKIE_SECURE=true` should be used when the public application URL is HTTPS. Nginx sends `X-Forwarded-Proto` and Uvicorn accepts that header only from the local proxy, preserving HTTPS for request-derived OIDC callback URLs.

If TLS is enabled but the certificate/key is missing, unreadable, malformed, or mismatched, Nginx validation fails and startup reports a frontend/configuration failure. Because the startup configuration remains HTTP-only until the production handoff, the diagnostic page remains reachable during this failure.

## Logs and operations

Startup details and backend startup output are stored under the ephemeral runtime status directory. Nginx logs remain container-local unless exported by the runtime. Operators should use the container logging driver or a centralized collector for durable retention and rotation.

Persist application and PostgreSQL data independently from logs. Backups should be tested against the actual deployment’s persistent volumes.

For small deployments, start around 2 CPU cores and 2 GiB RAM and size upward based on observed application and PostgreSQL workload.

## CI scope

The production-container workflow builds the image and validates Nginx/TLS configuration with deterministic self-signed test material. It does not run the full PostgreSQL/application runtime smoke suite; that remains #206 so normal image CI is not coupled to an environment-dependent integration stack.
