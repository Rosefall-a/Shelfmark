# AGENTS.md

## Purpose

This repository is the **Unnamed Tracking App host application**.

It contains the application backend, frontend, database/migration layer, deployment infrastructure, plugin host/runtime/manager, plugin security boundaries, and user-facing plugin management.

Agents must preserve the application's existing architectural boundaries. In particular:

* The host application owns plugin infrastructure.
* Third-party/official plugin implementations belong in `Rosefall-a/unnamed_tracking_app_plugins`.
* Plugins must communicate through the supported public Plugin API/gateway.
* Do not copy plugin implementations, test-only plugin fixtures, or plugin-repository concerns into the host merely to make a test pass.
* Do not move host/runtime infrastructure into the plugin repository.

When working on plugin functionality, treat the two repositories as separate projects connected by a versioned public contract.

---

## Repository Structure

The repository is broadly organized as follows:

```text
.
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
├── src/
│   ├── backend/
│   │   ├── src/
│   │   │   ├── api/
│   │   │   ├── core/
│   │   │   ├── database/
│   │   │   ├── features/
│   │   │   └── helpers/
│   │   └── tests/
│   ├── frontend/
│   │   └── src/
│   │       ├── components/
│   │       ├── services/
│   │       ├── stores/
│   │       └── ...
│   └── docker-container/
├── wiki/
├── compose.yaml
└── example-docker-compose.yaml
```

Do not reorganize this structure without a concrete architectural reason and a corresponding PR explanation.

Prefer extending the existing directory responsible for a concern rather than introducing a new top-level architectural layer.

---

# 1. General Coding Rules

## 1.1 Preserve existing architecture

Before adding code:

1. Find the existing implementation responsible for the same concern.
2. Understand its callers and tests.
3. Extend the existing abstraction when possible.
4. Reuse existing helpers/services/types.
5. Only introduce a new abstraction when the existing one genuinely cannot represent the new behavior.

Avoid parallel implementations of the same concept.

If two implementations are intentionally different, document why.

Do not introduce an abstraction merely because it makes one file shorter.

## 1.2 Make the smallest coherent change

Agents should:

* modify only files relevant to the task;
* avoid unrelated formatting churn;
* avoid wholesale file rewrites;
* preserve existing comments and structure unless they are incorrect;
* avoid changing public APIs unnecessarily;
* avoid renaming unrelated symbols;
* avoid dependency upgrades unless required;
* avoid changing CI merely to make a test pass;
* avoid deleting tests or CI checks.

If formatting a file is required, keep the formatting change scoped to the affected code where possible.

## 1.3 Follow existing patterns

Before creating a new module, locate one or more analogous modules and copy their **architectural pattern**, not their code blindly.

Existing conventions take precedence over generic framework tutorials.

---

# 2. Python Backend

The backend targets Python 3.12.

The repository uses:

* FastAPI;
* SQLAlchemy;
* Alembic;
* Pydantic;
* pytest;
* pytest-asyncio;
* mypy;
* pylint;
* Ruff.

The backend source lives under:

```text
src/backend/src/
```

with tests under:

```text
src/backend/tests/
```

## 2.1 Formatting and linting

Follow the repository's existing Ruff configuration.

Important existing settings include:

* Python 3.12;
* Ruff line length of 100;
* double quotes;
* spaces for indentation;
* import sorting;
* pycodestyle;
* Pyflakes;
* bugbear checks.

Pylint also uses a 120-character maximum line length.

Do not introduce a second formatting convention.

Run the repository's configured checks rather than substituting a personal formatter configuration.

## 2.2 Naming

Use normal Python conventions:

* `snake_case` for modules, functions, variables, and attributes;
* `PascalCase` for classes;
* `UPPER_SNAKE_CASE` for constants;
* descriptive names rather than abbreviations;
* boolean values should read naturally, e.g. `is_enabled`, `has_permission`, `can_install`.

Follow the names already established in the surrounding module.

## 2.3 FastAPI

FastAPI route definitions belong at the API boundary.

Keep route handlers thin where the surrounding feature already follows that pattern.

Prefer:

```text
route
  → feature/application logic
  → persistence/service/helper
```

rather than placing substantial business logic directly in route functions.

Do not make unrelated database queries, plugin-runtime operations, or external-provider operations part of an endpoint simply because they are convenient there.

