# Developing third-party plugins

Build a standalone `.utp` package using the existing Plugin API v1 and SDK. The
[official plugin repository](https://github.com/Rosefall-a/unnamed_tracking_app_plugins)
contains the package builder, schema, protocol helpers and examples. Its
[author guide](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/blob/main/docs/plugin-author-guide.md)
and [catalogue specification](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/blob/main/docs/catalogue-specification.md)
describe publisher-side distribution.

## Define the public contract

Choose a stable globally unique plugin ID and semantic version. Declare SDK and
application compatibility ranges, entrypoint, exact capabilities and permissions,
permission rationale, dependencies, storage quota and UI identifiers. The
[manifest validator](plugin-manifest.md) rejects unknown fields, duplicate
declarations and unsafe paths without importing the plugin.

Risk belongs to the host capability registry. A plugin supplies the reason it
needs a scope, not its risk rating. Request individual scopes where practical and
handle denial and revocation. Privileges never follow from a manifest declaration.
Administrative capabilities also check the actual user's administrator role.

Use `sdk.plugin_protocol.request` for supported methods. Keep stdout reserved for
the JSON-line protocol and use stderr for diagnostics. Do not make database
connections, import `src.database`/`src.features`/`src.plugin_api`, read host paths,
or assume Docker hostnames, tokens or localhost services exist in the plugin.
The [gateway contract](plugin-platform.md) is the public boundary.

## Configuration, storage and secrets

Ordinary configuration uses declared host-owned settings and the granted
`settings.get` method. Persistent data uses `storage.put`, `storage.get`,
`storage.delete` and `storage.keys`, with the `plugin.storage` grant checked on
every operation. SDK values are JSON-compatible UTF-8 strings; the underlying
storage library is byte-oriented and is owned by the runtime.

Mark UI credential fields as secrets and use the plugin-scoped secret-write
operation. Read credentials through the authorized broker under `secrets/<key>`.
Never put them in ordinary settings, browser local storage, action diagnostics
or package files. Broker files have owner-only permissions and a namespace quota;
they are not exposed as a general host filesystem or encrypted vault contract.
The sandbox's `/plugin-data` is an empty private filesystem, not direct access
to brokered persistent storage. See [storage and backups](plugin-storage.md).

Keep data migrations compatible with rollback, or require an administrator's
explicit migration/backup workflow. Rolling back executable code does not restore
an older data schema. Test credentials and configuration across preserving
reinstall, update and rollback, and reset them only on explicit purge/uninstall.

## UI and background work

The existing `ui.json` supports host-rendered settings, actions, pages and
allowlisted contributions. Custom frontend bundles use the sandboxed iframe
and validated host bridge. Native frontends are a separate privileged capability
that requires host consent. UI actions use host-confirmed context and the same
runtime/gateway authorization as long-running workers. See [UI](plugin-ui.md),
[iframe security](plugin-ui-sandbox.md) and [backend routes](plugin-backend-routes.md).

Long-running workers own their bounded scheduling loop and report `lifecycle.ready`.
The `tasks.background` declaration does not create an unrestricted host scheduler
or an API for manipulating unrelated scheduled tasks. Stop/disable removes
contribution execution; background domain calls carry the installation's activation
user and remain subject to live grants. Poll supported events using
`events.poll` with `events.subscribe`; the deployed surface returns bounded,
user-owned game/media changes and a timestamp cursor. The contract library's
subscription/acknowledgement DTOs are not a deployed push transport. See
[capability methods](plugin-capabilities.md).

Do not assume outbound sockets are available under Bubblewrap. A declared
`network.outbound` scope alone does not implement arbitrary network forwarding.
The runtime has a narrow host-approved Discord delivery path; a plugin needing
another external operation must use a supported gateway method or coordinate
an incremental public capability. Reduced isolation has different operating-system
protections and must be reported honestly. See [runtime policy](plugin-runtime.md).

## Verify and distribute

1. Run the independent plugin tests and builder. Inspect actual generated `.utp`
   bytes, manifest/UI consistency and SDK packaging.
2. Verify canonical payload digest and archive hash. Trusted publication uses an
   authorized Ed25519 publisher key; never modify a signed archive after signing.
3. Generate catalogue metadata from verified packages. Preserve release history,
   README, safe icons, tags and release-specific automatic-update policy.
4. Preview through the host Plugin Manager, review trust and permissions, approve
   only needed scopes, then exercise the installed worker through public actions.
5. Run [installed-plugin conformance](plugin-conformance.md) and the existing
   cross-repository contract checker against the candidate host. Test both the
   default-deny and explicitly granted paths, including a new-scope update.

Unsigned development packages remain supported through explicit untrusted review.
Catalogue membership never grants signing trust or permissions. Existing v1 SDKs
remain compatible with additive gateway correlation/version/error metadata.
