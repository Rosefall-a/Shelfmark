# Custom plugin frontend sandbox design

This is the future extension path for UI that cannot be expressed by Plugin UI v1. It is a design only; v1 plugins must use the native declarative host.

## Boundary

Custom frontend code must run in a separately sandboxed frontend execution context. It must not be loaded as a script into the core Vue application, receive core environment variables, access the DOM outside its mount boundary, or obtain application credentials directly.

The custom host still talks to the Plugin Gateway. The gateway remains responsible for plugin identity, installation identity, user/device context, API version negotiation, and capability authorization.

## Proposed transport

1. The plugin advertises a custom-UI capability and a separately versioned custom UI protocol.
2. The core requests a signed/verified package from the plugin runtime.
3. The host verifies package integrity and compatibility before execution.
4. The package is loaded into an isolated browser execution context with a narrow message channel.
5. Messages are typed request/response envelopes; arbitrary DOM, network, storage, and parent-window access are not exposed.
6. Gateway operations are explicit messages and are independently authorized.
7. The host can terminate the context without affecting the core frontend.

The exact browser isolation primitive remains an implementation decision after the plugin runtime exists. Options must be evaluated against the supported browser matrix before adoption; this document does not authorize iframe, worker, WebAssembly, or another mechanism as a security boundary by itself.

## Secret handling

Secrets never cross into custom UI as environment variables or unrestricted configuration. A secret operation must be represented by an explicit gateway request and return only the minimum required result. The host should prefer opaque handles where a long-lived secret is unnecessary.

## Failure behavior

Custom UI failure is isolated to the plugin surface. Timeouts, malformed messages, rejected capability requests, incompatible protocol versions, and renderer crashes produce an error state and may quarantine the plugin through the lifecycle system. They must not prevent core startup or navigation.

## Compatibility

Custom UI has its own protocol version and compatibility range. It cannot change the meaning of Plugin UI v1 documents. A plugin may ship both native and custom UI; native UI remains the fallback when the custom protocol is unavailable.

## Non-goals

This design does not implement arbitrary JavaScript execution, package installation, browser isolation, or a new authorization mechanism. Those belong to the runtime, update/security, and gateway work downstream of #269.