Preserve:

* authentication;
* authorization;
* request validation;
* response models;
* error semantics;
* dependency injection.

When adding an endpoint, add or update the appropriate tests.

## 2.4 Async code

Use asynchronous APIs consistently with the surrounding code.

Do not introduce blocking operations into async request paths.

Do not convert an existing async subsystem to synchronous code without an explicit architectural reason.

When calling external providers or performing potentially expensive operations, follow the existing service/application patterns.

Avoid creating unnecessary tasks or background workers.

## 2.5 SQLAlchemy

Keep database access within the existing database/feature boundaries.

Prefer the repository's existing model and session patterns.

Do not:

* open ad-hoc database connections inside route handlers;
* duplicate model definitions;
* bypass established repositories/services without reason;
* access database internals from unrelated features;
* put business logic into migration files.

When changing a model:

1. update the model;
2. generate the corresponding Alembic migration;
3. inspect the generated migration manually;
4. make it safe and deterministic;
5. add/update tests;
6. verify upgrade behavior.

## 2.6 Alembic migrations

Database migrations are part of the application's compatibility surface.

The migration history is intended to remain a **single linear history**.

Generate migrations using the repository's normal Alembic command:

```bash
docker compose exec backend alembic -c alembic.ini revision --autogenerate -m "description"
```

Never blindly trust autogenerated migrations.

Review them for:

* incorrect column operations;
* unintended drops;
* duplicate operations;
* incorrect defaults;
* nullable/non-nullable transitions;
* data migration requirements;
* index/constraint changes;
* upgrade/downgrade correctness.

Do not manually edit an old migration to solve a new schema change unless there is a documented migration-repair reason.

New migrations should be safe to apply to databases created from earlier migrations.

Do not create multiple competing heads.

---

# 3. Backend Feature Architecture

The backend uses feature-oriented organization.

Existing areas include:

```text
api/
core/
database/
features/
helpers/
```

When adding functionality, determine which layer owns it.

### `api/`

Use for API-facing concerns and route composition.

### `core/`

Use for application-wide infrastructure/configuration/security concerns.

### `database/`

Use for models, database configuration, migrations, and database-specific infrastructure.

### `features/`

Use for application functionality.

Prefer feature-local logic over adding generic global helpers prematurely.

### `helpers/`

Use only for genuinely shared helpers.

Do not turn `helpers/` into a dumping ground.

If a helper only belongs to one feature, keep it with that feature.

---

# 4. Testing

Tests are first-class code.

Every meaningful behavioral change should have regression coverage.

Backend tests are located under:

```text
src/backend/tests/
```

The repository's tests use the configured pytest/asyncio setup.

Use tests that exercise the public behavior being changed rather than testing implementation details unnecessarily.

When fixing a bug:

1. reproduce the failure;
2. add a regression test;
3. implement the fix;
4. verify the regression test fails before the fix when practical;
5. run the relevant broader suite.

Do not weaken an assertion simply to make CI pass.

If architecture changes legitimately invalidate an old test, update the test to validate the new public contract.

---

# 5. TypeScript / Vue Frontend

The frontend is Vue 3 + TypeScript + Vite.

Existing tooling includes:

* ESLint;
* Prettier;
* TypeScript;
* `vue-tsc`;
* Vitest.

Relevant commands include:

```bash
npm run lint
npm run format
npm run format:fix
npm run typecheck
npm run test
```

## 5.1 Vue components

Components live primarily under:

```text
src/frontend/src/components/
```

Use PascalCase filenames for Vue components:

```text
AppDialog.vue
GameCard.vue
SettingsSection.vue
```

Prefer components with a clear responsibility.

Do not create giant components when an existing component boundary can be extended.

Before creating a component, search for an existing reusable component.

Reuse established application UI patterns rather than introducing a new visual system.

## 5.2 Composition API

Follow the existing Vue 3 patterns in the surrounding code.

Keep:

* UI rendering;
* state;
* API access;
* reusable business logic

appropriately separated.

Do not put large API implementations directly into templates/components when an existing service abstraction is appropriate.

## 5.3 Stores

Use existing store conventions for shared state.

Do not introduce another state-management mechanism.

Keep state ownership clear.

Local component state should remain local when it is not shared.

## 5.4 API clients/services

API calls belong in the established frontend service/API layer where applicable.

