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
