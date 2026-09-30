# Environment Variables

The backend configuration registry is the source of truth for application configuration exposed through environment variables. Environment values take precedence over values stored by setup.

The application also reads a small number of deployment/runtime variables directly, and the Docker Compose deployment has its own interpolation variables. They are listed separately below.

## Database

The application accepts either the individual PostgreSQL variables or the legacy `DATABASE_URL` alternative.

| Variable | Source | Default / requirement | Purpose |
|---|---|---|---|
| `POSTGRES_USER` | ENV | Required with `POSTGRES_PASSWORD` and `POSTGRES_DB` | PostgreSQL username. |
| `POSTGRES_PASSWORD` | ENV | Required with `POSTGRES_USER` and `POSTGRES_DB` | PostgreSQL password. |
| `POSTGRES_DB` | ENV | Required with `POSTGRES_USER` and `POSTGRES_DB` | PostgreSQL database name. |
| `POSTGRES_HOST` | ENV | `db` | PostgreSQL host. |
| `POSTGRES_PORT` | ENV | `5432` | PostgreSQL port. |
| `DATABASE_URL` | ENV | Alternative; deprecated | Legacy PostgreSQL connection URL. If the three component variables are complete, they take precedence. |

`DATABASE_URL` is still supported for compatibility. New deployments should use the individual PostgreSQL variables.

## Application

| Variable | Source | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | ENV | Generated/persisted when omitted | Stable Fernet encryption and session-signing key. It is hidden from the setup UI. |
| `AUTH_COOKIE_SECURE` | BOTH | `false` | Makes authentication cookies require HTTPS when enabled. |
| `DEBUG` | BOTH | `false` | Enables backend debug mode. |
| `STARTUP_MODE` | ENV | Empty/default | Selects startup defaults and whether the setup UI is shown. |
| `MAX_UPLOAD_SIZE_MB` | BOTH | `15` | General upload limit in MB. |
| `MAX_SAVE_ARCHIVE_SIZE_MB` | BOTH | `4096` | Game save archive limit in MB. |
| `MAX_CLIP_SIZE_MB` | BOTH | `500` | Clip upload limit in MB. |
| `MAX_WORLD_SAVE_SIZE_MB` | BOTH | `2000` | Game world-save limit in MB. |

### Startup modes

`STARTUP_MODE=dev` or `development` selects development defaults and skips the setup/configuration UI after installation.

`STARTUP_MODE=testing` shows the setup UI and uses testing defaults where defined, otherwise development defaults.

An empty or unrecognized value uses normal defaults and shows the setup UI.

Explicit environment values still take precedence over these mode defaults.

## First administrator

These values are used for environment-based bootstrap of the initial administrator:

| Variable | Source | Purpose |
|---|---|---|
| `PRIMARY_USER_USERNAME` | SETUP/BOTH | Initial administrator username. |
| `PRIMARY_USER_EMAIL` | SETUP/BOTH | Initial administrator email. |
| `PRIMARY_USER_PASSWORD` | SETUP/BOTH | Initial administrator password. |

The normal setup flow can collect these values instead of providing them through the environment.

## Metadata/provider credentials

These registry fields can be supplied through the environment and are deployment-owned when an environment value is present:

| Variable | Purpose |
|---|---|
| `STEAMGRIDDB_API_KEY` | SteamGridDB game artwork/metadata access. |
| `RETROACHIEVEMENTS_API_KEY` | RetroAchievements data access. |
| `GIANTBOMB_API_KEY` | GiantBomb game metadata access. |
| `IGDB_CLIENT_ID` | IGDB client ID. |
| `IGDB_CLIENT_SECRET` | IGDB client secret. |
| `TMDB_API_KEY` | TMDB movie/TV metadata access. |
| `OMDB_API_KEY` | OMDb movie/TV metadata access. |
| `TVDB_API_KEY` | TheTVDB metadata access. |
| `SCREENSCRAPER_DEVID` | ScreenScraper developer ID. |
| `SCREENSCRAPER_DEVPASSWORD` | ScreenScraper developer password. |
| `SCREENSCRAPER_SSID` | ScreenScraper session ID. |
| `SCREENSCRAPER_SSPASSWORD` | ScreenScraper session password. |

## Account & data integrations

These integrations are used for external account connections, user-specific data, libraries, achievements, or importing data rather than general media metadata.

