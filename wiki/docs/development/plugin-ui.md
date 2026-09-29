# Plugin UI protocol

The frontend host consumes the versioned PluginUiDocument contract and renders approved native controls only.

## Native primitives

The v1 contract covers settings fields, validation, secrets, select options, actions, tables, dialogs, menus, and pages. Secret values are write-only and never included in schema defaults.

## Security

UI declarations do not grant capabilities. Actions are sent through the authenticated gateway and are authorized independently. The host never evaluates plugin-supplied JavaScript or HTML.

See the [Plugin API v1](plugin-api-v1.md) and [Plugin Permissions & Scoped Identities](plugin-permissions.md) pages for the protocol and authorization boundaries.


## Runtime integration

The native host and management client are designed to address authenticated, gateway-facing plugin operations, but the production `/api/plugins` host/runtime path is not yet wired end-to-end. That integration remains tracked by #320. They must not communicate with plugin processes directly.

The browser treats Plugin UI documents as untrusted data and renders only the native v1 primitives. Custom frontend code is not loaded by this host.
