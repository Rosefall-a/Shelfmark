# Plugin API v1 stages 1–4 installation gate

Review base: `Rosefall-a/unnamed_tracking_app`, `plugin-manager`, `08f93511`.
Push integration base: `51f3ef50`, preserving the subsequent live-authorization
fixes and HTTP gateway audit. Restored the shared route's `CapabilityRef` import
after rebasing and reran the affected backend/runtime checks.
Scope: host installation infrastructure and its isolated runtime boundary.
Help Button, Jellyfin, Document Viewer, and Session Manager implementations are outside this change.

## Canonical lifecycle

| Stage | Owner |
| --- | --- |
| Upload/download with bounded size and public-URL checks | `api/routes/plugins.py` acquisition adapters |
| Content identification, archive safety, strict manifest validation, canonical payload integrity | `plugin_api/updates.py`, called by `PluginInstaller` |
| Signature verification and distinct trusted/unknown/unsigned/invalid classification | `plugin_api/installer.py::inspect_package` |
| Dependencies, permission calculation and update delta | `PluginInstaller`, sharing `plan_dependencies` and the capability registry |
| Unverified consent, exact approved permission keys, dangerous-permission confirmation and password re-entry | `PluginInstaller.confirm` |
| Prepared atomic package replacement, committed grants, runtime finalization | `PluginInstaller._commit` and `PluginRegistry` |
| Activation and health | `PluginInstaller` through the authenticated runtime client |

Uploaded `.utp`, ZIP, packages identified by contents, URL and catalogue requests
all enter the same service. Uploaded, URL and catalogue updates enter that service
with an existing installation context. Routes retain acquisition, response
serialization and HTTP error translation; they do not independently grant
permissions or choose trust policy. Catalogue provenance never grants trust.

## Findings addressed

- Install and update previously had separate consent, grant persistence, commit
  and activation implementations in the routes. They now share those decisions.
- Malformed unknown-key signatures and invalid signatures from known keys outside
  their permitted scope could become overridable warnings. Both now fail hard.
- Malformed UTF-8 ZIP names now produce controlled archive rejections at both
  boundaries. Windows alternate-data-stream paths are rejected alongside traversal,
  duplicate entries and symlinks; existing package and decompression limits remain.
- Becoming verified could retain grants from a previously unverified package.
  Retention now requires two verified versions with matching publisher identity.
- Dependency planning missed transitive failures and reverse version constraints
  when updating a dependency. Both now block installation before activation.
- Runtime start/stop discarded publisher trust and source metadata. Lifecycle
  transitions now preserve them.
- Runtime package replacement discarded its backup before state persistence.
  State-write failures now restore the predecessor.
- Runtime replacement could precede a failed PostgreSQL permission commit.
  Prepared packages now stay disabled until grants commit and runtime completion.
  Definitive database rejections abort and restore prior package/grants; ambiguous
  commit acknowledgements and interrupted completion leave the candidate disabled
  after restart or manual enable. Stale concurrent update plans are rejected by
  an installed-version precondition. Prepared packages cannot satisfy dependencies.

The v1 digest/signature format remains unchanged. The runtime's independent
archive/digest validation is defense at the execution boundary; administrator
trust and permission decisions belong to the host installer.

## Verification

`tests/test_plugin_install_sources.py` exercises the public FastAPI endpoints,
streamed HTTP acquisition, real PostgreSQL permission persistence and the actual
runtime package store. Only remote transport and plugin process execution are
substituted. It covers every acquisition/update source, all trust states, archive
and manifest failures, integrity/signature failures, size limits, explicit consent,
password re-entry, dependency isolation, grant retention/removal, atomic failures,
permission-commit failures, interrupted finalization, activation and health.

Runtime regressions cover authenticated HTTP preparation/completion, restart
guards, operation/installation identity, aborted replacement, state-write recovery
and metadata retention. Planner regressions cover scoped signatures, malformed
unknown-key signatures, transitive dependencies and optional catalogue hints.

Completed on 2026-10-01 in disposable Linux containers using Python 3.12,
PostgreSQL 16 and Node 22, following the existing CI workflows:

| Check | Result |
| --- | --- |
| Complete backend pytest suite | 586 passed, no skips after integration |
| Complete plugin-runtime suite | 53 passed after integration |
| Alembic upgrade and migration graph | Passed; six revisions, one head, no cycles or missing parents |
| Mypy | Passed; 186 source files |
| Pylint | Passed; 9.16/10 against the existing 9.0 threshold |
| Frontend formatting, ESLint and Vue type check | Passed |
| Complete frontend Vitest suite | 50 passed |
| Backend Ruff formatting workflow | Passed on an isolated source snapshot; changed backend files pass the format check |
| Strict MkDocs build | Passed |
| Production, backend, frontend and runtime Docker builds | Passed; local images only |

The optional external-package contract tests ran against the existing signed
`example.advanced-1.0.0.utp` and publisher registry from the separate plugin
repository. No external plugin implementation was added or modified. Formatting
workflows ran in clean Linux source snapshots to avoid unrelated Windows line
ending changes. No CI jobs or tests are removed or relaxed.

An interrupted finalization deliberately remains disabled for administrator
recovery. This change does not claim to wire the separate standalone lifecycle
manager's quarantine/safe-mode machinery or provide automatic rollback after a
post-commit health failure; existing activation failure reporting is preserved.
