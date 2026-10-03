# Custom plugin frontend sandbox design

Plugin UI v1 supports a sandboxed custom frontend for interfaces that cannot be
expressed by the declarative renderer. This remains the default custom-code mode
and is separate from the critical-risk native frontend contract.

## Boundary

Custom frontend code must run in a separately sandboxed frontend execution context. It must not be loaded as a script into the core Vue application, receive core environment variables, access the DOM outside its mount boundary, or obtain application credentials directly.

The custom host still talks to the Plugin Gateway. The gateway remains responsible for plugin identity, installation identity, user/device context, API version negotiation, and capability authorization.

## Transport

1. The plugin declares `frontend.entry` in its verified package.
2. The core requests a signed/verified package from the plugin runtime.
3. The host verifies package integrity and compatibility before execution.
4. The entry is loaded in an iframe with `sandbox="allow-scripts"` and a narrow message channel.
5. Messages are typed request/response envelopes; arbitrary DOM, network, storage, and parent-window access are not exposed.
6. Gateway operations are explicit messages and are independently authorized.
7. The host can terminate the context without affecting the core frontend.

The bridge accepts settings, write-only secret, declared action, and bounded
context operations. It does not grant same-origin access, host DOM access, or
arbitrary network access.

## Secret handling

Secrets never cross into custom UI as environment variables or unrestricted configuration. A secret operation must be represented by an explicit gateway request and return only the minimum required result. The host should prefer opaque handles where a long-lived secret is unnecessary.

## Failure behavior

Custom UI failure is isolated to the plugin surface. Timeouts, malformed messages, rejected capability requests, incompatible protocol versions, and renderer crashes produce an error state and may quarantine the plugin through the lifecycle system. They must not prevent core startup or navigation.

## Compatibility

Custom UI has its own protocol version and compatibility range. It cannot change
the meaning of Plugin UI v1 documents. A plugin may ship `frontend` and
`native_frontend` together. The iframe remains usable without `frontend.native`;
denying native permission never promotes iframe code into the host document.

## Non-goals

The sandbox is not a second authorization mechanism. Backend gateway checks remain
authoritative for every privileged bridge operation.
