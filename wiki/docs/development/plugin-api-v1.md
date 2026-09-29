# Plugin API v1

Plugin API v1 is the transport-neutral contract foundation for the Plugin Hub.

## Contract surface

The v1 boundary defines:

- application, plugin and installation identity;
- authenticated user request context;
- stable capability names and capability semantic versions;
- user, game and media representations;
- structured errors;
- bounded cursor pagination;
- timezone-aware timestamps;
- API version negotiation;
- versioned events, subscriptions and acknowledgements;
- notification and metadata provider coordinator interfaces.

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

Authentication, authorization, runtime isolation, storage and transport are downstream Plugin Hub work; this page describes the contract only.
