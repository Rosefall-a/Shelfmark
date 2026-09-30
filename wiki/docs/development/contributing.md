# Contributing

## Development layout

Backend development happens under `src/backend`; frontend development happens under `src/frontend`.

Keep backend-only logic in the backend and frontend-only behavior in the frontend. Configuration rules belong in the backend configuration registry rather than being duplicated in Vue components.

## Backend checks

The backend CI uses Python 3.12 and runs:

- pytest;
- Alembic migration graph validation;
- mypy;
- pylint.

The CI migration check requires a valid single Alembic head.

For local checks:

```bash
cd src/backend
mypy --config-file pyproject.toml src
pylint --rcfile=pyproject.toml src
```

Run tests with the development database available:

```bash
docker compose exec -e PYTHONPATH=/app backend python -m pytest tests -q
```

## Frontend checks

From `src/frontend`:

```bash
npm run format
npm run lint
npm run typecheck
npm run test
```

## Database changes

Use Alembic for schema changes.

- Add a new migration instead of editing a migration that has already shipped.
- Keep one migration head.
- Test migrations against a fresh database and an existing database where practical.
- Do not use destructive database recreation as the normal development workflow.

## Configuration changes

For a new environment-backed setting:

1. Add it to the backend configuration registry.
2. Choose ENV, SETUP, or BOTH ownership.
3. Define validation, defaults, visibility, and secrecy.
4. Add explicit persistence mapping if application-owned.
5. Add a safe example to `example.env`.
6. Update the wiki Environment Variables page.
7. Add focused tests for resolution, validation, locking, and secret handling as applicable.

Do not add real credentials to `example.env`.

## Integration changes

If changing OIDC or Playnite behavior, verify the actual API/client contract before documenting it.

In particular:

- OIDC callback paths are generated from the current application address unless a deployment callback URI is explicitly configured.
- OIDC login requires `sub` and an email identity claim, but does not require `email_verified=true`.
- Playnite authenticates with a user API key and uses the `playnite_guid`/folder association for game matching.

## Pull requests

Keep pull requests focused on one change where practical.

For bug fixes, include the related GitHub issue reference in the pull request so the issue can be automatically closed when the PR is merged.

Document user-facing behavior changes in the wiki when they affect setup, configuration, deployment, or normal application usage.
