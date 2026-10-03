# Plugin Storage

Issue #268 defines persistent storage owned by the Plugin Runtime. Storage is
namespaced by the immutable plugin ID and is never implemented as a core
PostgreSQL schema or plugin-controlled migration.

## Namespace

Each installed plugin receives one private namespace:

    <storage-root>/<plugin-id>/
        .storage.json
        data/
        cache/
        generated/

The runtime constructs the namespace from the authenticated plugin identity;
the plugin does not supply a namespace path. Keys are relative paths within
that namespace. Absolute paths, .., symlinks and other path traversal are
rejected.

The storage root is mounted only into the Plugin Runtime service. The core
backend and browser never receive that filesystem mount.

## API

The stable runtime API is byte-oriented:

- put(key, value) — atomically replace a value;
- get(key) — retrieve a value;
- delete(key) — remove a value;
- keys(prefix) — deterministic listing;
- metadata() / set_schema_version() — plugin-owned data schema version;
- backup() / restore() — namespace-scoped backup and restore;
- uninstall() — delete only the plugin namespace.

These are runtime library operations. The deployed SDK exposes `storage.put`,
`storage.get`, `storage.delete` and `storage.keys` with UTF-8 string values.
`plugin.storage` must be granted; the runtime rechecks host authorization before
each operation. Library metadata and backup/restore methods are not currently
separate public gateway methods. The SDK does not receive SQLAlchemy objects or
filesystem paths. Sandboxed workers cannot directly read the broker's namespace.

## Quotas and security

Every namespace has a fixed byte quota derived from the plugin manifest.
Writes account for replacement size and fail before exceeding the quota.
Restores are validated against the same quota. Symlinks are rejected and
archives cannot contain absolute or traversal paths.

Storage access does not grant any other capability. In particular, the
plugin.storage capability does not expose the core database, application
filesystem or Docker socket.

## Backup/restore

Backups are gzip-compressed tar archives containing the plugin namespace and
metadata. A restore must match the installed plugin ID and quota and is
staged before replacement. Existing data is not partially overwritten if
validation fails.

Deployment backups must include the persistent plugin-runtime storage
volume. Plugin data remains independent from executable/package versions.

Configuration lives outside the executable package in the runtime volume's
`.configuration` directory. Legacy package-local `.settings.json` values migrate
before replacement. Secrets, profiles and imported history remain in the plugin
namespace. Restart, stop/start, disable/enable, update, rollback and reinstall
preserve these stores. Uninstall and explicitly confirmed reinstall-with-purge
remove both. Package-history deletion never touches plugin data. Purging removes
host permission requests, grants, scoped clients and provider registrations;
host security audit records remain host-owned records.

## Availability and lifecycle

Storage unavailable/failing operations return a storage error to the plugin;
they do not alter core database state. Disable does not delete data. Uninstall
does. Lifecycle orchestration in #270 owns when storage is made available.

## Compatibility

Plugin data schema version is stored with the namespace. Package/SDK
compatibility is evaluated by the manifest layer (#264); storage migrations
are plugin-owned data transformations and must not become core Alembic
migrations.

## Tests

src/plugin-runtime/tests/test_storage.py covers namespace isolation,
persistence, quota enforcement, versioning, uninstall cleanup, backup/restore,
cross-plugin restore rejection and archive traversal rejection.
