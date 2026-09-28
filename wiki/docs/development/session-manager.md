# Session manager architecture

The session manager extends the existing UserSession authentication model. It does not replace browser cookies, local authentication, OIDC, or API-key authentication.

## Session lifecycle

A browser login creates an opaque cookie and stores only its SHA-256 token hash. Metadata includes:
- creation/login timestamp;
- last-seen timestamp;
- expiry;
- originating IP and bounded user-agent;
- optional City/Country/network GeoIP fields;
- special-address classification;
- anomaly context;
- revocation timestamp.

Authentication checks both expiry and revocation. Last-seen is updated periodically, so database-row existence is not treated as proof that a session is currently active.

Revocation is a state change rather than an immediate delete. A separate retention loop removes old expired/revoked metadata after the bounded retention period.

API keys use the existing UserApiKey model and bearer authentication path and are deliberately excluded from browser-session management.

## Authorization

User routes are always scoped to get_current_user and the authenticated user's ID. Administrator routes use get_current_admin.

User endpoints provide individual and all-account revocation. Administrator endpoints provide individual, user-wide, and server-wide revocation.

No session-management response contains either the raw cookie or token_hash.

## GeoIP abstraction

src/core/geoip.py wraps the optional maxminddb reader. The provider accepts IPv4 and IPv6 and converts missing, malformed, or provider failures into safe unavailable results.

Special ranges are classified before database lookup: loopback, RFC 1918 private IPv4, RFC 6598 CGNAT, IPv6 unique-local, and IPv6 link-local.

The default paths are /data/GeoIP.mmdb for City, /data/GeoIP-Country.mmdb for Country fallback, and /data/GeoIP-ASN.mmdb for network ownership. They are intentionally inside the application's persistent data mount in Docker.

City data supplies coordinates and country/region/city fields; Country data is a fallback for country-only records; network data supplies autonomous-system number and organization. Only MMDB binaries are consumed by the runtime. The web application does not call a remote geolocation service.

## Session map

The frontend map uses latitude/longitude already stored on session records. It is rendered locally without a third-party map tile service.

User views show the user's own mapped active sessions. Administrator views colour individual user locations and cluster nearby sessions into numbered bubbles. Pins are clickable and expose the associated session metadata. Sessions without usable public coordinates are not plotted, and the map is hidden when the City database is unavailable.

The map is an approximate operational visualization, not a precise tracking system. The frontend uses a bundled local SVG map rather than third-party tiles.

## Anomaly notifications

A newly created session is compared with the user's most recent relevant non-revoked session when both have usable country/region information. A country/region transition records anomaly context and creates a normal Notification with kind session_anomaly.

Delivery uses the existing notification-provider registry and NotificationDelivery pipeline from the notification-provider feature branch. There is no second provider contract or notification worker.

Existing user notification preferences and provider routing determine delivery. Duplicate anomaly events are suppressed by the existing notification deduplication mechanism, and notifications are scoped to the affected user.

## Persistence and migration

The session migration adds nullable metadata fields, backfills last_seen_at from created_at, and preserves existing token hashes. The special-network fields are also nullable so older rows remain valid.

There must remain a single Alembic head. Existing sessions remain usable after upgrade even when their new metadata is empty.

In Docker, PostgreSQL data is persisted by the named pgdata volume and file-backed application data, including the GeoIP database, by ./data:/data.

## Privacy

IP, user-agent, and GeoIP values are operationally sensitive. Location is approximate and should not be interpreted as an exact household or physical position.

The feature intentionally does not provide IP blocking, MFA, SIEM capabilities, account-compromise classification, or an indefinite location-history database.