Do not scatter raw `fetch` calls throughout components if the surrounding feature uses a service.

Preserve:

* request/response types;
* error handling;
* authentication behavior;
* API URL conventions.

If an API contract changes, update both sides deliberately and add tests where practical.

## 5.5 TypeScript

Do not use `any` to silence type errors unless there is a strong, documented reason.

Prefer precise interfaces/types.

Handle nullable values explicitly.

Do not suppress compiler errors merely to get CI green.

---

# 6. Plugin Host Architecture

The host repository owns the plugin platform.

This includes concepts such as:

* plugin manifests;
* lifecycle;
* installation;
* package verification;
* publisher trust;
* permissions/capabilities;
* gateway access;
* plugin storage;
* plugin UI integration;
* runtime lifecycle;
* plugin management.

## 6.1 Public boundary

Plugins must interact with the application through the supported Plugin API v1 boundary.

Do not expose application internals merely because doing so makes an example easier.

Plugin code must not require imports such as:

```python
from src.plugin_api ...
```

from the plugin repository.

Likewise, host tests should distinguish:

* host/runtime tests;
* protocol/contract tests;
* cross-repository integration tests.

## 6.2 Package integrity

The `.utp` package format is security-sensitive.

Do not casually alter:

* manifest structure;
* canonical payload digest calculation;
* signature format;
* publisher key handling;
* package path rules;
* verification order;
* installation atomicity.

When changing package verification or installation, add regression tests covering malformed, modified, unsigned, incorrectly signed, and otherwise invalid packages where applicable.

Never execute plugin code before package validation has succeeded.

## 6.3 Permissions

Treat capabilities and permissions as security boundaries.

A plugin should receive only the capabilities it declares and the user/runtime grants.

Do not silently broaden permissions.

When adding a capability:

1. define the public contract;
2. define permission semantics;
3. implement host enforcement;
4. add tests;
5. document it;
6. add/update plugin-repository examples where appropriate.

## 6.4 Cross-repository plugin work

If a change affects both repositories:

* make the host-side contract explicit;
* update the host implementation;
* update the plugin repository independently;
* keep commits logically separated;
* ensure plugins do not depend on repository-relative host source;
* test the actual `.utp` package where installation behavior is involved.

Do not solve a cross-repository contract problem by adding private compatibility imports.

---

# 7. Docker and Development Environment

The repository uses Docker Compose for development.

The primary development stack is defined by:

```text
compose.yaml
```

There is also:

```text
example-docker-compose.yaml
```

The normal development stack includes separate database, backend, and frontend services.

Do not casually change service names, container networking, mounted paths, health checks, or environment-variable contracts.

The backend development container mounts backend source into the container, and the frontend development container mounts frontend source.

When modifying Docker:

* preserve development workflows;
* preserve production-image workflows;
* do not remove existing images/workflows because they appear redundant;
* verify container-to-container networking;
* verify startup and health behavior;
* verify environment handling;
* keep startup overhead and failure reporting in mind.

There is no current `.devcontainer` configuration on `main`. Historical/devcontainer work exists on dedicated branches, so do not assume that a devcontainer is the canonical development environment unless the target branch explicitly introduces one.

---

# 8. Documentation

Documentation is maintained alongside implementation.

The repository contains a `wiki/` documentation tree and README/development documentation.

When changing user-visible or developer-visible behavior:

* update the relevant wiki page;
* update navigation when a new page is added;
* update setup/installation instructions;
* document new environment/configuration behavior;
* document public plugin API changes;
* document migrations or operational changes when relevant.

Do not document behavior that the code does not actually implement.

Documentation should describe the current implementation, not an aspirational design.

---

# 9. Branching

Use descriptive branches with one of these prefixes:

```text
feat/<short-description>
fix/<short-description>
chore/<short-description>
docs/<short-description>
refactor/<short-description>
test/<short-description>
```

Examples:

```text
feat/plugin-install-ui
feat/plugin-api-v1
fix/plugin-manager-lifecycle-integrity
fix/startup-failure-screen
docs/plugin-installation
chore/update-ci
```

Plugin-related branches should identify the affected subsystem where useful:

```text
feat/plugin-...
fix/plugin-...
```

Do not use vague branch names such as:

```text
changes
stuff
test
update
new
```

Keep one logical change per branch.

If work depends on another branch/PR, state that relationship clearly rather than silently mixing unrelated histories.

