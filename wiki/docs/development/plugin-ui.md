# Plugin UI protocol

The frontend host consumes the versioned PluginUiDocument contract and renders approved native controls only.

## Native primitives

The v1 contract covers settings fields, validation, secrets, select options, actions, tables, dialogs, menus, and pages. Secret values are write-only and never included in schema defaults.

## Security

UI declarations do not grant capabilities. Actions are sent through the authenticated gateway and are authorized independently. The host never evaluates plugin-supplied JavaScript or HTML.

See the [Plugin API v1](plugin-api-v1.md) and [Plugin Permissions & Scoped Identities](plugin-permissions.md) pages for the protocol and authorization boundaries.
