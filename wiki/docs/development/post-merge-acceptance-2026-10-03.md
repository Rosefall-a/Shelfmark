# Cross-repository acceptance — 2026-10-03

This pass began on 2026-10-02 and continued into 2026-10-03 in Australia/Perth.
It tested current remote checkouts, then focused fixes, without replacing the
plugin framework or rewriting merged implementation PRs.

**Result: the exercised builds, packages, public contracts and real host/plugin
lifecycles pass. Acceptance is qualified by the explicitly unverified items
below.** This is not a claim that real Playnite UI operation, live anime import
or working Bubblewrap isolation was verified.

## Exact baseline and tested revisions

| Repository / target | Clean initial remote revision | Final code/package revision |
| --- | --- | --- |
| `Rosefall-a/unnamed_tracking_app` / `plugin-manager` | `45424fe6846587e2c25cbdafa882c621d2dbcd04` | `31e97fcd0b9217a9398d052bf99613e69cba9174` |
| `Rosefall-a/unnamed_tracking_app_plugins` / `main` | `bb09d1b6d83a6e9ce5b612307c87a420446f1de8` | `54649b50ecd422123cf244fe846bb59bc83a7ec0` |
| `Rosefall-a/UnnamedTrackingPlaynite` / `main` | `154f6d45e504c9b04f20e08b865278a2b6ebdc8c` | Same; no extension defect required a code change |

The dated report is a subsequent documentation-only change. Its PR targets
`plugin-manager`; the tested application/runtime source is the revision above.
The original developer checkout was not used as a build source.

