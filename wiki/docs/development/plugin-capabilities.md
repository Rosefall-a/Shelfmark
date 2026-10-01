# Plugin capability APIs

Plugin API v1 maps domain gateway methods to their required capabilities. The runtime
attaches its own plugin/installation identity, the authenticated action user (or the
installation's activation user for background requests), request ID, and requested
capability/version. The host checks the live installation and persisted grants for
every operation. Runtime-local storage/settings and delivery use the side-effect-free
`capabilities.check` method to recheck their required capability before execution.
Browser controls and manifest/UI/route declarations never authorize operations.

Grants must match the installation, capability version and user/device scope. The
current browser/runtime transports have no authenticated device identity and cannot
consume device-scoped grants. A grant from another installation is denied even when
`plugin_id` matches. Revocation takes effect at the next authorization check.

## Hierarchical grants

Capabilities use a canonical hierarchy. An administrator can grant one leaf, such as `games.read`, or its parent, `games`, which authorizes all current children in that subtree. A leaf never authorizes its parent or a sibling. The grant remains scoped to the installation, capability version, and optional user/device identity.

The principal families are:

- user data: `users`, `games`, `media`, `documents`, and `sessions`;
- frontend: navigation locations, Settings sections, overlays/dialogs, page extensions, page-scoped replacements, plugin routes, and `frontend.native`;
- backend: namespaced plugin routes and privileged host routes;
- notifications: sending notifications and registering/delivering through providers;
- external access: `network.outbound`.

`api.full` is a critical, exceptional backend grant. It implies the registered backend/domain API capabilities, but deliberately does not imply `frontend.native`, frontend contributions, or unrestricted network access. The install and permission-review APIs return the canonical category, hierarchy, risk, and high-privilege metadata so clients do not maintain a competing permission catalogue.

## Domain APIs

| Capability | Methods | Returned data and limits |
| --- | --- | --- |
| `documents.read` | `documents.list`, `documents.read` | User-owned game-document metadata and at most 5 MiB of base64 PDF or UTF-8 plain text. No filesystem paths, HTML, SVG, active content, or arbitrary binary data. |
| `sessions.read` | `sessions.list` | Opaque session ID, creation time, expiry time, and active state for the authenticated user. No cookies, tokens, hashes, IP addresses, or user-agent data. |
| `sessions.revoke` | `sessions.revoke` | Deletes one session only when it belongs to the authenticated user. UI actions should declare host-owned confirmation. |\n| `sessions.admin.read` | `sessions.admin.list` | Administrator-only session metadata including user, device, location and anomaly fields. The host re-checks administrator status. |\n| `sessions.admin.revoke` | `sessions.admin.revoke`, `sessions.admin.revoke_all` | Administrator-only session revocation. |\n| `media.write` | `media.import` | Imports normalized movie metadata into the authenticated user media library; plugins never receive ORM objects. |\n| `tasks.background` | Plugin-owned background execution | Allows a plugin to remain active for approved background work; the host still controls process/resource limits. |
| `notifications.send` | `notifications.send` | Creates a user-scoped in-app notification; core then creates eligible provider delivery rows. |
| `notification_providers.register` | `notification_providers.register`, `notification_providers.unregister` | Registers a provider ID namespaced below the plugin ID and one declared action ID. |
| `notification_providers.deliver` | Core invokes the registered action | Allows minimized eligible delivery work after core preference/grant checks. It does not allow querying notification tables or controlling retries. |

Existing leaves include `users.read`, `users.profile.read`, `games.read`, `games.write`, `media.read`, `media.write`, `events.subscribe`, `plugin.storage`, and `plugin.settings`. `home.replace` and `app.global` remain host-owned legacy UI extension slots. A plugin can contribute declarative UI to those slots but cannot mutate Vue components or the DOM. External navigation actions must explicitly declare `external_navigation` and are limited to HTTP(S) URLs.

Frontend context leaves are `frontend.context.game`,
`frontend.context.media`, and `frontend.context.documents`. Context values are
reconstructed and authorized at the backend action boundary rather than trusted
from browser-supplied action values. `frontend.native` is the only capability that
permits a verified bundle to register Vue components or CSS in the host document;
it remains critical-risk and is not implied by any navigation or page capability.

Only methods present in the gateway dispatch table are callable; presenting a different capability string does not change the method's authorization requirement.

## Errors and action results

Denied grants return 403 at the host boundary. Invalid, missing, or out-of-scope resource identifiers produce bounded validation/not-found errors without disclosing whether another user's resource exists. Plugin actions return structured JSON and a host-generated `request_id` suitable for correlating administrator diagnostics.

One-shot action handlers use the same mediated request/response protocol as long-running plugins. They do not receive host credentials or a direct network connection.
