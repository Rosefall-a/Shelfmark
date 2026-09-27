# Production Runtime Smoke Test Architecture

The runtime smoke suite intentionally tests the production artifact rather than a development stack.

## Components

```
production Dockerfile
        |
        v
unnamed_tracking_app:runtime-smoke
        |
        +---- Nginx
        +---- FastAPI/Uvicorn
        +---- compiled Vue frontend
        |
        +---- disposable PostgreSQL 18
```

The PostgreSQL container is created by `src/docker-container/smoke/compose.yaml`. The production application receives the individual `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` values. This deliberately exercises the same component-based database normalization used by the production entrypoint and backend settings.

The smoke harness does not reuse the development Compose file.

## Why Compose is used

Compose gives the test an isolated network with the database reachable as `db`, while keeping the production image itself unchanged. The harness controls database availability explicitly: it starts and stops the disposable database to prove that the static Nginx diagnostic layer is available before the database is ready.

For controlled failures, the harness launches additional instances of the same production image:

- an image with no database configuration;
- an image pointed at a nonexistent database host;
- an image pointed at a fresh database where the migration user cannot create tables;
- an image with a temporary `src.main` replacement that raises during backend import.

The temporary backend module exists only in the CI/test container and is never built into the production image.

## Published-image validation

The existing production image workflow remains unchanged. On a successful main-branch production-image workflow run, the smoke workflow receives that workflow's commit SHA and pulls `ghcr.io/rosefall-a/unnamed_tracking_app:sha-<commit>`.

For pull requests and manually/scheduled source runs, the smoke workflow builds the current production Dockerfile locally because the production image is not published for pull requests.

## Failure handling

`run.sh` uses an exit trap to collect logs and state before removing the Compose project. This is important because the failure state itself is part of the test: Nginx may intentionally remain alive while the application is failed.

The artifact contains enough state to distinguish a migration failure, backend startup failure, Nginx handoff failure, and database readiness problem without rerunning the job.

## Stability and scope

The workflow is a dedicated runtime validation workflow. It does not alter the normal backend/frontend test workflows and does not make PostgreSQL a dependency of ordinary unit tests.

It is triggered for changes that can affect the production artifact, plus manual and weekly runs. It is advisory rather than branch-protection-required initially.

The hardening work in #205 and HTTPS/TLS work in #204 are deliberately excluded. The smoke suite tests the current HTTP production artifact and documents the current shutdown limitation rather than implementing hardening behavior itself.
