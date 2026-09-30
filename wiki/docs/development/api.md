# API

The backend is a FastAPI application and generates its OpenAPI documentation from the running code.

## Interactive documentation

For a running instance, open:

```text
https://<your-host>/api/docs
```

The exact endpoints and request/response schemas shown there are generated from the installed application, so this is the authoritative API reference for that deployment.

## Authentication

The normal web application authenticates with a server-side session cookie.

API clients can also authenticate with a user API key:

```http
Authorization: Bearer utk_<secret>
```

User API keys are created for individual accounts and can be revoked. The backend hashes the key for persistence rather than storing the full secret.

The game API and other authenticated routes resolve the caller from either the bearer API key or the normal session cookie.

## User preferences

User preferences are exposed through the existing preferences API. The AniList automatic-import feature adds these per-user fields:

| Field | Type | Purpose |
| --- | --- | --- |
| `anilist_import_enabled` | boolean | Enables scheduled AniList imports for the user. Defaults to `false`. |
| `anilist_import_username` | string | Public AniList username to import. Empty by default; maximum 100 characters. |
| `anilist_import_interval_minutes` | integer | Minimum 60 minutes and maximum 43,200 minutes (30 days). Defaults to 1,440 minutes (24 hours). |
| `anilist_import_update_existing` | boolean | Allows matching existing titles to be updated from AniList. Defaults to `false`. |
| `anilist_import_last_run_at` | integer or null | Unix timestamp maintained by the scheduler after a scheduled import attempt. Defaults to `null`. |

The preferences are scoped to individual users rather than deployments.

The frontend presents the interval as Hourly, Every 6 hours, Twice daily, Daily, or Weekly, with a custom interval from 1 to 720 hours.

## Playnite API surface

The Playnite extension currently uses these authenticated endpoints:

- `GET /api/game/list`
- `POST /api/game/create`
- `PATCH /api/game/update/{game_id}`
- `POST /api/game/{game_id}/assets/{asset_kind}`

See [Playnite](../integrations/playnite.md) for the integration-specific behavior.

## OIDC API surface

The OIDC login flow is exposed under `/api/auth/oidc`:

- `GET /api/auth/oidc/status` — reports whether OIDC is available and the login providers exposed on the login page.
- `GET /api/auth/oidc/login` — starts the default OIDC login.
- `GET /api/auth/oidc/login/{provider_slug}` — starts a named provider when its autostart policy permits it.
- `GET /api/auth/oidc/callback` — receives the default provider callback.
- `GET /api/auth/oidc/callback/{provider_slug}` — receives a named-provider callback.

OIDC callback handling creates or links a local account and then creates the application's normal session.

## Configuration API

The setup/configuration API is generated from the backend configuration registry. It is used by the generic setup UI and by the post-install configuration editor.

The configuration schema deliberately masks secret values. Environment-owned fields are reported as locked rather than allowing the browser to override deployment configuration.

For the configuration model and environment precedence, see [Configuration](../setup/configuration.md).

## API changes

When changing an API route:

1. Update its Pydantic request/response models where needed.
2. Keep authentication and user scoping explicit.
3. Add or update backend tests.
4. Verify the generated `/api/docs` output.
5. Update integration documentation when a documented client such as Playnite depends on the contract.
