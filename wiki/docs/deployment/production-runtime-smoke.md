# Production Runtime Smoke Tests

The production runtime smoke suite validates the assembled production Docker image as a running application. It is separate from the production image build/publish workflow and from the production hardening/TLS work tracked by issues #205 and #204.

## What it validates

The smoke harness in `src/docker-container/smoke/run.sh` uses the production Dockerfile and a disposable PostgreSQL 18 container.

The happy-path sequence is:

1. Start PostgreSQL and wait for `pg_isready`.
2. Stop PostgreSQL and start the production image, proving the Nginx startup/diagnostic layer is available while the database is unavailable.
3. Start PostgreSQL again.
4. Wait for the entrypoint to run migrations and start FastAPI.
5. Confirm the status endpoint reports `READY` with database, migrations, backend, and frontend all ready.
6. Confirm the Alembic database revision equals the image's current Alembic head(s).
7. Confirm Nginx is using the production configuration.
8. Confirm the compiled frontend is served rather than the startup page.
9. Confirm FastAPI's internal `/health` endpoint is reachable.
10. Log in through Nginx and call `/api/auth/me`, exercising a database-backed API request through the production edge.
11. Exercise the shutdown cleanup path.

## Controlled failures

The suite also checks the diagnostic behavior for:

- missing database configuration (`CONFIGURATION_FAILED`);
- an unavailable database, where the startup page remains reachable while the entrypoint waits;
- a migration failure caused by a fresh database whose application user cannot create tables (`MIGRATION_FAILED`);
- a backend import/startup failure (`BACKEND_FAILED`).

The unavailable-database scenario is intentionally stopped after confirming the waiting/diagnostic state rather than waiting the entrypoint's full bounded timeout. This keeps CI practical while still testing the failure-visible path.

The current production entrypoint's graceful shutdown behavior is part of the separate hardening issue #205. This suite therefore verifies that the cleanup trap runs when shutdown is requested, but does not turn the current pre-hardening shutdown semantics into a second implementation of #205.

## CI triggers and relationship to image builds

The dedicated `.github/workflows/production-runtime-smoke.yml` workflow:

- runs on relevant pull requests;
- can be started manually with **workflow_dispatch**;
- runs weekly against `main`;
- also runs after the existing production image workflow successfully completes on `main`.

For the `workflow_run` path, the suite pulls the exact `sha-<commit>` image published by the production image workflow. For pull requests, manual runs, and the scheduled run, it builds the production Dockerfile into a local image because a pull-request image is not published.

The existing `.github/workflows/docker-container.yml` workflow is not modified. Its image build/publish behavior remains independent.

The smoke workflow is intentionally not added to branch protection by this change. Once the runtime environment is proven deterministic, maintainers can make it a required check without changing the harness.

## Diagnostics

The harness always writes a diagnostic directory. On failure it collects, where available:

- `docker compose ps -a`;
- PostgreSQL and production-container logs with timestamps;
- the production status JSON;
- startup detail output;
- the backend startup log;
- `nginx -T` output;
- controlled-failure container logs and status/details;
- captured frontend/API/Alembic outputs.

The workflow uploads this directory as an artifact even when the smoke test fails. Errors are not suppressed merely to keep the CI output short.

## What it deliberately does not test

The suite does not:

- replace unit/backend/frontend test suites;
- make normal backend checks depend on this workflow;
- test TLS/certificates or HTTPS;
- implement or validate the runtime hardening from #205;
- test external metadata providers;
- perform a full browser/E2E test of the Vue application;
- require the production image build workflow to execute the runtime suite in the same job.

Those concerns remain separate so a runtime regression can be diagnosed without conflating it with image packaging, TLS, or unrelated application integration tests.

## Local execution

Build the production image first:

```bash
docker build -f src/docker-container/Dockerfile -t unnamed_tracking_app:runtime-smoke .
```

Then run:

```bash
SMOKE_IMAGE=unnamed_tracking_app:runtime-smoke \
  SMOKE_PROJECT_NAME=unnamed-tracking-runtime-local \
  bash src/docker-container/smoke/run.sh
```

The harness requires Docker Compose and writes diagnostics to `SMOKE_ARTIFACT_DIR` when set.