Relevant existing merges include host [#382](https://github.com/Rosefall-a/unnamed_tracking_app/pull/382),
plugin [#25](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/25),
[#26](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/26),
[#27](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/27),
[#29](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/29), and
Playnite [#17](https://github.com/Rosefall-a/UnnamedTrackingPlaynite/pull/17).
Inspection found that host #383 and plugin #24/#30 were still open at baseline,
despite the initial assumption that the requested capabilities were all merged.
Those existing capability PRs were reviewed, updated without force-pushing, and
merged after their checks passed. Already merged PRs were not recreated.

The ecosystem still uses Plugin API v1, Package v1, the existing JSON-lines SDK,
host-owned grants/gateway/manager, separate runtime-owned storage, and the
Playnite user API-key integration. No duplicate framework was introduced.

The full final browser/worker acceptance and supplemental published-package
acceptance used host `31e97fc` and plugins `3ae1805`. The final plugin commit
`54649b5` differs only in the development cryptography dependency and the
integration workflow's companion-branch selection/regressions; executable
plugin source and all published packages are unchanged. Complete package,
Python, documentation and history checks were repeated. Tested PR heads
`0d8f0b4` and `ddec72e` have exactly the same trees as their respective merges
`4dd6836` and `54649b5`.

Earlier evidence is also explicit: the first repaired lifecycle used host
`45424fe` and plugin `a58e192` (tree identical to merge `35659f2`); capability
testing used host `8cd361d` and plugin `4e3fa47`. The final evidence supersedes
those runs for acceptance. Full SHA values appear in the linked JSON records.

## Environment and clean build proof

Windows ran .NET SDK 8.0.425 and the actual .NET Framework 4.6.2 regression
executable. Ubuntu/WSL and Docker ran Python 3.12, Node 22 and PostgreSQL 16.
Each repository was cloned from its stated remote branch. Final Python checks
used fresh virtual environments, installed from the repository requirements.
Frontend dependencies came from `npm ci`, not an existing developer install.

The final production host and non-root plugin runtime Docker images were built
from a `git archive` of host `31e97fc`. The archive excludes ignored artifacts,
local dependencies and uncommitted files. The production image then served the
real API used by the Windows Playnite transport proof.

| Check | Actual result |
| --- | --- |
| Host migrations | Clean database upgraded through the single head `f9c2a6d84103` |
| Complete backend suite, companion checkout supplied | **763 passed, no skips** |
| Runtime policy/storage suite | **83 passed** |
| Backend mypy | **195 source files**, no issues |
| Backend pylint | **9.25/10**, exceeds the existing 9.0 gate; raw diagnostic exit 30 is not reported as exit 0 |
| Frontend | **79 tests**; formatting, lint, typecheck and production build passed |
| Official plugins, fresh declared Python dependencies | **181 passed**, including five companion-target regressions |
| Plugin browser suite | **36 passed**, including finite/unlimited document configuration and parser safety |
| Native/plugin session UI tests | **11 passed** |
| Plugin package generation | Both repetitions identical; published and preview structure/signature/distribution checks passed |
| Playnite clean Release build | **0 warnings, 0 errors** |
| Playnite production helper regression executable | **174 assertions passed** on Windows/net462 |
| Playnite package validation | Manifest, assembly/version, file entries and packaging regression checks passed |
| Documentation | Strict host, plugin root, plugin direct-wiki and Playnite MkDocs builds passed |

The initial backend run's two optional companion-repository tests were skipped
without `PLUGIN_REPOSITORY_PATH`. They were then run with the real checkout
(2 passed), followed by the complete **763-test** run. These are not remaining
skips. Test warnings, including deliberately malformed ZIP fixtures and existing
archive-extraction deprecation warnings, were retained rather than hidden.

## Official distribution and release state

The final catalogue exposes **10 current plugins**. `/dist` contains **38**
historical/current packages and `/releases` contains **13** per-plugin history
documents. Baseline had 36 packages: Document Viewer 1.7.0 and Jellyfin 3.0.0
were appended through the existing publisher. Previously published package
bytes and historical release records were independently checked against
`bb09d1b`; history was not regenerated or overwritten.

| Plugin identity suffix (`example.` prefix) | Baseline | Final tested version |
| --- | --- | --- |
| discord-delivery-provider | 1.1.0 | 1.1.0 |
| help-button | 2.1.0 | 2.1.0 |
| jellyfin-media-sync | 2.1.1 | **3.0.0** |
| metadata-curator | 1.1.0 | 1.1.0 |
| playtime-report | 1.1.0 | 1.1.0 |
| recently-played-notifier | 1.1.0 | 1.1.0 |
| scoped-document-viewer | 1.6.0 | **1.7.0** |
| self-service-session-manager | 2.2.0 | 2.2.0 |
| ui-api | 1.1.0 | 1.1.0 |
| ui-playground | 1.1.0 | 1.1.0 |

Useful complete-file SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| Jellyfin 3.0.0 `.utp` | `472e0ecb35f6ad2d16c12b2d42d6ec0e0661eecfd191c0017bd7698e678c4eb7` |
| Document Viewer 1.7.0 `.utp` | `58ac3d13dbf44152874d55ac3b95ea92faf436ae94832ab0a17a527ada3e2c0a` |
| Session Manager 2.2.0 `.utp` | `a928ca4c9dd502c9a6e4f6cc633b0823b1be84dbafb3f56d690004e7798886ce` |
| Local Windows `UnnamedTrackingPlaynite-0.1.2.pext` | `10bec763bfc99c95466d5a7fed963124ad1df3458d99b4776b7ec3388c532131` |

Complete-file hashes are distinct from the canonical signed payload digest.
The evidence includes both. Determinism was checked for plugin packages and
metadata; no claim is made that separate Windows ZIP/PEXT builds have identical
container timestamps.

All 38 published plugin packages and generated previews passed existing
verification and validation tools. Current catalogue packages use
`non-secret-testkey`. The host correctly identifies this as **Unnamed Tracking
Official (test key)**, with `retiring` status and `example.` scope; the plugin
registry labels the same public key active/Official. Matching key bytes and
scope are verified, but the existing publisher-policy difference is recorded.
This pass did not rotate keys or relabel a test signer as a production signer.

Repository `list.json`/`dist`/`releases` are the current plugin distribution;
GitHub release `v0.0.0-R` still contains older 1.0-era artifacts. The host's
GitHub prerelease remains `v0.0.1-alpha.1`. Playnite source explicitly prepares
**unreleased 0.1.2**. Its separately published `v0.2.0-beta.3` has no assets and
its tag build fails the correct version guard. This is an invalid release-tag
assumption, not a failed main build or a reason to weaken that guard. The
historical tag/release was preserved; no new Playnite release was published.
Do not direct users to that empty release as proof of a working 0.1.2 package.

## Real installation, lifecycle and permissions

The actual application, authenticated HTTP manager, gateway, runtime and worker
processes were used. The production frontend was built and exercised in
Chromium. This goes beyond package validation or inspection of buttons.

Published packages were discovered through the official catalogue and installed
through the normal preview/consent/install APIs: UI/API reference 1.1.0, Help
Button 2.1.0, Playtime Report 1.1.0, Document Viewer 1.7.0, Jellyfin 3.0.0 and
Session Manager 2.2.0. All six reported enabled, running, healthy workers.
Playtime Report read a real scoped game library and wrote its persisted report.
Its persisted report was compared through retaining lifecycle operations.

| Lifecycle / permission behavior | Evidence and result |
| --- | --- |
| Install, consent, configure, enable, start, use | Normal signed acquisition, host risk review and healthy workers; real scoped actions and native frontend passed |
| Stop/start, runtime-process restart | Worker readiness and durable data/configuration/secret comparison passed |
| Disable/enable | Disabled contributions stop; reenable restores operation without destroying retained state |
| Update without new permission | Activated new working version with retained data/grants |
| Rollback | Restored preceding package/version and retained owned state |
| Candidate requests new scope | Candidate staged; existing version remained running with unchanged grants/history |
| Deny candidate scope | Authenticated denial retained healthy predecessor; unapproved capability remained unavailable |
| Approve candidate scope | Explicit approval activated the staged candidate |
| Failed candidate startup | Previous package, data and grants restored; failed candidate did not become the active release |
| Revoke and explicitly regrant | Actual actions/contributions deny revoked access and resume only after regrant |
| Retaining reinstall | Installation identity, configuration, state and secrets preserved where defined |
| Confirmed purge and uninstall | All six representative owned storage/configuration paths absent after removal |

The full update/failure/permission sequence used disposable signed candidate
packages generated by the existing builder and a disposable publisher. This
is genuine host/runtime execution, but does not imply that synthetic candidate
versions were published as official releases.

Separate real-worker reference transactions exercised Metadata Curator,
Playtime Report, Recently Played Notifier and UI/API through update, rejected
permission transaction, rollback, failed activation recovery, state retention
and nonempty uninstall. These tests used the existing runtime transaction
entry points; the final browser suite verifies the authenticated public layer.

## Catalogues and trust boundaries

The final browser/HTTP acceptance verified official discovery, multiple enabled
sources, duplicate identities and explicit source choice, tags, README display,
release notes, full-file hashes, signed payload verification, publisher identity,
release-specific automatic-update policy, retained versions and offline inventory.
A delayed catalogue and unavailable runtime did not erase installed inventory.

Host risk review is derived from host capability policy, not a plugin's claimed
risk label. Invalid manifests, changed payloads, wrong digests and unsigned
packages were rejected before execution. Unsigned/unverified metadata was not
accepted as a trusted publisher. Direct runtime management requires its own
authentication; a catalogue row is not execution authority.

Revocation checks cover actions, contribution discovery, gateway operations,
plugin backend routes, scoped/delegated identities and management tokens.
The real acceptance also confined token methods/sources and blocked wrong-user
identity, administrator and Watch Now access. Passing cryptographic verification
does not mean a plugin is safe to trust with all granted capabilities.

## Jellyfin — live server and fixture results

The supplied live server was accessed with test credentials entered through
hidden input. Credentials were stored through the existing plugin secret API
in a disposable runtime namespace. No live credential, remote user/item ID,
configuration dump or live request URL was exported to report assets.

Master configuration, connection/discovery and administrator-approved user
linking worked. Explicit Movies/TV/Anime library mapping was applied once at
installation level; user configuration linked an approved identity without
duplicating master credentials. Ordinary action responses were checked for
credential leakage. The browser fixture verifies a blank password control and
that reading configuration does not return the credential.

Independent header-authenticated, paginated library queries supplied the count
oracle. The real plugin then imported **43 movies and 23 TV shows**. Movie
completion was **35 WATCHLIST, 3 IN_PROGRESS, 5 WATCHED**; TV completion was
**22 WATCHLIST, 1 IN_PROGRESS**. A complete bounded sync processed 1,594 entries,
skipped 684 and reported zero conflicts. Repeated sync returned the same host
identities and counts, with no duplicate media.

Live Watch Now resolved populated movie/TV media contexts to the configured
server and durable Jellyfin item ID. The destination contained no API key/token
or remote user identity. Live stop/start, disable/enable, retaining reinstall
and a full runtime-process restart preserved credentials, master/user setup,
library mapping and durable host identities. Uninstall returned the documented
HTTP 204 and removed the installation/owned secret state.

The mapped live Anime library contains **no Movie/Series records**: live anime
import is **NOT VERIFIED**. The controlled real-worker Jellyfin fixture covers
film/TV/anime, explicit mappings, completion/watch reversals, repeated sync,
second-user delegation, context-specific Watch Now and update/rollback/state
retention. Unit/integration tests cover retry, pagination, renamed identity,
optimistic completion conflicts and bounded season/episode data. This pass did
not mutate the real server's watched state, rename its media or induce remote
failures; those live mutation/retry scenarios are **NOT VERIFIED**.

## Scoped Document Viewer

The published **1.7.0** worker used the actual public settings and document API.
With `max_preview_mb=1`, a 5,242,881-byte text file was rejected as oversized.
With `max_preview_mb=0`, all bytes were read in **214 authenticated chunks** and
the final SHA-256 matched the original content. The saved setting survived
stop/start, disable/enable and retaining reinstall. The host's 24-KiB chunk
ceiling remains enforced; unlimited refers to the preview size contract.

Host tests cover old callers' legacy default, finite limits, zero/unlimited,
identity/digest consistency and safe malformed content. New regressions cover
1/2/3-byte finite limits: the host no longer issues a negative-length read that
would read an entire file before returning 413. Browser tests retain PDF/Office
safety controls, sanitization, ZIP expansion/member limits, XML limits, DTD and
macro restrictions, and malformed/unsupported-document handling. Removing the
Office compressed-input size ceiling did not remove these parser/browser controls.

## Playnite

The clean checkout built on Windows, produced a validated **0.1.2 PEXT**, and
passed **174 assertions** against production synchronization/save helpers.
NuGet's transitive vulnerability scan returned no vulnerable packages.

An additional Windows/net462 CLI linked the unchanged production C# transport
and save sources and called the clean production host Docker image through its
normal authenticated API. **Eight assertions** verified connection, non-mutating
preview, game creation with artwork, persistent Playnite GUID, rename/repeated
update without duplicates, native BEATEN status, actual save upload/download
restoring bytes, and cancellation. A disposable user API key was used; this
did not use a plugin-management token or copied host implementation.

**Real Playnite UI/runtime acceptance is NOT VERIFIED.** Playnite is installed,
but the desktop launch approval expired. No claim is made about PEXT installation
inside Playnite, UI-event/library capture, real user dialogs or the embedded
Unnamed Tracking WebView. Those require the actual application. Existing
screenshots remain files, not evidence that its current UI was exercised here.
The extension's [runtime checklist](../integrations/playnite.md) and its own
wiki describe the remaining interactive checks.

## Security and isolation

Static boundary review and executed tests found no need for a new security
architecture. Official plugins use the supported scoped SDK rather than host
database sessions, host models or host filesystem paths. Generic media/HTTP/task
APIs are host-owned; Jellyfin implementation remains in the plugin repository.
Runtime storage refuses traversal, symlinks and cross-namespace backup restore.
Protected secret keys are not exposed through ordinary plugin storage reads.
Secret files use the runtime's private directory/file permissions; this report
does not claim an encrypted vault.

The audit found and fixed URL password transport and known dependency issues.
Final `npm audit` and `pip-audit` reports contain zero known vulnerabilities for
the audited host/plugin dependency graphs; the NuGet audit also passed. This is
an advisory-database result, not proof that no vulnerability exists.

The real built non-root runtime image's namespace probe failed with
`No permissions to create a new namespace`. Its health report accurately says
`bubblewrap_available=false`, `sandbox_available=false`, `mechanism=process`,
`reduced_isolation_allowed=false`. Strict startup policy blocks worker execution
when sandboxing cannot be established. Functional worker acceptance explicitly
used `NONBUBBLE_ENV=true` and reported reduced process isolation.

**Successful Bubblewrap worker isolation is NOT VERIFIED in this environment.**
Process mode is not an OS filesystem/network sandbox; a worker sharing that
execution identity can access ambient files. Public API/grant checks do not
turn process mode into safe execution for an untrusted plugin. The production
Compose database/runtime network separation was reviewed, but a complete
deployment of that topology was not demonstrated by the local API harness.

## Failures, root causes and fixes

| Failure / root cause | Focused fix or classification | Regression / verification |
| --- | --- | --- |
| Clean plugin baseline: 60 failed / 118 passed; six published sources moved to an obsolete directory; wiki move left stale requirements, links, tutorial paths and docs checker assumptions | Plugin [#32](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/32), merge `35659f2`; restore exact source moves and resolve inherited MkDocs docs path | 179 passed at repaired state; inherited broken-link regression; both strict wiki entry points; history/package validation; all CI green |
| Host finite document limits 1–3 cause `read(negative)` to consume the whole file | Host [#385](https://github.com/Rosefall-a/unnamed_tracking_app/pull/385), merge `e54aaa9`; clamp remaining read length | Three regressions failed before/fixed after; 61 document tests passed; final broader suite passed |
| Required unlimited viewer capability was still in an open PR; stale release filename and missing declared `load-settings` action | Existing plugin [#24](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/24), merge `6cff3e1`; reconcile current main and append 1.7.0 | Two browser regressions; finite/unlimited host-worker proof; safety tests retained; all CI green |
| Requested final Jellyfin behavior was still in open host/plugin PRs | Existing host [#383](https://github.com/Rosefall-a/unnamed_tracking_app/pull/383), merge `2dfaee1`, and plugin [#30](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/30), merge `13c8ec9` | Public generic APIs, 176 plugin tests, full authenticated real-worker/browser lifecycle and live sync; all CI green |
| Supplemental CI screenshot selector expected the former Jellyfin credential label | Updated relevant existing plugin #30 capture helper; accept current/legacy labels while asserting password type and blank value | Actual paired browser CI passed; current screenshots captured |
| Known host frontend dependency advisories | Host [#386](https://github.com/Rosefall-a/unnamed_tracking_app/pull/386), merge `959e233`; compatible lockfile updates for DOMPurify/brace-expansion | Frontend tests/checks; audit zero; all CI green |
| Host backend dependency audit: 82 advisory records across seven packages, including duplicated advisory records | Host [#387](https://github.com/Rosefall-a/unnamed_tracking_app/pull/387), merge `c05c280`; patched dependencies and Pillow's explicit converted-image variable | Full backend/runtime, typing/lint and real lifecycle; final audit zero; no assertion weakening |
| Administrator password included in file-upload install/update URLs | Host [#388](https://github.com/Rosefall-a/unnamed_tracking_app/pull/388), merge `31e97fc`; multipart body field and frontend FormData | Two HTTP tests reject query-only reauth and accept body reauth; frontend install/update URL regression; 253 acquisition tests; final full suites and all CI green |
| Plugin dev constraint `<47` excludes patched cryptography; audit resolves 46.0.7 with seven advisory records | Plugin [#33](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/33), merge `4dd6836`; existing requirement becomes `>=50,<51` | Fresh declared-only environment, 176 tests, signing/history/docs, audit zero; all CI green |
| Plugin main's post-merge CI selected host main because that same-named branch exists; host acceptance harness was absent there | Plugin [#34](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/pull/34), merge `54649b5`; main uses the owned host target plugin-manager, preserving feature matching and explicit overrides | Five tests execute the actual Bash selector with offline Git; 181 total tests and unchanged real-worker CI passed before merge; main run rechecked |
| Locally stale preview generated before source restoration omitted six plugins | Generated-artifact problem: rebuild with existing machinery | Ten source/current catalogue entries and installed host contracts pass; no committed generated junk |
| Early browser run before rebuilt frontend; competing npm installs; live inventory used a different auth header; harness expected nested settings or uninstall HTTP 200; oversize test chunk | Acceptance-harness assumptions/order corrected; no production change for these failures | Sequential fresh builds, direct settings payload, required 24-KiB chunks, expected HTTP 204 and successful repeats |
| Parallel disposable hosts shared a database and changed grants for identical plugin IDs, producing live HTTP 403 | Environmental harness conflict; allocate a separate migrated database for the live run | Final isolated live run passed all eight checkpoints |
| Playnite `v0.2.0-beta.3` tag versus source 0.1.2 | Invalid release trigger; preserve version guard and history | Main build/package and real transport passed; historical failed tag is not marked green |

Every code fix above used the correct target branch, coherent commits, a PR and
passing applicable checks before merge. No tests, quality gates or failing jobs
were removed. Unrelated open PRs were left alone.

## CI and documentation evidence

Final host [backend](https://github.com/Rosefall-a/unnamed_tracking_app/actions/runs/37037122224),
[frontend](https://github.com/Rosefall-a/unnamed_tracking_app/actions/runs/37037122257),
[cross-repository lifecycle](https://github.com/Rosefall-a/unnamed_tracking_app/actions/runs/37037114990),
[production build](https://github.com/Rosefall-a/unnamed_tracking_app/actions/runs/37037122197),
and [strict docs](https://github.com/Rosefall-a/unnamed_tracking_app/actions/runs/37037122302)
are successful. Plugin #33's [tests/build](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/37039334170)
and [real host lifecycle](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/37039334268)
are successful. Plugin #34's [tests/build](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/37041796629)
and [real lifecycle](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/37041796884)
are also successful. The failed post-#33 main run was diagnosed and repaired by
#34 rather than ignored or rerun against a different host branch.
Final plugin main's [tests/build](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/37042500264),
[package publication check](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/37042500226)
and [full lifecycle](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/37042500221)
all passed at `54649b5`.
Playnite [main build/wiki](https://github.com/Rosefall-a/UnnamedTrackingPlaynite/actions/runs/37019954440)
and [PEXT build](https://github.com/Rosefall-a/UnnamedTrackingPlaynite/actions/runs/37019953667)
are successful; the distinct [invalid-tag failure](https://github.com/Rosefall-a/UnnamedTrackingPlaynite/actions/runs/37020257548)
remains visible. See the complete [check snapshot](../assets/post-merge-acceptance-2026-10-03/ci.json).

Documentation commands, API ownership, lifecycle semantics and release guidance
were compared with implementation/tests. Strict builds and plugin internal-link/
asset checks pass. Report screenshots were captured from the current built host
and installed native UI, and visually inspected. Other historical screenshots,
especially Playnite, are not upgraded to current-runtime evidence merely because
their referenced files exist.

## Evidence files and screenshots

The following records are committed with the report. They contain aggregate
results, exact revisions and public package metadata, without live credentials.

- [Final browser/worker lifecycle](../assets/post-merge-acceptance-2026-10-03/lifecycle.json)
- [Six published representative installations and document/session proof](../assets/post-merge-acceptance-2026-10-03/representatives.json)
- [Live Jellyfin aggregate results](../assets/post-merge-acceptance-2026-10-03/live-jellyfin.json)
- [Final distribution, package hashes and reproducibility](../assets/post-merge-acceptance-2026-10-03/distribution.json)
- [Real Windows production Playnite transport](../assets/post-merge-acceptance-2026-10-03/playnite-http.json)
- [Actual built runtime image diagnostics](../assets/post-merge-acceptance-2026-10-03/runtime-isolation.json)
- [Build/test/dependency audit excerpts](../assets/post-merge-acceptance-2026-10-03/checks.txt)
- [Documentation link and image-reference inventory](../assets/post-merge-acceptance-2026-10-03/documentation-assets.json)
- [Screenshot provenance and file hashes](../assets/post-merge-acceptance-2026-10-03/provenance.json)
- [Repository/secret hygiene result](../assets/post-merge-acceptance-2026-10-03/hygiene.json)

Host-owned permission review in the actual production frontend:

![Host permission review](../assets/post-merge-acceptance-2026-10-03/permission-review.png)

Installed native Jellyfin master/library controls, with a blank credential field.
All screenshots use a disposable local server and synthetic identities:

![Jellyfin master settings](../assets/post-merge-acceptance-2026-10-03/jellyfin-admin-settings.png)

Actual host media page with completed fixture movie and durable Watch Now:

![Media completion and Watch Now](../assets/post-merge-acceptance-2026-10-03/jellyfin-watch-now.png)

## Reproduction and remaining limitations

Clone the exact revisions above. Follow each repository's requirements and
existing build/packaging commands. Use a separate migrated disposable database
for each independent host acceptance run. Build the host frontend before its
browser lifecycle. The core checks are:

```sh
# Host, with normal documented database/test environment
python -m pip install -r src/backend/requirements.txt jsonschema
(cd src/backend && alembic upgrade head)
(cd src/frontend && npm ci && npm run format && npm run lint && npm run typecheck && npm test && npm run build)
PLUGIN_REPOSITORY_PATH=/absolute/plugins PYTHONPATH=src/backend python -m pytest src/backend/tests
(cd src/plugin-runtime && PYTHONPATH=. python -m pytest -q tests)
python -m mkdocs build --strict -f wiki/mkdocs.yml

# Official plugins
python -m pip install -r requirements-dev.txt
python -m pytest -q
python tools/build_packages.py
python tools/distribution.py --check-source
python tools/distribution.py --baseline-ref bb09d1b6d83a6e9ce5b612307c87a420446f1de8
python tools/verify_packages.py dist/*.utp
python tools/validate_packages.py dist/*.utp
python tools/check_docs.py
python -m mkdocs build --strict
npm ci && npm run check && npm test
python tools/check_host_lifecycle.py --host-root /absolute/host --plugins-root /absolute/plugins --work-root /absolute/disposable-evidence --browser
```

The last command needs the host's requirements, its configured disposable
PostgreSQL database and installed Playwright browser. In this environment the
functional worker runs explicitly opted into `NONBUBBLE_ENV=true`; require
successful strict isolation on a suitable production host instead.

On Windows, Playnite used `dotnet restore UnnamedTrackingPlaynite.sln`, Release
build, the net462 `Companion.Tests.exe`, root `pack.ps1 -NoBuild` and
`tests/test-packaging.ps1`. No Toolbox-generated developer files were required.

Remaining limitations are live anime (empty library), destructive live watched/
rename/retry scenarios (not induced), actual Playnite UI/embedded WebView,
successful Bubblewrap worker isolation, and the invalid empty Playnite release
tag. Publisher test-key policy differs between repositories as described above.
No claim of complete production deployment, strong process-mode isolation or
current screenshots for unexercised UI is made.

Generated `.validation`, frontend builds, MkDocs output, .NET output and local
PEXT files were inspected as intentional ignored build products. The only new
tracked host artifacts are this report, its navigation entry and evidence
assets. Historical plugin distributions remain intact; no live Jellyfin secrets
were found in scanned repository/evidence/package contents. Task-owned live
temporary secret storage is removed after shutdown.
