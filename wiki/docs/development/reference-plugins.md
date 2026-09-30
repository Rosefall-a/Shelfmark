# Reference plugins

The independent [`unnamed_tracking_app_plugins`](https://github.com/Rosefall-a/unnamed_tracking_app_plugins) repository contains packages that consume the public boundary without importing application source.

## Scoped Document Viewer

`example.scoped-document-viewer` contributes a sandboxed Documents sidebar page and requests only `documents.read`. It lists opaque document DTOs and renders browser-native PDF or plain text. Ownership, path confinement, MIME checks, UTF-8 validation, active-content rejection, and the 5 MiB limit remain in the host.

## Self-Service Session Manager

`example.self-service-session-manager` contributes an Account sessions page. It requests `sessions.read` and `sessions.revoke` separately. The host performs confirmation before revocation and scopes both operations to the signed-in user. The plugin never receives credential material.

## External Discord Delivery Provider

`example.discord-delivery-provider` requests provider registration, provider delivery, and private plugin storage. It registers one namespaced provider, stores a webhook through the write-only secret route, and formats eligible delivery work. Core owns user preference checks, retries, deduplication, and audit state.

## Build and install

Run `python tools/build_packages.py`, then verify and validate the resulting `.utp` files with the repository tools. Development artifacts are unsigned and trigger the untrusted-package consent warning. Release CI uses the reviewed private signing identity; private keys are never stored in either repository.

Install through the normal Plugin Manager preview/consent flow. A reference page disappears when its plugin is disabled or removed, and requests fail immediately when the relevant grant is revoked.
