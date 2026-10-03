# Developer control container

This is trusted local developer tooling, separate from the application runtime.

## Start

    cp src/devcontainer/.env.example src/devcontainer/.env
    docker compose -f src/devcontainer/compose.yaml up --build

Open http://localhost:9000/ for the control UI or http://localhost:999/ for the live MkDocs viewer.

## Managed instances

The UI keeps instance definitions in the ignored src/devcontainer/.instances.json file. Every instance is an independent Docker Compose project with its own application port and volumes.

The instance **name and Compose project are always the same**. They are generated from the stack type:
- `dev`, `dev-2`, `dev-3`, ...
- `prod`, `prod-2`, `prod-3`, ...

The number is added automatically when another instance of the same type already exists. Name/project are not manually edited.

## Build and image modes

Each instance chooses either:
- **Build from source** — build the current checkout.
- **Use GHCR tag** — pull the exact final tag from the fixed repositories.

The final tag field is shown and editable only for GHCR mode. Selecting source mode hides and disables it. If a tag is entered while editing the mode, the UI automatically switches to GHCR mode.

The three repositories are always:
- `ghcr.io/rosefall-a/unnamed_tracking_app:<tag>`
- `ghcr.io/rosefall-a/unnamed_tracking_app-frontend:<tag>`
- `ghcr.io/rosefall-a/unnamed_tracking_app-backend:<tag>`

**Build all 3 images from source** builds and tags all three locally with the selected final tag. It does not push to GHCR.

## Deploy and redeploy

**Deploy** starts an unavailable stack and waits for its health checks. Once healthy, the control switches to **Stop**.

**Redeploy** rebuilds/recreates the stack and always requests fresh image pulls. For source mode this also refreshes build inputs/base images; for GHCR mode it pulls the selected tag before recreating containers.

**Reset volumes** stops the selected Compose project and removes only its volumes. No Docker-wide prune commands are used.

## Shared environment

All instances use the same src/devcontainer/.env, with optional per-instance overrides under `src/devcontainer/environments/`. Rebuild/redeploy after saving configuration to apply it.

## Fast source and wiki feedback

Development maps the backend src and frontend src/public into the running containers. Backend uses Uvicorn reload and frontend uses Vite polling, so normal source edits are picked up without rebuilding. Use Redeploy after Dockerfile, dependency, or other image-level changes.

MkDocs reads /workspace/wiki directly, so wiki edits appear through MkDocs live reload immediately.

## Security

The Docker socket is a privileged trust boundary. Keep the control and application ports on localhost and use this container only as trusted developer tooling.