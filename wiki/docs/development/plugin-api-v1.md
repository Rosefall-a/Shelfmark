# Plugin API v1

Plugin API v1 is the transport-neutral contract foundation for the Plugin Hub.

## Contract surface

The v1 boundary defines:

- application, plugin and installation identity;
- authenticated user request context;
- stable capability names and capability semantic versions;
- user, game, media, safe document, session, and notification-delivery representations;
- structured errors;
- bounded cursor pagination;
- timezone-aware timestamps;
- API version negotiation;
- versioned events, subscriptions and acknowledgements;
- notification and metadata provider coordinator interfaces.
- host-mediated namespaced and privileged backend route declarations.

The contract layer must not expose ORM models, database sessions, environment values, secrets, filesystem paths, or unrestricted application internals.

## Versioning

The current API version is v1. The contract library provides VersionNegotiationRequest
and VersionNegotiationResponse. Deployed workers send an optional `api_version`
through the existing JSON-line bridge; omission defaults to v1 for older SDKs.
The runtime rejects incompatible versions and advertises supported versions in
health. Success and structured failure responses retain correlation. See the
[deployed platform boundary](plugin-platform.md) for the wire format and limits.

Breaking changes require a new major API version. Additive changes require compatibility review. Event versions are independent of API versions. Capability semantic changes require a capability-version change.

## Request and authorization context

A request contains a request ID, core application ID, plugin identity, installation identity/version, optional user context, and a versioned requested capability.

The DTO does not grant authorization. The gateway must verify installation grants and user scope before servicing the request.

## Events

Events have an API version, event ID/type/version, UTC occurrence timestamp, source, optional user ID and versioned payload. Subscriptions can filter event types and user IDs. The gateway must enforce the events.subscribe grant and prevent cross-user delivery.

## Provider coordinators

Notification and metadata providers return normalized DTOs to core-owned coordinators. Provider selection, authorization, persistence, retries, delivery state and orchestration remain core responsibilities.

## Security

Public DTOs reject unknown fields and are immutable. Error envelopes deliberately exclude stack traces, SQL, secrets and environment values.

The production host/runtime path implements authentication, exact grant checks, runtime isolation, private storage, action dispatch, and structured diagnostics. Contract types still do not grant access by themselves.


## Manifest and dependency model

Plugin API v1 now provides a strict static manifest contract. A manifest declares a stable plugin ID, semantic version, safe entrypoint, SDK/application compatibility ranges, requested capabilities and human-readable permission rationales, dependencies, declarative UI identifiers, namespaced storage quota, and SHA-256 integrity metadata with optional signature/key identifiers.

Manifest validation is deliberately static: it validates data without importing or executing plugin code. Unknown fields, invalid identifiers, malformed semantic versions, duplicate declarations, unsafe entrypoints, and ambiguous legacy migrations are rejected.

Compatibility is evaluated independently for SDK and application versions. An incompatible manifest is classified before activation and is quarantined rather than executed. Manifest version migration is a pure data transformation; it never loads plugin code.

Dependencies support required/optional dependencies, semantic-version constraints, deterministic dependency-first ordering, missing/incompatible dependency rejection, and cycle detection. Dependency resolution occurs before plugin activation.

See [Plugin capability APIs](plugin-capabilities.md) for the current method map and domain-specific limits, and [Plugin backend routes](plugin-backend-routes.md) for authenticated HTTP integration.

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
