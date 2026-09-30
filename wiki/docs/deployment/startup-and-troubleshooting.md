# Startup and Troubleshooting

The production container separates startup diagnostics from the normal application frontend. Configuration or backend failures can still be displayed through Nginx.

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

## Diagnostic endpoints

When startup diagnostics are available, inspect:

\`\`\`text
/_startup/status.json
/_startup/details.txt
/_startup/backend.log
\`\`\`

These expose the current state, human-readable details and backend startup log.

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

