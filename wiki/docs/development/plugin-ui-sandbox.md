# Custom frontend sandbox design

The declarative Plugin UI v1 host is the default. Complex interfaces can declare a static `frontend.entry` and run on the plugin's dedicated page in a sandboxed iframe.

## Security model

Custom frontend code does not execute inside the core Vue application. The iframe uses `sandbox="allow-scripts"` without `allow-same-origin`, and the host accepts messages only from that iframe's `contentWindow`.

The bridge supports basic context, ordinary settings, write-only secrets, and declared actions. CSP denies direct network connections and object embedding; PDF viewing is limited to blob-backed frames created from host-approved document bytes. The host does not expose environment values, credentials, DOM access, or a second permission system.

## Lifecycle

The runtime verifies package integrity and compatibility before the browser loads custom code. Disabling or uninstalling removes its host navigation contribution immediately. Custom frontends cannot mount inside native host extension slots; those slots accept declarative pages only.

See [Plugin UI Protocol](plugin-ui.md) for the native renderer and [Plugin API v1](plugin-api-v1.md) for the gateway contract.
