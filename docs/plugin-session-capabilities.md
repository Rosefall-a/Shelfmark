# Scoped session capabilities

These generic APIs expose the session domain from [PR #248](https://github.com/Rosefall-a/unnamed_tracking_app/pull/248), inspected at `5bf43f22bd4991999cd278c5b201817aae439e85`. The official plugin implementation lives in the separate plugins repository. Host code never selects that plugin's ID, page IDs, or Settings section IDs.

| Method | Capability | Scope |
| --- | --- | --- |
| `sessions.list` | `sessions.read` | Authenticated caller's records |
| `sessions.revoke` / `sessions.revoke_all` | `sessions.revoke` | Authenticated caller's records |
| `sessions.admin.list` | `sessions.admin.read` | Active administrator, cross-user |
| `sessions.admin.revoke` / `sessions.admin.revoke_user` / `sessions.admin.revoke_all` | `sessions.admin.revoke` | Active administrator, cross-user |
| `sessions.geoip.status` | `sessions.geoip.read` | Active administrator; City/Country/Network availability |

Live installation grants and healthy enabled state are required before dispatch. The domain additionally checks admin role and applies ownership in SQL. Read and revoke grants do not imply one another. GeoIP leaves are High risk; native frontend authority remains Critical.

Lists accept `q` (200 characters), `country` (128), `state` (`active|expired|revoked`), boolean `anomaly`, integer `limit` (1–200, default 50), UUID `cursor`, and admin-only UUID `user_id`. Self-service cursor anchors must belong to the caller. Replies contain `sessions`, `next_cursor`, and `geoip.city`. Ordering is descending activity then UUID; activity during pagination can move rows, so refresh for a new snapshot.

The additive DTO preserves `id`, `created_at`, `expires_at`, and `active`. It adds user identity (username for admin), IP, bounded user agent, activity/revocation timestamps, state/current indication, location/network classification/ASN/organization, and anomaly reason/previous location. It reuses the source credential-free serializer and validates its public shape. These sensitive metadata require read grants; tokens and hashes never cross the boundary.

Every revoke requires strict `confirmed: true`. Individual session/user IDs must be UUID strings. Writes set `revoked_at`, preserving audit metadata; bulk operations affect all unrevoked records in scope, including expired records, matching source SQL. API keys are separate. Foreign/already revoked IDs fail safely without disclosing ownership.

Action requests add strict boolean `confirmed` (default false). Declared confirmation text is handled in both frontend modes and enforced before backend dispatch. The host overwrites arbitrary `_plugin_context` with authenticated admin status, confirmed state, and cookie-derived current session UUID. Backend route envelopes receive equivalent current session context. Explicit confirmation prevents accidents; a granted plugin can deliberately invoke destructive operations, so it is not an authorization substitute.

## GeoIP configuration transport

`POST /api/plugins/{plugin_id}/capabilities/sessions/geoip` requires administrator authentication, healthy enabled installation, `sessions.geoip.configure`, `confirmed=true`, `kind=city|country|network`, and multipart `file`. The host bounds reads to 256 MiB, validates MMDB through the existing provider, and atomically replaces the selected database. The reply contains configured status/kind, never paths. The reserved `capabilities` root prevents plugin-route conflicts. Any suitably granted plugin can use this transport.

## Shared authentication and notification behavior

Password login now uses the same metadata/anomaly creation as OIDC. Cookie authentication rejects revoked rows and updates activity at most once per minute; logout retains revoked records. Generic frontend authentication refresh detects remote revocation. Native `host.navigate('/login')` refreshes authentication before router guards run.

The existing `session_anomaly` notification flow owns persistence, deduplication, configured providers, delivery/preferences, and retention. Plugins display existing metadata without another anomaly coordinator or duplicate notifications. Missing historical metadata, optional databases, and provider delivery remain core/deployment responsibilities.

## Compatibility

Capability version 1 keeps existing scopes; richer DTO fields are additive and GeoIP grants are new leaves. Destructive callers must explicitly confirm. The official plugin increases to 2.0.0 and requires a coordinated host update. Trust/permission review, signing identities, package format, and completed platform stages 1–4 remain intact. The host does not import or package official plugin source.
