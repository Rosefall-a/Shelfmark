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

Both managed environments use the same shared configuration stored in `src/devcontainer/.env`. The control UI can edit this configuration; restart a stack after saving to apply changes.

The shared values include database credentials, the application secret key, initial admin credentials, and cookie security. This is a local developer environment: do not put production secrets in this file.

Development builds the backend/frontend from the current checkout.

Production-like builds the existing `src/docker-container` production image locally, so its backend and Nginx startup path are exercised rather than using a separate debug backend. It uses the same shared environment and dedicated production-like volumes.

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
