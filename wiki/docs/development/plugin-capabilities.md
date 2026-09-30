# Plugin capability APIs

Plugin API v1 maps every gateway method to exactly one capability. The runtime attaches plugin ID, installation ID, user ID, request ID, and the requested capability; the backend then requires a matching active grant for that installation, version, and user scope.

## Domain APIs

| Capability | Methods | Returned data and limits |
| --- | --- | --- |
| `documents.read` | `documents.list`, `documents.read` | User-owned game-document metadata and at most 5 MiB of base64 PDF or UTF-8 plain text. No filesystem paths, HTML, SVG, active content, or arbitrary binary data. |
| `sessions.read` | `sessions.list` | Opaque session ID, creation time, expiry time, and active state for the authenticated user. No cookies, tokens, hashes, IP addresses, or user-agent data. |
| `sessions.revoke` | `sessions.revoke` | Deletes one session only when it belongs to the authenticated user. UI actions should declare host-owned confirmation. |\n| `sessions.admin.read` | `sessions.admin.list` | Administrator-only session metadata including user, device, location and anomaly fields. The host re-checks administrator status. |\n| `sessions.admin.revoke` | `sessions.admin.revoke`, `sessions.admin.revoke_all` | Administrator-only session revocation. |\n| `media.write` | `media.import` | Imports normalized movie metadata into the authenticated user media library; plugins never receive ORM objects. |\n| `tasks.background` | Plugin-owned background execution | Allows a plugin to remain active for approved background work; the host still controls process/resource limits. |
| `notifications.send` | `notifications.send` | Creates a user-scoped in-app notification; core then creates eligible provider delivery rows. |
| `notification_providers.register` | `notification_providers.register`, `notification_providers.unregister` | Registers a provider ID namespaced below the plugin ID and one declared action ID. |
| `notification_providers.deliver` | Core invokes the registered action | Allows minimized eligible delivery work after core preference/grant checks. It does not allow querying notification tables or controlling retries. |

Existing families include `users.read`, `users.profile.read`, `games.read`, `games.write`, `media.read`, `media.write`, `events.subscribe`, `plugin.storage`, and `plugin.settings`. `home.replace` and `app.global` are host-owned UI extension slots. A plugin can contribute declarative UI to those slots but cannot mutate Vue components or the DOM. External navigation actions must explicitly declare `external_navigation` and are limited to HTTP(S) URLs. The `api.full` capability bypasses individual method capability matching, but still uses the authenticated gateway and its DTO/error boundaries. It is never implied by a scoped grant.

Only methods present in the gateway dispatch table are callable; presenting a different capability string does not change the method's authorization requirement.

## Errors and action results

Denied grants return 403 at the host boundary. Invalid, missing, or out-of-scope resource identifiers produce bounded validation/not-found errors without disclosing whether another user's resource exists. Plugin actions return structured JSON and a host-generated `request_id` suitable for correlating administrator diagnostics.

One-shot action handlers use the same mediated request/response protocol as long-running plugins. They do not receive host credentials or a direct network connection.
