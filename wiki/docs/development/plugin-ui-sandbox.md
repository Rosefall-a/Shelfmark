# Custom frontend sandbox design

The declarative Plugin UI v1 host is the default. Complex interfaces can declare a static `frontend.entry` and run on the plugin's dedicated page in a sandboxed iframe.

## Security model

Custom frontend code does not execute inside the core Vue application. The iframe uses `sandbox="allow-scripts"` without `allow-same-origin`, and the host accepts messages only from that iframe's `contentWindow`.

The bridge supports basic context, ordinary settings, write-only secrets, and declared actions. CSP denies direct network connections and object embedding; PDF viewing is limited to blob-backed frames created from host-approved document bytes. The host does not expose environment values, credentials, DOM access, or a second permission system. Every bridge operation that reaches privileged host data is authorized again at the backend gateway.

Sandboxed and native frontends are distinct declarations and a plugin may declare both. `frontend.entry` remains the ordinary iframe model and does not require native execution. `native_frontend` represents trusted Vue/JavaScript/CSS integration and requires the explicit critical-risk `frontend.native` capability. Native loading is not enabled by merely declaring the bundle.

## Lifecycle

The runtime verifies package integrity and compatibility before the browser loads
custom code. Disabling, uninstalling, updating, or revoking permission refreshes
the host contribution registry. Sandboxed frontends cannot mutate the host DOM or
mount themselves into native host extension slots. A separately declared native
bundle can fill those slots only after the backend confirms `frontend.native`;
native activation does not change the iframe sandbox or bridge.

See [Plugin UI Protocol](plugin-ui.md) for the native renderer and [Plugin API v1](plugin-api-v1.md) for the gateway contract.