| Variable | Description |
|---|---|
| `XBOX_CLIENT_ID` | Xbox integration client ID. |
| `XBOX_CLIENT_SECRET` | Xbox integration client secret. |
| `GIANTBOMB_API_KEY` | API key used for GiantBomb integration and related game data. |
| `RETROACHIEVEMENTS_API_KEY` | API key used to access RetroAchievements data. |

Secret fields are not returned as plaintext by the setup configuration API.

## OpenID Connect / SSO

| Variable | Default | Purpose |
|---|---|---|
| `OIDC_PROVIDER_NAME` | `Provider 1` | Name of the setup-created provider. |
| `OIDC_PROVIDER_SLUG` | `provider-1` | URL-safe provider identifier used by named-provider routes. |
| `OIDC_ISSUER_URL` | — | OIDC issuer or discovery URL. |
| `OIDC_CLIENT_ID` | — | OIDC client ID. |
| `OIDC_CLIENT_SECRET` | — | OIDC client secret. |
| `OIDC_REDIRECT_URI` | Generated when omitted | Optional deployment-provided callback URI; otherwise the current request is used. |
| `OIDC_SCOPES` | `openid profile email` | Space-separated OIDC scopes. |
| `OIDC_GROUPS_CLAIM` | `groups` | Claim containing group membership. |
| `OIDC_ADMIN_GROUP` | — | Optional group whose members receive administrator access. |
| `OIDC_USER_MATCH_FIELD` | `email` | Match an OIDC identity by `email` or `username`. |
| `OIDC_ALLOW_NEW_USERS` | `true` | Allow unmatched OIDC identities to create local accounts. |
| `OIDC_DEFAULT_LOGIN_METHOD` | `local` | Default login choice: `local` or `sso`. |
| `OIDC_LOGIN_BUTTON_TEXT` | `Continue with SSO` | Text used for the SSO login button. |

OIDC issuer, client ID, and client secret become required when the OIDC section is selected. See [OIDC / SSO](../integrations/oidc.md) for the callback and account-linking behavior.

## Frontend development

The frontend has one documented environment switch outside the backend registry:

| Variable | Purpose |
|---|---|
| `VITE_USE_MOCK_DATA` | When `true`, frontend services use their development/mock behavior instead of normal API-backed behavior. It is consumed by Vite and is not exposed through the backend setup schema. |

Do not add a `VITE_API_BASE_URL` setting unless the frontend code actually introduces one; the current frontend does not define it.

## Runtime variables outside the registry

Two backend runtime variables are read directly rather than being configuration-registry fields:

| Variable | Default | Purpose |
|---|---|---|
| `APP_DATA_DIR` | `/data` | Root directory used for the persistent generated Fernet key. |
| `ENV_FILE` | Searches for `.env` from the current directory upward | Explicit path to the environment file used by the configuration handler. |

## Docker Compose variables

These are Compose interpolation variables from `src/docker-container/compose.yaml`, not additional application configuration fields:

| Variable | Default / requirement | Purpose |
|---|---|---|
| `UNNAMED_TRACKING_APP_VERSION` | `latest` | Published image tag. |
| `UNNAMED_TRACKING_APP_PORT` | `8080` | Host port mapped to the application's container port 80. |
| `POSTGRES_USER` | `unnamed_tracking` in the production Compose file | Database container username. |
| `POSTGRES_DB` | `unnamed_tracking` in the production Compose file | Database container database name. |
| `POSTGRES_PASSWORD` | Required | Database container password. |
| `SECRET_KEY` | Required by the production Compose file | Application encryption/session key. |
| `PRIMARY_USER_USERNAME` | `admin` | Production Compose bootstrap username. |
| `PRIMARY_USER_EMAIL` | `admin@example.invalid` | Production Compose bootstrap email. |
| `PRIMARY_USER_PASSWORD` | Required | Production Compose bootstrap password. |
| `AUTH_COOKIE_SECURE` | `false` | Production Compose cookie security setting. |

The production Compose file builds `DATABASE_URL` from the PostgreSQL variables, so the application receives a complete database URL even though the Compose file does not pass `POSTGRES_HOST` or `POSTGRES_PORT` separately.

## Secrets

Never commit real credentials to `example.env`, the wiki, or source control.

For `SECRET_KEY`, omitting the variable is supported by the backend: a stable Fernet key is generated under `APP_DATA_DIR/config/fernet.key` with redundant copies and recovered on later starts. If you provide a deployment key, preserve it for the lifetime of the installation because existing encrypted values depend on it.
