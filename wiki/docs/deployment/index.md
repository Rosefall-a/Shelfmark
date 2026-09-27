# Deployment

Unnamed Tracking App provides a production Docker image and a separate development Compose stack.

## Production

Use src/docker-container/compose.yaml and the published image ghcr.io/rosefall-a/unnamed_tracking_app:<tag>.

The production deployment includes PostgreSQL 18, persistent application data at /data, persistent PostgreSQL storage, and Nginx as the public HTTP edge.

See [Production Docker Image](production-docker.md).

## Development

Use the root compose.yaml for development. It keeps frontend and backend containers separate and exposes Vite on port 5173.

## HTTPS

The production container supports optional embedded Nginx TLS. HTTP-only remains the default. TLS is enabled through deployment environment variables and externally mounted certificate/key files; the image does not generate certificates.

Set `NGINX_TLS_ENABLED=true`, configure `NGINX_TLS_CERTIFICATE` and `NGINX_TLS_PRIVATE_KEY` to the mounted PEM paths, and publish host port 443 to container port 443. Set `NGINX_TLS_REDIRECT_HTTP=true` when HTTP should redirect to HTTPS after the production configuration becomes ready. For HTTPS deployments, set `AUTH_COOKIE_SECURE=true`.

See [Production Docker Image](production-docker.md) for certificate mounts, permissions, OIDC/proxy behavior, and TLS troubleshooting.
