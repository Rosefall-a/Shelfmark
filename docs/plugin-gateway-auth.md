# Plugin Gateway Authentication

This document records the authenticated application-to-gateway trust model implemented for #265 and #282.

## Identities

The core application has a stable application_id. The plugin gateway has a separate stable gateway_id. Both identities are explicitly carried by the bootstrap request and response.

The configured gateway URL, hostname, IP address, Docker service name, or network reachability is never treated as proof of identity.

## Bootstrap credential

The core provisions a high-entropy bootstrap credential. The gateway stores only a keyed digest of the credential and binds it to the application identity.

Credential material is returned only at issuance and is never retained by the credential store. Bootstrap credentials have a bounded lifetime and may be rotated or revoked.

## Replay protection

Every bootstrap request contains a UUID nonce and an issued-at timestamp. The gateway rejects requests outside the configured clock-skew window and records each nonce atomically through the credential-store contract. A reused nonce is rejected even when the bootstrap credential remains valid.

A durable CredentialStore implementation is required for production so credential revocation and replay state survive gateway restarts. The repository includes an in-memory implementation for tests/development only.

## Session credentials

A successful bootstrap produces a separate short-lived session credential bound to the same application identity and gateway identity. Session credentials are independently revocable and rotatable.

Session credentials must be presented on subsequent core-to-gateway requests. The gateway never trusts a URL alone.

## API version selection

The bootstrap request advertises supported Plugin API major versions. The gateway selects v1 only when it is explicitly offered; otherwise bootstrap fails rather than silently downgrading.

## Request context

RequestContext includes gateway_id alongside application_id, plugin identity, installation identity, user context, request ID, and capability. This prevents a request from omitting which gateway authenticated it.

## Security boundary

This implementation does not expose database credentials, environment variables, filesystem paths, Docker objects, or application secrets to plugins. Plugin installation credentials and capability grants remain downstream work for #283 and #266.

The credential store is an explicit persistence seam rather than an accidental plugin-storage dependency. This keeps #265 trust state separate from #268 plugin-owned storage.