---

# 10. Commits

Use Conventional Commits.

Preferred format:

```text
type: concise description
```

Examples:

```text
feat: add plugin package upload endpoint
fix: reject invalid plugin package digests
fix: preserve plugin cleanup failure semantics
refactor: centralize provider error handling
test: cover plugin lifecycle cleanup
docs: document plugin installation
chore: update plugin CI
```

Use a scope only when it materially improves clarity:

```text
feat(plugin): add package installation flow
fix(frontend): handle plugin installation errors
```

Commits should be:

* medium-sized;
* logically coherent;
* independently understandable;
* easy to review.

Avoid both extremes:

* one giant commit containing an entire feature, refactor, documentation overhaul, and formatting pass;
* dozens of tiny commits containing individual typo fixes or one-line edits.

Do not modify unrelated files just because they are nearby.

Do not use commit messages such as:

```text
fix stuff
changes
update
work
AI changes
```

Do not include AI/tool meta-commentary in commit messages.

---

# 11. Pull Requests

PRs should use a formal-casual engineering tone.

A good PR should explain:

## Motivation

What problem does this solve?

Reference the relevant issue where appropriate.

## Implementation

Explain:

* the architectural approach;
* important implementation decisions;
* affected subsystems;
* compatibility considerations.

## Testing

List:

* tests added;
* tests run;
* lint/type checks;
* Docker/manual verification when relevant.

Include exact useful commands where practical.

## Screenshots/GIFs

Include screenshots or GIFs for meaningful UI changes.

Do not add screenshots merely for backend changes.

## Possible extensions

Mention reasonable follow-up work that was intentionally left out.

Do not turn this into a speculative roadmap.

## Breaking changes

Explicitly state:

```text
Breaking changes: None
```

when there are none.

If there are breaking changes, describe exactly what breaks and how callers/users should migrate.

## PR hygiene

PRs should:

* remain focused;
* avoid unrelated formatting;
* avoid unrelated refactors;
* explain cross-PR dependencies;
* include documentation changes when needed;
* contain no AI meta-commentary.

Do not describe work as "generated by AI", "AI-reviewed", or similar in the PR body.

---

# 12. CI

Never remove or weaken CI checks to make a PR pass.

Before declaring work complete, run the relevant checks.

Backend:

```bash
cd src/backend
mypy --config-file pyproject.toml src
pylint --rcfile=pyproject.toml src
```

Backend tests require the development database:

```bash
docker compose exec -e PYTHONPATH=/app backend python -m pytest tests -q
```

Frontend:

```bash
cd src/frontend
npm run lint
npm run format
npm run typecheck
npm run test
```

If `npm run format` reports changes, use the repository's documented `npm run format:fix`, then review the resulting diff.

CI failures caused by legitimate code changes should be fixed at the source.

Do not modify tests to accept incorrect behavior.

---

# 13. Agent Workflow

For a normal implementation task:

1. Inspect the relevant existing implementation.
2. Inspect nearby tests.
3. Search for all callers of the code being changed.
4. Identify the existing architectural boundary.
5. Make the smallest coherent implementation.
6. Add regression coverage.
7. Update documentation.
8. Run focused tests.
9. Run broader checks.
10. Review the final diff for unrelated changes.
11. Report exactly what changed and what was verified.

For complex changes, perform architecture discovery before writing code.

For bug fixes, reproduce the bug before changing the implementation whenever practical.

For migrations, inspect the generated migration manually.

For Docker changes, test the affected container workflow rather than relying solely on static inspection.

For plugin changes, verify both the host-side contract and the plugin-side consumer when the change crosses the public API boundary.

---

# 14. Architecture Drift Rules

Agents must not:

* duplicate existing services;
* bypass established API boundaries;
* introduce direct plugin-to-database access;
* expose host internals to plugins;
* move plugin implementations into the host repository;
* move host runtime infrastructure into the plugin repository;
* create parallel configuration systems;
* create parallel API-client systems;
* add unnecessary global helpers;
* remove security checks for convenience;
* weaken package verification;
* execute unverified plugin code;
* rewrite large files unnecessarily;
* remove tests or CI checks;
* introduce unrelated framework/dependency changes.

When uncertain, prefer the existing architectural pattern and document the exception.

The goal is to extend the application without making its boundaries less clear.
