# Development

This page describes the current repository development workflow. The backend and frontend are developed as separate applications and are combined by the production container.

## Repository layout

| Path | Purpose |
|---|---|
| `src/backend/src/` | FastAPI application, configuration, API routes, database models, migrations, and feature code. |
| `src/backend/tests/` | Backend pytest suite. |
| `src/frontend/src/` | Vue application, services, router, state, and views. |
| `src/frontend/` | Vite/Vue package and frontend tooling. |
| `src/docker-container/` | Production Docker image, Compose deployment, Nginx configuration, and startup scripts. |
| `wiki/` | This documentation site. |

## Local development

The repository's development Compose file starts PostgreSQL, the backend, and the Vite frontend:

```bash
docker compose up -d --build
```

The development stack exposes the Vite frontend on port `5173`. The Vite development server proxies `/api` requests to the backend service.

The development Compose file reads `.env`. Copy the repository's `example.env` as a starting point and provide the database/bootstrap values required by the configuration handler.

For a clean database reset, the repository currently uses:

```bash
docker compose down -v
docker compose up -d --build
```

The `-v` flag removes the development PostgreSQL volume, so do not use it when you need to preserve local database data.

## Backend development

Backend code targets Python 3.12.

From `src/backend`:

```bash
mypy --config-file pyproject.toml src
pylint --rcfile=pyproject.toml src
```

Run the backend tests with the development database running:

```bash
docker compose exec -e PYTHONPATH=/app backend python -m pytest tests -q
```

The pytest configuration uses automatic asyncio support and the test suite is under `src/backend/tests`.

## Frontend development

The frontend uses Vue, Vite, TypeScript, ESLint, Prettier, and Vitest.

From `src/frontend`:

```bash
npm ci
npm run dev
```

Checks:

```bash
npm run lint
npm run format
npm run typecheck
npm run test
```

Use `npm run format:fix` when formatting needs to be corrected.

For early frontend development/testing, `VITE_USE_MOCK_DATA=true` makes the frontend services use their mock behavior. This variable is consumed directly by Vite and is intentionally outside the backend setup registry.

## Database migrations

The backend uses Alembic.

Generate a migration from the backend environment with:

```bash
docker compose exec backend alembic -c alembic.ini revision --autogenerate -m "describe the schema change"
```

Apply migrations with:

```bash
docker compose exec backend alembic -c alembic.ini upgrade head
```

The backend startup process also applies pending migrations. Keep the migration history on a single head and add a new migration rather than rewriting one that has already been shipped.

For migration changes, test both a fresh database and an existing database where practical.

### What happens on start

Both the development backend container and the production image run `python -m src.database.migrate` before the API starts. It waits for the database, takes a lock so two starting containers never migrate at once, then decides what to do from the version the database records:

| Database state | What the runner does |
| --- | --- |
| Empty | Builds everything from the migrations. |
| Version is in this code's history | Runs the migrations newer than it. |
| Version is not in the history (the history was squashed since), or tables exist with no version | Attaches the database to the first migration, keeping its data, and runs every migration after it. It then checks that every table and column the models need exists; if something is still missing it stops and names it. |

A real failure stops startup with the reason instead of retrying the same error.

### Writing a migration that is safe to re-run

Because an adopted database is attached to the first migration and then runs every later one, each migration after the baseline must be safe on a database that already has part of what it adds. Use the create-if-missing wrappers in `src/database/migration_helpers.py` (`create_table_if_missing`, `add_column_if_missing`, `create_index_if_missing`, `create_unique_constraint_if_missing`, `drop_index_if_exists`) instead of calling `op.*` directly, and name every constraint explicitly so it can be looked up. `tests/test_migrations.py` re-runs the whole chain on the already-migrated test database to catch a migration that is not.

## Configuration development

Application setup/configuration is registry-driven:

```text
config_registry.py
       |
       v
EnvConfigHandler
       |
       +--> process environment
       +--> .env
       +--> persisted application configuration
       +--> startup-mode defaults
       |
       v
setup/configuration API
       |
       v
generic Vue setup renderer
```

When adding a normal configuration field:

1. Add it to `src/backend/src/core/config_registry.py`.
2. Choose its source ownership: ENV, SETUP, or BOTH.
3. Define type, default, validation, visibility, and secrecy.
4. Add explicit persistence mapping when the setting is application-owned.
5. Add a safe example to `example.env`.
6. Update the wiki's Environment Variables page when it is deployment-facing.
7. Add focused tests.

Do not add a normal environment-backed setup field directly to `Setup.vue`; the registry is the source of truth.

## Production image

The production image is built from:

```bash
docker build -f src/docker-container/Dockerfile .
```

It contains the built Vue frontend, Python backend, Nginx, and startup scripts. The image exposes HTTP on container port 80.

The published deployment Compose file is `src/docker-container/compose.yaml`.

## Before opening a pull request

For backend changes, run the backend tests, mypy, pylint, and migration checks relevant to the change.

For frontend changes, run linting, formatting, type checking, and Vitest.

For schema changes, verify the Alembic graph remains a single head and test migration behavior.

Keep user-facing setup/configuration/deployment changes documented in the wiki.
