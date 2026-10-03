# Official PWA integration

`official.pwa` is maintained user-facing functionality based on
`Rosefall-a/unnamed-tracking-mobile-app/pwa`. Its integration version is **0.0.1**;
stable 1.0.0 requires a future explicit human decision. It opens the complete web
application and inherits future responsive improvements. Native Android, Android
WebView and Windows/WinUI client implementations are independent and unchanged.

## Host and plugin boundary

The manifest's typed `pwa` declaration requires an explicit `frontend.pwa` v1
permission. It publishes public install metadata and two bounded verified PNGs.
The host constructs `/manifest.webmanifest`, serves current icons under `/pwa/`,
and owns `/service-worker.js` at root scope. An arbitrary plugin worker is never
executed. The plugin receives no native frontend, account API, arbitrary root
route or private data permission. Official publisher status adds no privileges.
Other publishers may use the same narrow contribution with explicit permission.

Enablement requires a healthy running installation and an installation-wide
permission. Per-user/device grants do not authorize an origin-wide worker.
Multiple live providers fail closed with 409 rather than silently replacing one
another. Disabled, stopped, quarantined, incompatible, revoked or missing
installations expose no install manifest or icons. Runtime unavailability returns
503 and preserves existing neutral offline content during a transient outage.

The root URL matters: a worker under `/api/plugins/...` cannot inherently control
the application root. The host serves a JavaScript MIME type at a stable root URL
with `Service-Worker-Allowed: /`, and the frontend registers it at `/` with
`updateViaCache: none`. Production and Vite proxy those URLs before SPA fallback.

## Cache and lifecycle

Only the reviewed waiting-for-internet HTML page enters CacheStorage. There is
no runtime response caching or private application shell. `/api/`, authentication,
non-navigation, non-GET and cross-origin traffic bypass the worker handler.
Passwords are never persisted by the PWA; normal host session expiry returns to
login/SSO. Chrome/Edge use the browser install prompt; iOS Safari offers Share →
Add to Home Screen guidance. Installation requires HTTPS or localhost support.

The cache generation binds plugin ID, installation UUID, version and payload
digest. Updates use `skipWaiting`/`clients.claim`, migrate only owned caches and
withdraw old icon URLs. Clean pages reload automatically; after input edits a
reload button lets the user save first. Offline HTML has no time expiry. Missing
storage or a cache entry produces neutral plain-text reconnect guidance.

The stable worker URL remains available after disable/uninstall and serves a
retirement configuration. The frontend also unregisters owned workers and clears
owned caches on affirmative withdrawal. Cleanup never deletes another origin
application's cache; the exact legacy `tracking-shell-v1` cache is migrated.
Reinstall gets a fresh identity. Offline devices observe removal at their next
server contact. Browser shortcuts cannot be remotely removed and then open the
ordinary website, with plugin settings guidance. Failed initial startup follows
the existing manager contract: an unhealthy diagnostic installation is retained
until removed, but it exposes no PWA functionality. Failed updates restore the
previous healthy package, permissions and generation.

## Signing and publishing

Publisher channels are independently reviewed: `official`, `demo`, `community`.
Only a verified v2 signature under an official registry identity receives the
Official badge. Existing example keys are demo identities despite their old
display names. Unknown/unsigned packages are explicitly unverified; invalid
signatures cannot be overridden. Legacy v1 archives require reviewed manifest
pins and never establish official status. See [update verification](plugin-updates.md).

Provision these protected builder/Actions secrets in the plugin repository:

| Environment key | Role |
| --- | --- |
| `PLUGIN_EXAMPLES_SIGNING_KEY_ID` | Reviewed demo identity for examples |
| `PLUGIN_EXAMPLES_SIGNING_KEY_B64` | Its base64 raw 32-byte private seed |
| `PLUGIN_OFFICIAL_SIGNING_KEY_ID` | Separate new official identity |
| `PLUGIN_OFFICIAL_SIGNING_KEY_B64` | Its protected private seed |
| `PLUGIN_SIGNING_KEY_ID` | Optional generic/legacy fallback identity |
| `PLUGIN_SIGNING_KEY_B64` | Its protected private seed |
| `PLUGIN_SIGNING_FALLBACK` | `generic` (default), `unsigned` previews, or `error` |

Register the matching public key, SHA-256, publisher, channel and scope in both
reviewed registries. The host can use `PLUGIN_TRUSTED_PUBLISHER_REGISTRY` to select
its deployed policy; it needs no private signing keys. No production official
private key is generated or committed. Until a protected official key is
provisioned, only the explicitly unsigned preview is available; signed official
publication fails atomically. Existing immutable demo artifacts remain intact.

From the plugin checkout synchronize source assets with `tools/sync_pwa.py
--mobile-root PATH --host-root PATH`; use `--check` to verify exact source hashes,
host worker/offline templates and version consistency. Packaging consumes
`official/` as well as `examples/` and optional `plugins/`. `.validation/list.json`
contains all preview packages; the public catalogue advertises only published
history until the official identity is provisioned. Never publish a preview URL
as a production signed release.

## Verification

Use a disposable migrated PostgreSQL database, installed host/backend dependencies,
built frontend and the companion repository's Playwright installation:

```sh
python tools/check_pwa_lifecycle.py --plugins-root /path/to/plugins --work-root /tmp/new-pwa-acceptance
```

This uses disposable signing keys, real host HTTP/DB grants, actual subprocess
workers, package verification, the real update policy and Chromium. It covers
discovery, inspect/install/permissions, official UI, reload, manifest/icon parsing,
offline navigation, private API exclusion, automatic update/cache migration,
rollback, old versions, disable/uninstall/reinstall, actual session expiry,
unsigned consent, invalid signatures, malformed packages and unhealthy startup.
`pwa-conformance.json`, logs and screenshots record evidence. No plugin API is
mocked; only HTTPS catalogue acquisition maps to the disposable local release
fixture. The mobile source has separate worker cache-failure/migration tests.

Headless browser verification cannot operate native OS installation dialogs or
prove physical Android Chrome, iOS Safari and Windows install surfaces. Those
device checks remain manual before a stable release. Cross-repository CI runs
this lifecycle; feature branches must have matching host/plugin changes available
to the workflow selectors.
