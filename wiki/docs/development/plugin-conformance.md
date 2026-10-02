# Installed-plugin conformance

Conformance exercises installed packages through the existing Plugin Manager,
runtime HTTP, workers and granted gateway. Unit tests remain useful for malformed
input and isolation policy, but do not replace real installed-worker acceptance.

## Reusable host-side surface

`tools/plugin_conformance.py` provides `InstalledPluginConformance`. Supply an
authenticated `httpx.Client` and the installed plugin ID. It imports no host models
or plugin implementation and supports:

- public manager requests, authoritative inventory and declared actions;
- process health, recorded `lifecycle.ready` and runtime API-version readiness;
- stop/start, disable/enable and preserving reinstall with stable installation identity;
- a caller-provided persistence probe for the plugin's actual configuration, data and secrets.

Run these checks only on a disposable installation. A persistence probe must return
stable state rather than request IDs, timestamps or secrets in printed output:

```python
import httpx
from plugin_conformance import InstalledPluginConformance

with httpx.Client(base_url=host_url, cookies=authenticated_cookies) as client:
    suite = InstalledPluginConformance(client, plugin_id)
    suite.assert_ready()
    suite.preserving_lifecycle(read_stable_plugin_state)
```

`plugin_conformance` lives in the host's `tools/` directory; add that directory
to the test harness import path. The plugin package itself must not import it.
The persistence probe can use public plugin actions or independently read only
the disposable runtime namespace as an administrator. It must not grant the
plugin access to host internals.

## Existing cross-repository runner

The supported full runner remains `tools/check_plugin_repository_lifecycle.py`.
It builds signed candidate releases using a separate official-plugin checkout,
then uses the reusable helper for installed lifecycle checks. Only synthetic
catalogue acquisition is substituted. Official public package downloads,
PostgreSQL, authorization, runtime HTTP, workers and gateway are real.

```bash
export DATABASE_URL=postgresql+psycopg://test:test@localhost:5432/plugin_acceptance
export SECRET_KEY='your-disposable-test-encryption-key'
export PYTHONPATH="$PWD/src/backend"
cd src/backend
alembic upgrade head
cd ../frontend
npm ci
npm run build
cd ../..
python tools/check_plugin_repository_lifecycle.py \
  --plugins-root /path/to/unnamed_tracking_app_plugins \
  --work-root /tmp/plugin-acceptance --browser
```

Use a disposable database and a new work root. Install the backend requirements,
`jsonschema`, and the plugin repository's locked npm/Playwright dependencies;
install Chromium with `npx playwright install --with-deps chromium --only-shell`
in the plugin checkout. The test environment needs a writable host data directory.
Omit `--browser` for the HTTP/worker checks alone.

| Area | Real acceptance |
| --- | --- |
| Validation | Invalid archive, unsafe manifest and wrong digest rejected before execution; official identity, versions, payload/archive hashes, trusted signing, README, tags and release policy checked |
| Install | Review host-classified scopes, approve, install actual official package and signed generated package, start and observe readiness/native UI |
| Operation | Real Jellyfin HTTP sync, configuration, progress and brokered credentials |
| Persistence | Runtime and host restart, stop/start, disable/enable, ordinary reinstall, update and rollback preserve identity and stored bytes |
| Inventory | Installed identity/version and enablement remain during a real runtime outage; browser renders while catalogue requests are deliberately held |
| Permission changes | Same-scope update proceeds; new-scope update stages; denial survives a scheduled check; explicit approval activates; revocation denies operations and explicit regrant restores access |
| Recovery | Deliberately failing worker startup restores the working predecessor, persistent bytes and grants; records error and administrator notification |
| Destruction | Confirmed purge resets owned configuration/storage/grants; uninstall removes namespace and inventory |
| Management tokens | Granular route matrix, unrelated application APIs, ordinary API-key issuance, plugin actions/UI/settings/secrets and unauthorized grant approval |
| Browser | All four manager views, catalogue tags, unique identity, README, permission risks/counts, duplicate-install choices, direct update review and outage diagnostics |

Successful checkpoints and source revisions are saved in `conformance.json`.
Failure marks that report failed and retains earlier checkpoints. Source revisions
can be null for exported trees; CI records `GITHUB_SHA`. Logs and actual screenshots
stay in the work root and are uploaded by `Plugin repository integration`.
The report excludes credentials and stored values.

![Host-owned permission review with scope counts and risk classification](../assets/plugin-integration/permission-review.png)

## Generated packages and release history

The host integration workflow also runs the plugin repository's existing builder,
signature/hash and structural validators, and `tools/check_host_contract.py` against
the actual candidate host. The builder strictly validates current generated
packages and catalogue metadata. Historical packages use their original contract;
they are not rewritten to pretend they were built with current metadata.

From the separate plugin checkout:

```bash
python tools/build_packages.py
python tools/verify_packages.py .validation/dist/*.utp
python tools/validate_packages.py .validation/dist/*.utp
python tools/check_host_contract.py --host-root /path/to/host
```

The plugin repository separately verifies published catalogue/release history with
`tools/distribution.py`, preserves immutable releases, and runs its independent
Python, JavaScript and browser suites. Both repositories' checks are required;
host acceptance alone cannot certify publisher-side source/history integrity.

## Isolation and practical limits

The runner intentionally sets `NONBUBBLE_ENV=true` in its disposable environment
so it works where namespace creation is unsupported. It probes Bubblewrap and
asserts the actual reduced process-isolation report. It does not claim a successful
real sandbox run; runtime policy tests cover usable and unsupported probes.

Readiness and successful operations supplement process-liveness checks. Package
rollback preserves current data and cannot reverse plugin-owned migrations.
Capture backups before testing destructive or incompatible migrations. See
[troubleshooting](plugin-runtime.md), [lifecycle semantics](plugin-lifecycle.md)
and the [previous dated verification](plugin-integration-verification.md).
