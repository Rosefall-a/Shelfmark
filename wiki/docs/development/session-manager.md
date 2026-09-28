# Session manager architecture

The session manager extends the existing server-side `UserSession` authentication model. It does not replace local login, OIDC or API-key authentication.

## Session lifecycle

A browser login creates an opaque random token; only its SHA-256 hash is stored. Metadata includes creation time, last-seen time, expiry, IP address, bounded user-agent, optional GeoIP data, network information, anomaly context and revocation time.

Authentication requires an active, non-expired session. Revocation is recorded as state; old expired/revoked records are removed by the bounded retention process.

API keys remain on the bearer-authentication path and are intentionally excluded from session management.

## Authorization

User endpoints scope queries and revocation to the authenticated user. Administrator endpoints require administrator access and permit individual, user-wide and server-wide revocation.

No response contains a raw session token or its hash.

## GeoIP

`src/core/geoip.py` wraps optional local MaxMind DB readers for IPv4 and IPv6. Special ranges are classified before lookup, including loopback, RFC 1918 private IPv4, RFC 6598 CGNAT, IPv6 unique-local and IPv6 link-local.

City, Country and Network/ASN databases are independent. The runtime reads local MMDB files and does not call a remote geolocation service.

## Map

The frontend map uses stored session coordinates and renders an interactive OpenStreetMap slippy map. It supports pan, zoom, clustering and clickable pins. Only visible map tiles are requested, and session IP addresses are not sent to the tile service.

Administrator maps colour individual users and cluster nearby sessions. User maps show that user's mapped active sessions. The map is hidden without usable City data and is an approximate operational visualization.

## Anomaly delivery

A new session can be compared with the user's most recent relevant non-revoked session. A country/region difference records anomaly context and creates a normal notification.

Delivery uses the generic notification-provider/NotificationDelivery infrastructure; existing notification preferences and provider routing still control delivery.

## Persistence

Session metadata is stored in PostgreSQL. GeoIP files under `/data` persist with the application data mount in Docker.

Session migrations use nullable metadata fields so existing sessions remain valid after upgrade.
