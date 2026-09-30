# Deployment

Unnamed Tracking App provides a production Docker image and a separate development Compose stack.

## Production

Use src/docker-container/compose.yaml and the published image ghcr.io/rosefall-a/unnamed_tracking_app:<tag>.

The production deployment includes PostgreSQL 18, persistent application data at /data, persistent PostgreSQL storage, and Nginx as the public HTTP edge.

See [Production Docker Image](production-docker.md).

## Development

Use the root compose.yaml for development. It keeps frontend and backend containers separate and exposes Vite on port 5173.

## HTTPS

TLS and certificate generation are not included in the production image. Use an HTTPS-capable reverse proxy when TLS is required and set AUTH_COOKIE_SECURE=true.
