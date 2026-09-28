# Developer control container

This is a local developer control environment, not part of the application runtime.

It has access to the host Docker socket so it can create and manage two isolated Compose projects:

- Development: builds the normal backend/frontend images and uses dedicated named volumes.
- Production-like: runs the existing published production image with production-style startup and Nginx behavior, but uses dedicated debug volumes and localhost-only ports.

The container also serves the repository's existing MkDocs wiki at port 999. The normal Vue frontend and the real production container are not modified to host the documentation viewer.

## Start

From the repository root:

    docker compose -f src/devcontainer/compose.yaml up --build

Open the control UI at http://localhost:9000/ or the documentation at http://localhost:999/.

The control UI exposes only fixed lifecycle and diagnostic actions. It does not provide an arbitrary Docker command runner.

## Docker socket

The Docker socket is equivalent to powerful host Docker access. Keep the control port bound to localhost and only run this container as trusted developer tooling. Do not publish it to a LAN or the public internet.

The repository mount lets the container read the current backend/frontend/wiki sources. Managed application data is stored in Compose named volumes and is separate from the normal development and production data directories.

## Environments

Development uses a dedicated Compose project and builds from /workspace/src/backend and /workspace/src/frontend.

Production-like uses ghcr.io/rosefall-a/unnamed_tracking_app:${UNNAMED_TRACKING_APP_VERSION:-latest}. It is intentionally not production: its port is localhost-only, its data volumes are debug-only, and it is controlled by this developer container.

Set UNNAMED_TRACKING_APP_VERSION before starting the production-like stack if a particular published image should be exercised.

## Reset

Reset is scoped to the corresponding project name and removes only that project's containers, networks, and named volumes. It never runs Docker-wide prune commands.

## Documentation

The viewer is MkDocs Material and reads /workspace/wiki/mkdocs.yml directly. This keeps /wiki as the single source of truth and avoids adding documentation routes to the application frontend or production image.

The existing standalone wiki workflow remains valid:

    cd wiki
    mkdocs serve -a 0.0.0.0:999

## Troubleshooting

Use the control UI's Status, Health, and Logs actions. Logs are intentionally local diagnostics and may contain application-generated messages; do not expose the control port to untrusted users.

From a shell, the same projects can be inspected with:

    docker compose --project-name uta-debug-dev -f src/devcontainer/compose.dev.yaml ps
    docker compose --project-name uta-debug-prod -f src/devcontainer/compose.prod.yaml ps
