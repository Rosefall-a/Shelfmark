# Startup and Troubleshooting

The production container keeps startup diagnostics available without turning the startup page into a raw log viewer. The page is intentionally concise: it reports lifecycle state and a short failure explanation, while detailed logs remain operator-facing diagnostics.

## Production startup sequence

The production image starts approximately in this order:

1. Initialise startup status and diagnostic files.
2. Start Nginx with the startup/failure configuration.
3. Validate database configuration.
4. Wait for PostgreSQL.
5. Run Alembic migrations.
6. Start Uvicorn on the internal loopback address.
7. Wait for the backend health endpoint.
8. Validate resolved application configuration.
9. Switch Nginx to the ready configuration and reload it.
10. Verify the frontend.
11. Continue monitoring the backend.

The implementation is in \`src/docker-container/entrypoint.sh\`.

## Failure states

Startup records explicit states including:

- \`CONFIGURATION_FAILED\`
- \`DATABASE_FAILED\`
- \`MIGRATION_FAILED\`
- \`BACKEND_FAILED\`
- \`BACKEND_TIMEOUT\`
- \`FRONTEND_FAILED\`
- \`BACKEND_CRASHED\`

Nginx can remain available when startup fails so the diagnostic page can explain what happened.

## Startup page

The static startup page reports application starting, database state, migration state, backend state, frontend state, application ready, and application failed. Normal startup does not render backend, migration, Nginx, or Docker log output. On failure the spinner is replaced by a failure indicator and a concise diagnostic message.

Raw logs are intentionally not rendered by default: they are useful for operators but noisy for normal startup. The startup page does not add a reload button or other log-management controls.

## Detailed diagnostics

Use the container logging facilities first:

```text
docker logs <container>
docker logs -f <container>
```

Docker exposes container stdout/stderr through docker logs. The production entrypoint writes lifecycle messages there and Nginx errors are directed to stderr. Detailed backend output is retained at /run/unnamed-tracking/backend.log; migration output is retained at /run/unnamed-tracking/migration.log.

If detailed file contents are needed, use docker exec while the container is available or docker cp to retrieve them. Do not inspect Docker's internal logging-driver files directly.

## Diagnostic endpoints

When startup diagnostics are available, inspect:

\`\`\`text
/_startup/status.json
/_startup/details.txt
\`\`\`

These expose the current state and human-readable startup details.

## Configuration failures

A \`CONFIGURATION_FAILED\` state means startup validation found an unrecoverable configuration problem. Check the startup details for the specific field or configuration group.

Configuration values may come from environment variables, persisted configuration or registry defaults. See [Configuration](../setup/configuration.md).

## Database and migration failures

If startup cannot connect to PostgreSQL, inspect the database connection settings and database container health.

If migrations fail, startup reports \`MIGRATION_FAILED\` and the migration error is available through the diagnostics.

## Backend failures

If Uvicorn cannot start, never becomes healthy, or crashes after startup, inspect \`/_startup/backend.log\`. The status distinguishes startup failure, timeout and later crash.

## Frontend failures

The production image checks that the built frontend can be served before switching to the normal Nginx configuration. A frontend failure is reported as \`FRONTEND_FAILED\`.


## Secrets

The production entrypoint does not print passwords, tokens, API keys, SMTP credentials, private keys, webhook secrets, or session secrets. Detailed logs remain operator-only diagnostics because application components may produce their own log output.
