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

The current API version is v1. Callers advertise supported versions with VersionNegotiationRequest and the gateway responds with VersionNegotiationResponse.

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
