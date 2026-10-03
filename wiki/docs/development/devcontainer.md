# Developer control container

The repository has a dedicated /src/devcontainer for local developer infrastructure. It is separate from the normal root Compose workflow and the real production image.

## What it provides

- A Docker-socket-backed control UI.
- Any number of isolated development Compose instances.
- Any number of isolated production-like Compose instances.
- Automatically generated instance names/project names with numbering.
- Per-instance application ports.
- Local source builds or explicitly selected image tags.
- One shared environment file plus optional per-instance overrides.
- Fast source feedback and live MkDocs documentation.

## Start

    cp src/devcontainer/.env.example src/devcontainer/.env
    docker compose -f src/devcontainer/compose.yaml up --build

Then open http://localhost:9000/ or http://localhost:999/.

## Instance naming

The control UI deliberately does not ask for separate Name and Project values. They are always identical and are generated from the stack type:

- `dev`, `dev-2`, `dev-3`, ...
- `prod`, `prod-2`, `prod-3`, ...

This keeps the visible identity and Docker Compose project identity synchronized while still allowing multiple stacks of the same type.

## Build and image tags

Every managed instance chooses either **Build from source** or **Use GHCR tag**. The tag defaults to `main`, and the tag field is only editable for GHCR mode. Entering a tag automatically selects GHCR mode.

The image repositories are fixed to match the repository's CI naming:

- `ghcr.io/rosefall-a/unnamed_tracking_app:<tag>` — production-like image.
- `ghcr.io/rosefall-a/unnamed_tracking_app-frontend:<tag>` — frontend.
- `ghcr.io/rosefall-a/unnamed_tracking_app-backend:<tag>` — backend.

**Build from source** builds the current checkout. **Use GHCR tag** pulls the selected final tag.

The Images panel also has **Build all 3 images from source**, which locally creates all three fixed repository/tag combinations. It does not push to GHCR.

Production-like source builds use the repository root as the context and `src/docker-container/Dockerfile`; this is required because that Dockerfile copies both backend and frontend source.

## Deploy lifecycle

The primary action follows the live state: an unavailable stack shows **Deploy**, while a healthy stack shows **Stop**.

**Redeploy** always asks Compose to pull fresh images and then waits for the application to become healthy. Source mode still builds the checkout; GHCR mode uses the selected remote tag without a local build.

**Reset volumes** is deliberately separate and removes only the selected Compose project's containers, network and named volumes.

## Environment files

There is one global `src/devcontainer/.env`, plus one optional `.env` override per managed instance under the ignored `src/devcontainer/environments/` directory. The control UI opens each file as a plain text editor so you can paste an existing `.env` without translating it into individual fields.

The global file is loaded first and the instance file is loaded second, so instance values override global values. Save the relevant file and use Redeploy to apply it.

## Fast source feedback

Development maps src/backend/src to /app/src and runs Uvicorn reload. It maps src/frontend/src and public and uses Vite polling. Normal code edits therefore take effect without rebuilding.

For dependency, Dockerfile, or other image-level changes, use Redeploy.

## Wiki live updates

MkDocs runs against /workspace/wiki itself rather than a copied build artifact. Markdown, navigation and MkDocs configuration changes are therefore picked up by MkDocs live reload immediately.

## Lifecycle and isolation

Each instance maps to its own Compose project. Stop/reset operations are scoped to that project. Reset removes only that project's volumes and never calls Docker-wide prune commands.

The UI exposes no arbitrary Docker command runner. Docker socket access remains a trusted local boundary.