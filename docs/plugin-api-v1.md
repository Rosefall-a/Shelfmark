# Plugin API v1

See the [runtime authorization audit](plugin-api-v1-authorization-audit.md) for the
concrete HTTP request trace, enforcement corrections, integration coverage, and limits.

See [scoped session capabilities](plugin-session-capabilities.md) for rich session
metadata, ownership, confirmed revocation, and administrator GeoIP operations.

This document defines the contract foundation for Plugin Hub (#262), implemented by #263 and its contract sub-issues #274-#278.

## Scope

Plugin API v1 defines transport-neutral contracts. Gateway and runtime implementations are downstream work.

The public boundary defines stable application/plugin/installation identity, authenticated user context, capability families and semantic versions, stable user/game/media representations, error envelopes, cursor pagination, timestamps, API-version negotiation, versioned events, and notification/metadata coordinator interfaces.

The boundary does not expose ORM/database objects, sessions, environment variables, secrets, filesystem paths, Docker objects, or unrestricted application internals.

## Request identity and capabilities

Every gateway request carries a request ID, core application ID, plugin identity, installation ID/version, optional user context, and a requested capability with its semantic version.

Capability names are stable strings grouped into users, games, media, notifications, events, and plugin families. Changing an existing capability's meaning requires a capability-version change and compatibility review.

The contract does not grant access. A downstream gateway must authorize the requested capability against installation grants and user scope.

## DTOs, errors and pagination

Public DTOs are immutable and reject unknown fields. UUIDs are used for application-owned IDs. User, game and media representations contain only stable plugin-facing fields, not ORM objects.

Errors use a stable machine-readable code, safe message, request ID, and structured validation details. Internal exceptions, stack traces, SQL, secrets, and environment values must never be returned.

List contracts use a bounded cursor with a default limit of 50 and maximum of 200.

## Events

Events include API version, event ID/type/version, UTC occurrence time, source, optional user ID, and versioned payload. Subscriptions can filter event types and user IDs and declare a bounded delivery rate. Acknowledgements can carry a safe error envelope.

The gateway remains responsible for enforcing the events.subscribe capability and preventing cross-user delivery.

## Versioning and compatibility

v1 is the current major API version. VersionNegotiationRequest lets callers advertise supported versions and VersionNegotiationResponse identifies the selected version.

Additive fields require compatibility review. Removing a field or changing its meaning is breaking and requires a new major API version. Event versions are independent from API versions. Capability semantic changes require a capability-version change. Deprecation must be documented before removal.

## Provider coordinators

Notification and metadata providers are extension points behind core-owned coordinators. Plugins return normalized DTOs; core retains provider selection/priority, user preferences, authorization, retries, delivery state, persistence, lifecycle, and cross-provider orchestration.

## Security boundary

The contract package has no ORM or application-service imports. Strict validation reduces accidental internal-model leakage.

Authentication, authorization, rate limiting, storage, process isolation, package validation, and concrete transport remain downstream Plugin Hub work.


## Manifest and dependency model

Plugin API v1 now provides a strict static manifest contract. A manifest declares a stable plugin ID, semantic version, safe entrypoint, SDK/application compatibility ranges, requested capabilities and human-readable permission rationales, dependencies, declarative UI identifiers, namespaced storage quota, and SHA-256 integrity metadata with optional signature/key identifiers.

Manifest validation is deliberately static: it validates data without importing or executing plugin code. Unknown fields, invalid identifiers, malformed semantic versions, duplicate declarations, unsafe entrypoints, and ambiguous legacy migrations are rejected.

Compatibility is evaluated independently for SDK and application versions. An incompatible manifest is classified before activation and is quarantined rather than executed. Manifest version migration is a pure data transformation; it never loads plugin code.

Dependencies support required/optional dependencies, semantic-version constraints, deterministic dependency-first ordering, missing/incompatible dependency rejection, and cycle detection. Dependency resolution occurs before plugin activation.

Scoped game documents: see [document transport, format policy and security tests](plugin-documents.md).

## Provider media synchronization, background subscriptions and outbound JSON

These are additive **Plugin API v1** operations on the existing gateway. They do
not change package format, SDK, gateway transport or installation identity.

| Operation | Capability | Scope |
| --- | --- | --- |
| `media.sync` | `media.write` | Authenticated caller's existing Movies/TV/Anime domain records |
| `network.request` | `network.outbound` | Bounded JSON GET through the host, outside worker network isolation |
| `tasks.subscribe`, `tasks.unsubscribe` | `tasks.background` | Explicit authenticated UI action's own user; a worker cannot subscribe another user |
| `tasks.subscribers` | `tasks.background` | Plugin's opted-in user IDs; bounded offset/limit, maximum 100 |
| `tasks.request` | `tasks.background` | Delegates only `media.sync`/`media.write` to a subscribed target, checking target background and media grants live |

### Media sync contract

`media.sync` accepts one bounded DTO: `source`, `source_scope`, `external_id`,
`media_type` (`movie`, `tv_show`, `anime`), `title`, optional `genres`,
`runtime_minutes`, `poster_url`, `played`, `in_progress`, `expected_revision`,
`inventory_complete`, and at most 100 `episodes`. Each episode contains
`external_id`, `season` (including zero for specials), `number`, `watched`, optional
`title`, and optional `removed`. Unknown fields and invalid bounds are rejected.

The host derives a deterministic UUID from plugin ID, authenticated user, source,
source scope and external ID. This uses the existing media primary key rather than
introducing another provider database. The plugin stores its external mapping and
returned host ID. Source scope must distinguish server/account namespaces. Names
and category changes do not alter this ID. Identical titles remain distinct.
Upserts serialize by identity using a transaction advisory lock.

A successful response returns `id`, `created`, `status`, `revision`. Revision is a
SHA-256 digest of actual watch status, episode flags and season counts. An existing
item requires its last returned revision. Local watch changes return
`conflict=local_watch_state_changed` and the current revision, without mutation.
A plugin may use that revision only after explicit user resolution. Local deletion
returns `locally_deleted`; a category change returns `category_changed` instead of
creating another record or dropping local notes/references. Do not silently adopt
unrelated existing records by title. Locked metadata, notes, ratings, favorites
and rewatch history remain protected. Legacy `media.import` remains available.

Films map played to WATCHED; unwatched positions imply IN_PROGRESS, otherwise
WATCHLIST. Episodic media writes real episode flags and derives season counters.
Completion requires an explicitly finalized, nonempty complete inventory with
all episodes watched. Until finalization, a partial watched inventory is
IN_PROGRESS. A root object's existence or played flag does not complete a series.
Episode removal is explicit and bounded; it retains unrelated local fields.

### Background consent and lifecycle

Subscriptions are runtime-owned records in a protected `host/tasks/` storage
namespace. Plugin storage operations cannot read/write those records or list their
keys. Registration gets identity from the authenticated action context, not a
payload-supplied user ID. Delegated work uses the existing private HTTP bridge,
then the public gateway checks the target's media grant. Unsubscribed targets,
revoked grants, arbitrary methods, and nested delegation are rejected. Normal
reinstall/update/rollback retains subscription/storage state; purge/uninstall
removes it through the existing lifecycle. Installing a different plugin never
inherits another plugin's subscriptions.

`tasks.request` payload is `{user_id, method: "media.sync", capability:
"media.write", payload: <media DTO>}`. A background grant does not grant media
access or authorize arbitrary impersonation. The target needs both grants.

### Outbound JSON

`network.request` accepts `{url, headers?}` and performs only HTTP(S) GET. It uses
normal TLS verification, an 8-second timeout, no redirects and a 4 MiB response
limit. URLs cannot contain embedded credentials or fragments. Header names are
restricted to Accept, Authorization and X-Emby-Token; count/length and CRLF bounds
are enforced. The generic transport treats those headers as opaque strings and
contains no provider behavior. Responses are `{status: 200, data: <object/array>}`
or a safe `{status, error}` for HTTP/connection failures. Malformed/oversized JSON
is rejected. No arbitrary response headers/bodies are returned on errors.

Network grants remain explicit, high-risk egress authorization; the administrator
chooses appropriate destinations. This operation enables isolated workers to use
HTTP without changing their sandbox policy. It does not proxy playback.

### Existing media actions

Use `frontend.page.extend` with `media.detail.after-header` and an authenticated
`frontend.context.media` action. The existing `external_navigation` action flag
now also applies to contextual buttons: a `redirect_url` is accepted only when
that flag is declared and the target is credential-free HTTP(S). Failed actions
show an unavailable/error message. Native plugins can render normal HTTP links.
Native contributions remount when the authenticated resource context changes, preventing a previous media item's action destination from remaining visible. There is no provider-specific button or media action in core.
