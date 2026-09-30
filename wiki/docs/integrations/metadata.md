# Metadata providers

Metadata search and refresh use provider credentials configured under administrator settings or deployment environment variables. The settings API reports whether a credential is configured without returning its secret value.

The application currently has provider-backed flows for games, movies, TV shows, anime, PlayStation/Steam/RetroAchievements library data, and optional profile integrations. Which search results are available depends on the configured provider and its upstream availability.

## Safe operation

- Keep provider client secrets and API keys out of browser storage, screenshots, logs, and the wiki.
- Environment-managed credentials take precedence and should be rotated through deployment tooling.
- Search results are previews; users review data before creating a record.
- Refresh operations respect supported locked fields and user ownership.
- Provider failures are contained and reported rather than granting a fallback access path.

Plugins do not receive provider credentials. A plugin can use only the normalized methods granted through Plugin API v1.
