# Playnite

Unnamed Tracking App has a Playnite 10 extension for synchronizing a Playnite library with the authenticated user's game library.

The extension repository is **UnnamedTrackingPlaynite**. The integration uses the application's normal user API-key authentication rather than a separate Playnite-specific credential system.

## Requirements

The current extension targets:

- Windows;
- Playnite 10.x;
- .NET Framework 4.6.2 / the Playnite 10 SDK;
- an Unnamed Tracking user API key beginning with `utk_`.

## Configure the extension

1. Install the extension package, or load the Release output through Playnite's developer extension support while developing.
2. Open **Add-ons → Extension settings → Unnamed Tracking**.
3. Enter the base URL of the Unnamed Tracking server.
4. Generate a user API key in Unnamed Tracking and enter it in the extension.
5. Use **Test connection**.
6. Use **Upload Playnite Library** for the initial synchronization.
7. Optionally configure the ignore tag, startup synchronization, and game-stopped synchronization.

The API key is stored in Playnite's extension settings. Treat the Playnite profile and extension settings as sensitive configuration.

## Authentication

User API keys are created from the application's API-key settings. They use the `utk_` prefix.

Authenticated API requests use:

```http
Authorization: Bearer utk_<secret>
```

The backend accepts these bearer keys alongside normal browser session authentication. The API key is associated with the user who created it, so Playnite operations run against that user's library.

## Library synchronization

The extension reads the Playnite library and synchronizes game metadata and state.

It can create new games and update existing games. The synchronized Playnite data includes:

- title and sort title;
- description;
- release date;
- developer and publisher;
- series;
- tags and features;
- links and source;
- age rating;
- favourite state;
- notes;
- playtime;
- rating;
- completion status.

Cover and banner artwork can also be uploaded.

The application has a `playnite_guid` field on games. It is an optional UUID association and is indexed, but it is deliberately not globally unique because the same account can receive imports from multiple Playnite libraries.

### Matching

The extension first uses its generated `folder_location` association and then falls back to `playnite_guid`. This lets the extension retain the association when a Playnite title is renamed without creating an unnecessary duplicate.

If a game already exists, the extension updates it through the game's update endpoint. Otherwise it creates the game first and then uploads available artwork.

## Supported API contract

The extension currently uses these authenticated application endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/game/list` | Read the user's game library |
| POST | `/api/game/create` | Create a game |
| PATCH | `/api/game/update/{game_id}` | Update an existing game |
| POST | `/api/game/{game_id}/assets/{asset_kind}` | Upload game artwork |

The application requires authentication for the game API and scopes game lookups to the authenticated user.

## Ignoring games

The extension can skip games carrying its configured ignore tag. The default tag is:

```text
trackingapp_ignore
```

The comparison is case-insensitive. Clearing the setting disables the tag filter.

## Automatic synchronization

The extension can optionally:

- synchronize the whole library when Playnite starts;
- update an already-linked game when a game stops.

Game-stopped synchronization does not create missing games. Run a library synchronization first if the game is not already linked.

Manual synchronization reports progress and can be cancelled. Cancellation stops additional game operations after the current network operation completes.

## Save synchronization

Save synchronization is implemented by the Playnite extension and is keyed to the Playnite game GUID.

For a configured game, the extension can:

- configure one or more local save folders;
- upload a save immediately;
- download the latest cloud save;
- enable download-on-start;
- enable upload-on-stop.

Windows environment variables such as `%USERPROFILE%` can be used in configured paths. Before replacing local files with a cloud download, the extension creates a timestamped local backup.

Save synchronization is separate from the normal game metadata synchronization described above.

## Embedded application view

The extension also provides an **Unnamed Tracking** sidebar view for opening the configured server UI inside Playnite.

The API key is not put into the page URL or browser storage. The embedded web UI uses the application's normal session authentication, so it may require a normal web login even though background Playnite synchronization continues to use the configured API key.

## Troubleshooting

### Test connection fails

Check that the server URL is correct and that the API key:

- begins with `utk_`;
- has not been revoked;
- belongs to the account whose library you want to synchronize.

### A game is duplicated

Run the current synchronization again and check that the Playnite GUID and generated folder association are being sent. The extension uses those associations to match existing games.

### Artwork fails but game synchronization succeeds

Artwork uploads are treated as per-game warnings by the extension. Check the Playnite extension log for the individual artwork request and response.

### Synchronization is slow

Initial synchronization is per-game and can upload cover and banner artwork. Use **Preview sync** before a large upload and **Cancel** if a manual synchronization needs to stop.
