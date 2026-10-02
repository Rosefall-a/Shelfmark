# Plugin UI protocol

The frontend host consumes the versioned `PluginUiDocument` contract. Sandboxed,
declarative, and privileged native UI may coexist in one plugin, but each uses a
different host boundary.

## Native primitives

The v1 contract covers settings fields, validation, secrets, select options, actions, tables, dialogs, menus, and pages. Secret values are write-only and never included in schema defaults.

Installed plugins are managed through a per-plugin dialog with Overview, Settings, Permissions, and Diagnostics tabs. That Settings tab is the plugin's configuration area. A plugin may separately contribute a Settings application section with `settings_sections`; this is normal application navigation and does not move configuration or permission management out of the Plugin Manager.

## Navigation and host extensions

The first-class contribution contract supports navigation in the main sidebar, Settings sidebar, administration, game context, and media context. Contributions include an ID, label, icon, ordering, target, and optional visibility conditions. The host only exposes a contribution when the installation has the matching navigation capability.

Legacy pages may still opt into the application sidebar with `navigation.sidebar`.
New navigation entries target exactly one declared page, plugin route, Settings
section, or action. Plugin-owned routes remain under `/plugins/<plugin-id>/...`;
they never claim arbitrary application paths.

Plugins can add declarative content at these allowlisted extension slots:

- `home.after-widgets`
- `game.overview.after-header`
- `game.documents.actions`
- `media.detail.after-header`

An extension references a page in the same UI document. The host renders that page with the native component set and supplies a small context object (such as the current game ID) to actions. Unknown slots, dangling page references, and duplicate contribution IDs are rejected. Sandboxed and declarative UI can coexist, but sandboxed code does not mount into host slots.

The contribution document also defines Settings sections, overlays, dialogs,
contextual actions, plugin routes, and page replacements. A Settings contribution
uses its contribution ID directly, so `id: sessions` renders at
`/settings?section=sessions`. This is separate from the plugin's configuration in
Plugin Manager and separate from `/plugins/<plugin-id>/sessions`.

Replacements are page-specific and capability-specific: replacing Home requires
`frontend.page.replace.home`, while replacing Settings requires
`frontend.page.replace.settings`. There is no replace-everything capability.
Conflicts are resolved by ascending `order`, then plugin ID, then contribution ID.
Administrators see the selected plugin and can bypass a Settings replacement to
reach host Settings.

Game, media, and document actions carry a typed resource ID and optional resource
type. The backend confirms that the action is declared for that context and checks
the matching `frontend.context.*` grant before adding the scoped context passed to
the plugin. Client-supplied `_plugin_context` values are discarded.

## Security

UI declarations do not grant capabilities. Actions are sent through the
authenticated gateway and are authorized independently. Declarative slots never
evaluate plugin HTML or JavaScript. Native code executes only for an enabled,
compatible installation with the critical `frontend.native` grant.

See the [Plugin API v1](plugin-api-v1.md) and [Plugin Permissions & Scoped Identities](plugin-permissions.md) pages for the protocol and authorization boundaries.


## Runtime integration

The production `/api/plugins` routes mediate UI documents, frontend assets, ordinary settings, write-only secrets, and declared actions through the authenticated runtime. Browser code never connects to a plugin process directly.

The browser treats Plugin UI documents as untrusted data. Bundled custom frontends
run in a sandboxed iframe on their dedicated plugin page and cannot be mounted into
a host-page extension slot. The backend removes every contribution for which the
current installation/user lacks a grant before returning the document; frontend
checks are defense in depth.

## Privileged native bundle

`native_frontend.entry` and every path in `native_frontend.styles` must live below
`native/` in the verified package. The entry is an ES module exporting `activate`
(or a default activation function). Activation receives a versioned host context:

- `registerComponent(pageId, component)` associates a Vue component with a page
  already declared in `PluginUiDocument`;
- `onCleanup(callback)` registers plugin cleanup;
- `vue` exposes approved Vue composition/rendering primitives;
- `host` exposes navigation, declared action dispatch, plugin settings save, and
  opening the plugin's declared dialogs.

Native components can therefore render pages, Settings sections, extensions,
replacements, and overlays without special-case host code. The host owns the
registration table and stylesheet links. Disable, uninstall, update, permission
revocation, or activation failure removes those registrations and styles. Render
and cleanup errors are isolated so they cannot take down the application shell.

Component instances belong to a plugin ID and page ID. Switching between native
pages (including Settings sections) unmounts the previous page and creates a new
instance, even if both pages share a component. Use Vue's unmount lifecycle to
clean up page-local resources. Context updates within the same page retain the
instance, and page navigation does not reactivate the bundle.

Native CSS is loaded only from the separately permissioned native asset endpoint.
This supports a future trusted theme plugin without changing the meaning or CSP of
the sandboxed `frontend` bundle.


## Action context

Declarative page actions receive a host-created non-secret `_plugin_context`.
Contextual actions additionally receive the validated game, media, or document
scope described above. Sandboxed frontend actions use the same declared action
table. If an action declares `confirmation`, the host displays that confirmation
before dispatch, including for iframe requests. Secret fields are excluded from
ordinary settings saves and use the separate write-only secret operation.

## Opaque sandbox asset delivery

An opt-in `frontend.inline_assets: true` manifest flag lets a verified package use classic scripts and CSS in a cookie-isolated iframe. The authenticated entry response resolves only relative package assets within `frontend/`, embeds them with a fresh CSP nonce, and escapes raw-text closing tags. Limits are 32 assets and 8 MiB combined content. External URLs, traversal, query/fragment sources and module scripts are rejected. Asset endpoints remain authenticated; no origin/native privilege or unsafe-eval grant is added. The default remains false for existing frontends.

Game Docs reader declarations, document context and the original-download bridge are described in [Scoped document API](plugin-documents.md).
