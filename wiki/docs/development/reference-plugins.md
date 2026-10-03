# Reference plugins

The independent [`unnamed_tracking_app_plugins`](https://github.com/Rosefall-a/unnamed_tracking_app_plugins) repository contains packages that consume the public boundary without importing application source.

## Scoped Document Viewer

`example.scoped-document-viewer` contributes a sandboxed Documents sidebar page and requests only `documents.read`. It lists opaque document DTOs and renders browser-native PDF or plain text. Ownership, path confinement, MIME checks, UTF-8 validation, active-content rejection, and the 5 MiB limit remain in the host.

## Self-Service Session Manager

`example.self-service-session-manager` contributes an Account sessions page. It requests `sessions.read` and `sessions.revoke` separately. The host performs confirmation before revocation and scopes both operations to the signed-in user. The plugin never receives credential material.

## Help Button

`example.help-button` demonstrates plugin-owned routes/navigation, the `app.global` extension slot, the Home Hub `home.replace` slot, dialogs, and explicitly declared external navigation.

## Jellyfin Media Sync

`example.jellyfin-media-sync` demonstrates plugin settings, write-only plugin secrets, Jellyfin HTTP API access, media read/import, background synchronization, and event-driven update polling.

## Retired reference plugins

The plugin repository has retired the former UI/API, Playtime Report, Recently Played Notifier, Metadata Curator, Discord Delivery Provider, and UI Playground examples from the current catalogue. Their published packages and release histories remain immutable for audit and historical installation, but they are not current reference implementations and should not be used as examples for new development.

## Build and install

Run `python tools/build_packages.py`, then verify and validate the resulting `.utp` files with the repository tools. Development artifacts are unsigned and trigger the untrusted-package consent warning. Release CI uses the reviewed private signing identity; private keys are never stored in either repository.

Install through the normal Plugin Manager preview/consent flow. A reference page disappears when its plugin is disabled or removed, and requests fail immediately when the relevant grant is revoked.


## Current official reference plugins

The official plugin repository currently maintains four feature demonstrations:

- **Help Button (Totally Not Helpful)** — demonstrates plugin-owned routes/navigation, the `app.global` extension slot, the Home Hub `home.replace` slot, and explicitly declared external navigation.
- **Jellyfin Media Sync** — demonstrates plugin settings, write-only plugin secrets, Jellyfin HTTP API access, media read/import, background synchronization, and cursor-based `game.updated` / `media.added` event polling.
- **Self-Service Session Manager** — implements scoped own/admin sessions and privileged native Settings/maps.
- **Scoped Document Viewer** — implements scoped document APIs and sandboxed PDF/text/Office presentation.

### Full API warning

The `api.full` capability is intentionally separate from all scoped capabilities and is never granted implicitly. **Full API access allows plugins to read and modify all user data. Only enable this for plugins you trust.** Prefer scoped capabilities whenever possible.
