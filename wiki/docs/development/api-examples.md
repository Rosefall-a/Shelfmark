# API Examples

The running application's \`/api/docs\` page is the authoritative API reference. These examples show the authentication and integration patterns currently used by the application.

## API key authentication

Send a user's API key as a bearer token:

\`\`\`http
Authorization: Bearer utk_<secret>
\`\`\`

For example:

\`\`\`bash
curl -H "Authorization: Bearer utk_<secret>" \\
  https://example.com/api/game/list
\`\`\`

API keys are user-scoped.

## Game integration

The Playnite integration currently uses:

\`\`\`http
GET   /api/game/list
POST  /api/game/create
PATCH /api/game/update/{game_id}
POST  /api/game/{game_id}/assets/{asset_kind}
\`\`\`

Use \`/api/docs\` for the exact request and response schemas.

## Library export

An authenticated user can export their current library with:

\`\`\`http
GET /api/export/library
\`\`\`

The response is a JSON snapshot containing games, movies, TV shows and anime for that user.

## Library import

The current generic importer accepts game records:

\`\`\`http
POST /api/import/library
Content-Type: application/json
Authorization: Bearer utk_<secret>
\`\`\`

Imported games are assigned to the authenticated user and existing folder locations are avoided.

## Game save archives

Save archives are authenticated and user-scoped. The two archive kinds are \`save\` and \`world_save\`.

Routes include:

\`\`\`text
/api/game/{game_id}/archives/{kind}
/api/game/{game_id}/archives/{archive_id}/versions
\`\`\`

Archives support named saves, multiple versions, download, soft-delete/trash and restoration.

## OIDC

OIDC login routes are under \`/api/auth/oidc\`. Provider configuration is documented in the [user guide](../user-guide/oidc.md).
