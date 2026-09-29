# Plugin UI protocol

Plugin UI v1 is a declarative, versioned document exchanged through the authenticated Plugin Gateway. The core frontend renders only a fixed set of native primitives; plugin code is never loaded into the browser.

## Schema

A PluginUiDocument contains:

- settings sections and fields (text, textarea, password, number, boolean, select, multiselect);
- explicit validation constraints;
- write-only secret fields (no defaults or secret values in the UI document);
- actions carrying optional capability references and confirmation text;
- read-only tables;
- dialogs that reference declared actions;
- menus that target local pages or declared actions;
- pages that compose those primitives.

All identifiers are stable lowercase IDs. Schema version v1 is negotiated as part of the Plugin API version rather than inferred from frontend implementation details.

## Security boundary

The document is data, not executable UI code. Labels/descriptions are plain text, external URLs and arbitrary HTML are not part of the schema, and menu/page references are validated before rendering. The host treats capability declarations as metadata only: the gateway remains authoritative for authorization.

Secret fields are represented only by their metadata. Existing secret values are never returned in a UI document or default value. A renderer uses a password control and sends a value only when explicitly submitted.

## Compatibility

Unknown schema versions must be rejected or rendered as an unsupported-plugin state. New schema versions must add semantics without silently changing the meaning of existing v1 fields.

## Future custom UI

Complex UIs have a separate design path in #295. They must not be introduced by adding arbitrary HTML, JavaScript, URLs, or component names to the declarative schema.
