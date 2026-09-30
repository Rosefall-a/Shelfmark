# Games

The game library supports manual records and provider-backed metadata. Use search, filters, collections, lists, bulk edit, and the detail page to organize a library.

## Adding and editing

Create a game from the library, optionally search configured metadata providers, then review the fields before saving. Editing supports title and sort title, platform, status, dates, rating, genres/tags/features, description, time-to-beat data, and artwork. Field-change history records supported metadata changes.

Bulk edit changes selected records only. Locked fields are not overwritten by refresh operations.

## Detail-page data

A game can have:

- achievements and achievement progress;
- screenshots, videos, documents, and other uploaded files;
- notes and checklist items;
- player profiles, linked Wise Old Man statistics, and stat history;
- save, config, mod, and world archives with version history;
- rendered world-map previews for supported archives;
- related variants and collection/list membership.

Uploaded files remain user-scoped. Deleted games, files, screenshots, profiles, and archives move to their corresponding trash views when supported and can be restored until purged or swept by retention policy.

## Documents and plugins

The core file list allows normal downloads. Plugins with an approved `documents.read` grant can receive only safe document DTOs and supported PDF/plain-text content; they never receive host paths. See [Plugins](plugins.md).
