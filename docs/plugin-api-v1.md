# Plugin API v1

This document defines the first stable wire-contract layer for the plugin
platform tracked by #262 and implemented by #263.

## Scope

Plugin API v1 defines contracts, not transport. The gateway and runtime
implementations are downstream work.

The public boundary deliberately contains stable application/plugin/install
identities, optional user context, explicit capability identifiers, versioned
request/error/event envelopes, cursor pagination, and provider-neutral
notification/metadata DTOs.

It does not expose SQLAlchemy models, database sessions, environment
variables, application secrets, filesystem paths, Docker objects, or
arbitrary application internals.

## Compatibility

The current API version is v1. Additive fields require an explicitly
versioned contract decision. Removing or changing the meaning of an existing
field is a breaking change and requires a new major API version.

Event types have their own integer event_version. Event payloads must be
interpreted according to that version. Event versions are independent of the
overall API version.

Capability identifiers are stable strings. A new capability may be added
without changing the API version. Changing an existing capability's meaning
requires a compatibility review.

## Request identity

Every gateway request carries a request ID, core application identity,
plugin identity, installation identity/version, the requested capability, and
optional authenticated user context.

The contract does not itself grant access. Gateway work must authorize the
requested capability against the installation's grants.

## Errors

Errors use ErrorEnvelope with a stable machine-readable code, safe message,
request ID and optional structured validation details.

Internal exception messages, stack traces, SQL, secrets and environment
values must never be placed in an error envelope.

## Events

Events contain API version, event ID, event type, event version, UTC
occurrence time, source, optional user ID, and a versioned payload.

Subscriptions can be filtered by stable event type and relevant user IDs.
The gateway remains responsible for enforcing the events.subscribe grant and
preventing cross-user data leakage.

## Coordinator boundaries

Notification and metadata providers are implementations behind core-owned
coordinators. Plugins return normalized DTOs; core retains ownership of
provider selection/priority, user preferences, authorization, retries,
delivery state, persistence, provider lifecycle, and cross-provider
orchestration.

This preserves the extension seams identified by #238 and #242 without
duplicating those registries inside the plugin framework.

## Security and compatibility

The contract layer contains no ORM imports and no direct application-service
imports. DTOs reject unknown fields to reduce accidental coupling to internal
models.

Authentication, authorization, rate limiting, storage, process isolation and
package validation are separate downstream concerns.
