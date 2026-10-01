# Plugin UI protocol

Plugin UI v1 is a declarative, versioned document exchanged through the
authenticated Plugin Gateway. The core renders fixed primitives by default. A
plugin may additionally declare an iframe frontend or an explicitly permissioned
native bundle without changing the declarative schema's trust level.

## Schema

A PluginUiDocument contains:

- settings sections and fields (text, textarea, password, number, boolean, select, multiselect);
- explicit validation constraints;
- write-only secret fields (no defaults or secret values in the UI document);
- actions carrying optional capability references and confirmation text;
- read-only tables;
- dialogs that reference declared actions;
- menus that target local pages or declared actions;
- pages that compose those primitives;
- navigation, Settings sections, host-page extensions, overlays/dialogs,
  contextual actions, plugin-owned routes, and page-scoped replacements.

All identifiers are stable lowercase IDs. Schema version v1 is negotiated as part of the Plugin API version rather than inferred from frontend implementation details.

## Security boundary

The document is data, not executable UI code. Labels/descriptions are plain text, external URLs and arbitrary HTML are not part of the schema, and menu/page references are validated before rendering. The host treats capability declarations as metadata only: the gateway remains authoritative for authorization.

Secret fields are represented only by their metadata. Existing secret values are never returned in a UI document or default value. A renderer uses a password control and sends a value only when explicitly submitted.

## Compatibility

Unknown schema versions must be rejected or rendered as an unsupported-plugin state. New schema versions must add semantics without silently changing the meaning of existing v1 fields.

## Executable UI modes

`frontend.entry` is loaded only in the sandboxed iframe. `native_frontend` is
loaded into the Vue host only when the enabled installation has
`frontend.native`; its module can register components for page IDs already
declared by this document. The host owns registration, stylesheet,
failure-isolation, and cleanup lifecycle.

## Custom frontend sandbox

See [Custom plugin frontend sandbox design](plugin-ui-sandbox.md). The authenticated
gateway remains the application boundary for both executable modes.
