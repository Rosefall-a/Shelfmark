# Developer control container

The repository has a dedicated /src/devcontainer for local developer infrastructure. It is separate from the normal root Compose workflow and the real production image.

## What it provides

- A Docker-socket-backed control UI.
- Any number of isolated development Compose instances.
- Any number of isolated production-like Compose instances.
- Per-instance application ports and Compose project names.
- Local source builds or explicitly selected image tags.
- One shared environment file for all managed instances.
- Fast source feedback and live MkDocs documentation.

## Start

    cp src/devcontainer/.env.example src/devcontainer/.env
    docker compose -f src/devcontainer/compose.yaml up --build

Then open http://localhost:9000/ or http://localhost:999/.

## Multiple environments

Use Add instance in the control UI. Every instance needs a unique project name and application port. For example, three development instances can use 5173, 5174 and 5175 while a production-like instance uses 8180.

Instance definitions are kept in the ignored src/devcontainer/.instances.json file so they survive control-container restarts without becoming repository configuration.

## Build and image tags

Build from checkout uses the current repository source. Production-like builds use the repository root as the context and src/docker-container/Dockerfile as the Dockerfile; that Dockerfile copies src/backend and src/frontend, so the repository root context is required.

Use image/tag skips building and pulls the exact configured tag. This supports testing published releases or another registry image. Compose supports services with both build and image definitions, with pull/build behavior selected by policy.

## Shared environment

All managed stacks use one src/devcontainer/.env. The control UI can edit it. Save the environment and use Rebuild & restart on a stack to apply it.

## Fast source feedback

Development maps src/backend/src to /app/src and runs Uvicorn reload. It maps src/frontend/src and public and uses Vite polling. Normal code edits therefore take effect without rebuilding.

For dependency, Dockerfile, or other image-level changes, use Rebuild & restart.

## Wiki live updates

MkDocs runs against /workspace/wiki itself rather than a copied build artifact. Markdown, navigation and MkDocs configuration changes are therefore picked up by MkDocs live reload immediately.

## Lifecycle and isolation

Each instance maps to its own Compose project. Stop/reset operations are scoped to that project. Reset removes only that project's volumes and never calls Docker-wide prune commands.

The UI exposes no arbitrary Docker command runner. Docker socket access remains a trusted local boundary.
