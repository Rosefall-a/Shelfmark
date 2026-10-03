# Session management

The **Settings → Sessions** page shows browser sessions belonging to the signed-in account. API keys are a separate authentication mechanism and are never shown as browser sessions.

Each session can show:

- current/active/expired/revoked state;
- originating IP address;
- browser/device user-agent;
- creation/login time;
- last activity;
- expiry;
- approximate GeoIP country/region/city when available;
- a geographic anomaly explanation when one was detected.

Raw browser cookies and their stored hashes are never returned by the session-management API.

## Revoking sessions

Use **Revoke** on an individual active session to end that browser session.

Use **Revoke all sessions** to revoke every active browser session belonging to the account. This includes the current browser session, so use it when you intentionally want to sign out everywhere. The current session is otherwise identified separately and is not individually revoked by the normal session button.

Revocation is different from expiry:

- **Active** means the session is not revoked and has not expired.
- **Expired** means its expiry time has passed.
- **Revoked** means the application explicitly invalidated it.

Revoked and expired records can remain visible for the retention period so that their state is understandable; this does not make them usable credentials.

## Session map

When the City GeoIP database is configured, the Sessions page includes a world map containing approximate positions for active sessions with usable coordinates. If no City database is configured, the map is not rendered. The map does not make private/local addresses into physical locations.

Nearby sessions are clustered into numbered bubbles. Click a pin or bubble to see the associated session or sessions. The map is intentionally approximate and is not suitable for identifying a household or exact physical location.

## Location information

GeoIP is optional. The application continues to authenticate normally when no database is configured.

Special addresses are described rather than called “unavailable”:

- **Loopback** — for example, 127.0.0.0/8 or ::1.
- **RFC 1918 private address** — 10.0.0.0/8, 172.16.0.0/12, or 192.168.0.0/16.
- **CGNAT / RFC 6598** — 100.64.0.0/10.
- IPv6 unique-local and link-local addresses are also labelled as such.

Public addresses may have country, region, city, and map coordinates depending on the configured database. An optional Network database can also add the autonomous-system number and organization.

## Notifications

A newly created session can produce a **session anomaly** notification when the available country/region differs from the user's most recent relevant session. Existing notification preferences and provider routing determine delivery.

A geographic anomaly is evidence worth checking, not proof of account compromise. VPNs, mobile networks, corporate gateways, ISP routing, database changes, and other factors can make IP geolocation inaccurate.

## Privacy and retention

IP addresses, user-agents, and location metadata are operationally sensitive. The application stores location metadata on the session rather than building an independent indefinite location-history database.

Expired/revoked session metadata is periodically removed after a bounded retention period. Administrators should preserve only the data needed for their operational and privacy requirements.

The map uses data already stored on sessions for markers, while the visible basemap is loaded interactively from OpenStreetMap tiles. It supports mouse/touch panning and zooming and requests only the tiles needed for the current view. The basemap is subject to OpenStreetMap tile-service availability and usage policy. The application does not send session IP addresses to the map service; only map tile requests are made.
