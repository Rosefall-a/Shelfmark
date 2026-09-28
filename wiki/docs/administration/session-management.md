# Administrator session management

Administrators can open **Settings → Session Manager** to inspect browser sessions across users. Raw session tokens and token hashes are never returned.

The administrator view includes:
- affected user;
- active, expired, or revoked state;
- source IP;
- browser/device user-agent;
- creation/login time;
- last activity;
- expiry and revocation;
- approximate location or a special-address classification;
- anomaly reason and previous location.

## Revocation levels

Administrators have three levels of session revocation:
1. **Individual** — use the row's **Revoke** action.
2. **User-wide** — select a user and use **Revoke all for user**.
3. **Server-wide** — use **Revoke all server sessions** to invalidate every active browser session for every user.

Server-wide and user-wide actions require confirmation in the UI. Revocation affects browser sessions only; API keys are not revoked by these actions.

## Search, filtering, and compact tables

The session list can be searched by username, IP, browser/device information, country, or region. It can also be filtered by state, country, selected user, or anomaly status. The **Compact table** control reduces padding and text size so more columns fit on one screen.

## Search and map

The session list can be searched by username, IP, browser/device information, country, or region.

When the City database is configured, the administrator map shows active session locations. Individual users are assigned stable colours for the current view, while nearby sessions are clustered into numbered bubbles. Click a pin or bubble to inspect the session or sessions at that location. Coordinates are approximate and should not be treated as precise physical tracking. If no City database is configured, the map is not rendered.

## GeoIP database

GeoIP is optional. Authentication does not depend on it.

The City database defaults to **/data/GeoIP.mmdb**. Optional Country and Network databases default to **/data/GeoIP-Country.mmdb** and **/data/GeoIP-ASN.mmdb**. The production Docker deployment maps the host **./data** directory to **/data**, so all uploaded databases survive application-container recreation.

### What to upload

Upload **one MaxMind DB binary .mmdb file**, not an archive.

Recommended choices:
- **GeoLite2-City.mmdb** for country, region, city, and coordinate data.
- **GeoIP2-City.mmdb** for a licensed GeoIP2 City deployment.
- **GeoLite2-Country.mmdb** when only country fallback is desired.
- **GeoLite2-ASN.mmdb** when network number and organization information is desired.

Country and Network databases are optional additions to the City database. Country data can fill in country information when the City database has no record, while the Network database adds the autonomous-system number and organization to session details. The Network database does not provide geographic coordinates.

Do **not** upload:
- the ZIP/CSV download archive;
- a CSV database;
- an unrelated or malformed MMDB file;
- a MaxMind license key;
- an account credential file.

### Upload procedure

1. Obtain a current database through the provider's normal download/account process and comply with its licence and attribution requirements.
2. Extract the binary .mmdb file from the downloaded archive.
3. Open **Settings → Session Manager** as an administrator.
4. Confirm that the application data directory is persistent.
5. Choose the matching **City**, **Country**, or **Network** upload control and select the extracted .mmdb file.
6. The application validates the database before replacing the previous file.
7. If validation fails, the previous database remains in place.
8. The matching database status should change to **configured** after a successful upload.

For Docker deployments, keep **./data** on persistent storage. The default files are **./data/GeoIP.mmdb**, **./data/GeoIP-Country.mmdb**, and **./data/GeoIP-ASN.mmdb**. If the corresponding environment path is changed, point it to another persistent location and mount that location into the container.

MaxMind's downloadable GeoLite databases require periodic updating under their applicable terms. Administrators should follow the provider's current licensing and update requirements.

## Special/private addresses

Private addresses are not geolocated and are labelled with the reason where applicable:
- **Loopback** — 127.0.0.0/8 or ::1.
- **RFC 1918 private** — 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16.
- **CGNAT / RFC 6598** — 100.64.0.0/10.
- IPv6 unique-local and link-local addresses are labelled accordingly.

These labels describe the network range; they do not identify a physical location.

## Anomalies

The session manager records a lightweight geographic anomaly when a new session has a different usable country/region from the most recent relevant session. It does not attempt to prove impossible travel or classify an account as compromised.

Administrators can investigate the affected user, session, IP, approximate location, previous location, timestamps, device information, and anomaly context.

Notifications are created only for the affected user and are delivered through the existing notification-provider infrastructure and that user's preferences.

## Persistence and privacy

The PostgreSQL database remains the authoritative store for session metadata. Docker's named PostgreSQL volume persists database records across container recreation.

The GeoIP database is separate file data and is persisted through the application's **/data** volume. Replacing the application container does not remove it unless the persistent data directory/volume is removed.

Session metadata is retained only for the bounded session-data lifecycle. The application does not create an independent indefinite geographic history solely for this feature. IP, user-agent, and location data should be treated as sensitive operational information.