# Developer Debugging

## Development

The new isolated development Compose file is compose.dev.yaml. It runs PostgreSQL, the backend, and the Vite frontend with localhost-only ports 55432, 8000, and 5173. It waits for PostgreSQL and applies Alembic migrations before Uvicorn. Stop it with docker compose -f compose.dev.yaml down; reset its named database volume with docker compose -f compose.dev.yaml down -v. The bind-mounted data-dev directory is preserved.

The existing root compose.yaml remains unchanged and is still the normal development workflow.

## Production-like

src/docker-container/compose.debug.yaml builds the existing production Docker image and exercises its Nginx/startup/migration/backend/frontend readiness path. It binds localhost:8081 by default and uses separate named application/database volumes.

Production-like is not production. It uses debug/local bootstrap configuration and must never use a production database or production credentials.

Stop it with docker compose -f src/docker-container/compose.debug.yaml down. Reset only its named volumes with docker compose -f src/docker-container/compose.debug.yaml down -v.

## Diagnostics

GET /health remains a minimal liveness endpoint. GET /health/diagnostics is enabled only when DEBUG=true or development/testing startup mode is selected. It reports environment, backend/database state, and migration state/head count. It never returns passwords, tokens, connection strings, API keys, OIDC secrets, or arbitrary environment values.

The existing production-container startup diagnostics under /_startup/ remain the detailed lifecycle view. Inspect status.json and details.txt first when startup fails.

## Logs and health checks

Development: docker compose -f compose.dev.yaml ps and docker compose -f compose.dev.yaml logs -f backend.

Production-like: docker compose -f src/docker-container/compose.debug.yaml ps and docker compose -f src/docker-container/compose.debug.yaml logs -f app.

Check /health and /health/diagnostics in debug environments. For production-like startup failures also check /_startup/status.json and /_startup/details.txt.

## Integrated documentation

The production image builds the existing wiki/ MkDocs source during Docker build and serves the generated site at /docs/. wiki/mkdocs.yml remains the source of truth for navigation, and site_url is /docs/ so links and assets resolve under the integrated path. No Markdown is copied into frontend components.

The standalone wiki remains available through the existing GitHub Pages workflow and can be served locally with mkdocs serve -a 127.0.0.1:9999 from wiki after installing wiki/requirements.txt.

## Troubleshooting

1. Check service health and PostgreSQL logs.
2. Check /health and /health/diagnostics.
3. For production-like startup problems inspect /_startup/status.json and /_startup/details.txt.
4. For migration failures inspect the app log; reset only a disposable debug volume.
5. Rebuild MkDocs from wiki/ if documentation navigation/assets fail; do not create a second documentation copy.
