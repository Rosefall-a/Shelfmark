# Developer control container

This is trusted local developer tooling, separate from the application runtime.

## Start

    cp src/devcontainer/.env.example src/devcontainer/.env
    docker compose -f src/devcontainer/compose.yaml up --build

Open http://localhost:9000/ for the control UI or http://localhost:999/ for the live MkDocs viewer.

## Managed instances

The UI keeps instance definitions in the ignored src/devcontainer/.instances.json file. Every instance is an independent Docker Compose project with its own project name and application port. Docker Compose project names isolate containers, networks, and named volumes, so you can run several copies simultaneously.

For example: dev-a on 5173, dev-b on 5174, dev-c on 5175, and prod-a on 8180.

## Build and image modes

Each instance can either build from the checkout or use an image/tag. Production-like local builds use src/docker-container/Dockerfile with the repository root as the build context, so the real production backend/frontend/Nginx image is exercised.

Image mode skips building and pulls the configured tag. Production-like instances accept tags such as ghcr.io/rosefall-a/unnamed_tracking_app:latest. Development instances accept separate backend and frontend image tags.

## Shared environment

All instances use the same src/devcontainer/.env. The control UI edits database credentials, application secret, initial admin credentials, and cookie security for every managed instance. Rebuild/restart an instance after saving to apply changes.

## Fast source and wiki feedback

Development maps the backend src and frontend src/public into the running containers. Backend uses Uvicorn reload and frontend uses Vite polling, so normal source edits are picked up without rebuilding. Use Rebuild & restart after Dockerfile, dependency, or other image-level changes.

MkDocs reads /workspace/wiki directly, so wiki edits appear through MkDocs live reload immediately.

## Reset and security

Reset is scoped to the selected Compose project and removes only its containers, network and named volumes. No Docker-wide prune commands are used.

The Docker socket is a privileged trust boundary. Keep the control and application ports on localhost and use this container only as trusted developer tooling.
