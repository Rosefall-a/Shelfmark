# Developer control container

The repository has a dedicated /src/devcontainer for local development infrastructure. It is separate from the normal development stack and the real production container.

## Responsibilities

The devcontainer:

1. controls an isolated development Compose project;
2. controls a production-like Compose project using the existing production image;
3. exposes fixed status, health, and log diagnostics;
4. serves the existing /wiki MkDocs site as its documentation viewer.

It does not add a documentation route to the Vue application, and it does not change the real production image.

## Architecture

    Host Docker daemon
          |
          | /var/run/docker.sock
          v
    src/devcontainer
       |-- control UI/API
       |-- Docker CLI + Compose
       |-- MkDocs viewer
       |
       +--> uta-debug-dev
       |      PostgreSQL + backend + frontend
       |
       +--> uta-debug-prod
              production image + PostgreSQL

The Docker socket is intentionally a trusted local developer boundary. Keep the control port localhost-only.

## Starting it

From the repository root:

    docker compose -f src/devcontainer/compose.yaml up --build

Then open http://localhost:9000/ for the control UI or http://localhost:999/ for the wiki viewer.

The ports can be changed with the DEVCONTAINER_*_PORT variables.

## Development environment

The Development action builds the backend and frontend from the current checkout and starts PostgreSQL. It uses the dedicated Compose project uta-debug-dev and named volumes:

- devcontainer_dev_pgdata;
- devcontainer_dev_data.

The stack is isolated from the normal root compose.yaml project and does not reuse the repository's normal data bind mount.

## Production-like environment

The Production-like action uses the same published application image family as the real deployment:

    ghcr.io/rosefall-a/unnamed_tracking_app:<tag>

Set UNNAMED_TRACKING_APP_VERSION when a specific image should be exercised. The stack uses dedicated volumes and binds its application port to localhost.

This is a reproduction environment, not a production deployment. It does not build or modify src/docker-container.

## Lifecycle

The UI exposes only:

- Start — create or update the selected stack;
- Stop — stop and remove its containers and network;
- Reset — also remove that stack's named volumes;
- Status — show Compose state;
- Health — show Compose state and the published application endpoint;
- Logs — show the recent Compose log tail.

Reset is deliberately scoped to uta-debug-dev or uta-debug-prod. The tooling never runs docker system prune, docker volume prune, or another host-wide destructive operation.

## Diagnostics

Diagnostics are collected outside the application where practical:

- Compose project/container state;
- PostgreSQL healthcheck state;
- published application reachability;
- recent container logs.

The control API does not expose arbitrary environment variables, Docker inspect data, connection strings, credentials, OIDC secrets, or API keys.

## Documentation viewer

The devcontainer runs MkDocs against /workspace/wiki/mkdocs.yml. /wiki remains the source of truth and can still be served independently.

The normal application frontend is intentionally unaware of the viewer. There is no /docs application route, no Vue sidebar entry, and no MkDocs build in src/docker-container.

## Security

The Docker socket is a privileged trust boundary. Run this container only for local development and keep its control port bound to 127.0.0.1. Do not expose it through a reverse proxy or public interface.

The repository mount is writable so the developer environment can use the current checkout. Do not mount arbitrary host directories into the devcontainer.

## Troubleshooting

If the control UI cannot reach Docker, verify that /var/run/docker.sock is mounted and that the host Docker daemon is running.

If the Development stack fails to build, use Logs and inspect the backend/frontend build output.

If the Production-like stack fails immediately, check the selected UNNAMED_TRACKING_APP_VERSION and its startup logs. The stack intentionally uses the existing production image rather than a second copy of the production Dockerfile.
