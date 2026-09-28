# Integrations

Unnamed Tracking App can connect to external services for authentication, metadata, game data, account linking, and other supplemental features.

## Available integrations

### OIDC / SSO

Use an OpenID Connect provider to let users sign in with an external identity provider.

- Configure one or more OIDC providers.
- Existing users can be matched by email or username.
- Provider groups can optionally grant administrator access.
- Multiple named providers are supported.

See the [OIDC / SSO guide](oidc.md).

### Playnite

The Playnite integration connects the desktop game launcher with Unnamed Tracking App.

It is intended to synchronize game information and collect launcher-related data such as playtime while keeping the web application as the central source of truth.

See the [Playnite guide](playnite.md).

### AniList

AniList provides anime-list data that can be imported into a user's anime library.

- Imports a user's public AniList anime list.
- The import is read-only with respect to AniList.
- Users can configure the AniList username and import behavior from **Settings → Export/Import → AniList Import**.
- Automatic imports are optional and configured independently for each user.
- Import frequency can use a preset or a custom interval from 1 to 720 hours.

See the [AniList Import guide](../user-guide/anilist.md).

### Metadata providers

Metadata providers enrich games and other media with information such as titles, artwork, descriptions, release information, and related metadata.

Available metadata providers include:

- SteamGridDB
- IGDB
- TMDB
- OMDb
- TVDB
- ScreenScraper

See the [Metadata Providers guide](metadata-providers.md).

### Account & data integrations

These integrations are separate from metadata providers. They can connect to external accounts or services to support importing user-specific data, libraries, achievements, or other account-related information.

Current account and data integrations include:

- Xbox
- GiantBomb
- RetroAchievements

The exact capabilities of each integration depend on the service and the features implemented by Unnamed Tracking App.

## General configuration

Most integrations are configured through environment variables or the application's configuration system.

AniList import is different: its username and scheduling preferences are stored per user in the application preferences and do not require deployment-level AniList credentials.

Before enabling an integration:

1. Check the integration's documentation for required credentials or settings.
2. Add the required values to your deployment environment when applicable.
3. Restart or redeploy the application when required.
4. Verify the integration from the relevant application feature.

For the complete list of deployment configuration variables, see [Environment Variables](../setup/environment-variables.md).

## Security

Treat API keys, client secrets, and other integration credentials as secrets.

- Do not commit real credentials to the repository.
- Do not put real credentials in example configuration files.
- Use HTTPS when exposing authentication integrations publicly.
- For OIDC behind a reverse proxy, make sure the proxy preserves the original host and scheme so generated callback URLs are correct.
