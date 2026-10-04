# Metadata Providers

Games are searched on Steam, GOG, IGDB, GiantBomb, RetroAchievements and
HowLongToBeat; SteamGridDB and ScreenScraper add artwork. Movies and TV use
TMDB, OMDb and TVmaze, anime uses AniList. Cover and banner artwork can also be
uploaded by hand.

## Where keys go

Keys can be set in two places:

| Place | Who | Used for |
| --- | --- | --- |
| Settings › Metadata/API | Every user, for themselves | That user's searches and library syncs. |
| Settings › Server Integrations | Administrators | Everyone who hasn't saved their own key. |

A user's own key always wins for that user. The server-wide key is the
fallback; a Server Integrations field that is set in `.env` is locked to the
`.env` value. On Settings › Metadata/API, a provider that
works through the server's key shows **Using server key** rather than **Not
configured**, so the same provider appearing in both places isn't a sign
that they're out of sync.

IGDB, TMDB, OMDb and TVDB are server-wide only.
