# Plugin UI protocol

The frontend host consumes the versioned PluginUiDocument contract and renders approved native controls only.

## Native primitives

The v1 contract covers settings fields, validation, secrets, select options, actions, tables, dialogs, menus, and pages. Secret values are write-only and never included in schema defaults.

Installed plugins are managed through a per-plugin dialog with Overview, Settings, Permissions, and Diagnostics tabs. That Settings tab is the plugin's configuration area. A plugin may separately contribute a Settings application section with `settings_sections`; this is normal application navigation and does not move configuration or permission management out of the Plugin Manager.

## Navigation and host extensions

The first-class contribution contract supports navigation in the main sidebar, Settings sidebar, administration, game context, and media context. Contributions include an ID, label, icon, ordering, target, and optional visibility conditions. The host only exposes a contribution when the installation has the matching navigation capability.

Legacy pages may still opt into the application sidebar with `navigation.sidebar`. New plugin-owned routes remain host registered and namespaced. Plugins cannot register arbitrary browser paths.

Plugins can add declarative content at these allowlisted extension slots:

- `home.after-widgets`
- `game.overview.after-header`

An extension references a page in the same UI document. The host renders that page with the native component set and supplies a small context object (such as the current game ID) to actions. Unknown slots, dangling page references, and duplicate contribution IDs are rejected. Sandboxed and declarative UI can coexist, but sandboxed code does not mount into host slots.

The contribution document also defines Settings sections, overlays, dialogs, contextual actions, plugin routes, and page replacements. Replacements are page-specific and capability-specific: for example, replacing Home requires `frontend.page.replace.home`, while replacing Settings requires `frontend.page.replace.settings`. There is no generic replace-everything capability. When multiple enabled plugins compete for the same replacement, deterministic ordering selects one and the host displays a conflict warning.

## Security

UI declarations do not grant capabilities. Actions are sent through the authenticated gateway and are authorized independently. Native slots never evaluate plugin-supplied JavaScript or HTML; bundled frontends use the separate sandbox described below.

See the [Plugin API v1](plugin-api-v1.md) and [Plugin Permissions & Scoped Identities](plugin-permissions.md) pages for the protocol and authorization boundaries.


## Runtime integration

The production `/api/plugins` routes mediate UI documents, frontend assets, ordinary settings, write-only secrets, and declared actions through the authenticated runtime. Browser code never connects to a plugin process directly.

The browser treats Plugin UI documents as untrusted data and renders only the native v1 primitives. Bundled custom frontends run in a sandboxed iframe on their dedicated plugin page and cannot be mounted into a host-page extension slot.


## Action context

Native plugin actions receive a non-secret `_plugin_context` value containing the current page ID, page title, and browser path. Sandboxed frontend actions use the same declared action table. If an action declares `confirmation`, the host displays that confirmation before dispatch, including for iframe requests. Secret fields are excluded from ordinary settings saves and use the separate write-only secret operation.
