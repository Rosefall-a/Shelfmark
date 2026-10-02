# Remote Plugin Manager API

The backend provides instance-local groundwork for an external control plane;
this repository does not provide a central website.

## Credentials

An authenticated administrator creates a token with
`POST /api/plugins/management/tokens`, supplying a name and a nonempty scope list.
The response returns its ID and token once. Tokens start with `utpm_`; only their
SHA-256 hash is stored. Revoke with
`DELETE /api/plugins/management/tokens/{token_id}`. The owner must remain an active
administrator. Credential issuance/revocation requires normal admin authentication.

Send `Authorization: Bearer <token>` over HTTPS to an intentionally exposed
instance. Management tokens cannot authenticate unrelated application APIs,
plugin-provided pages/actions/routes or scoped-client credential creation.
A simultaneous browser session does not widen token access.

| Scope | Access |
| --- | --- |
| `plugins.read` | Installed inventory, catalogues, manager settings, runtime capabilities, manager logs/changelog and grant/request inventory |
| `plugins.install` | Upload/URL/catalogue install preview and commit |
| `plugins.update` | Update checks/previews/commit/staged review, reinstall, rollback, retained package deletion, update policy and catalogue configuration |
| `plugins.lifecycle` | Start, stop, enable, disable, retry and uninstall |
| `plugins.permissions` | Active-package scope preview/re-grant, request approval/denial and grant revocation |

Permission risk/trust checks still apply. Tokens cannot bypass untrusted
privileged consent, password reauthentication, dependencies or package validation.

## Operations

`GET /api/plugins` returns authoritative installed metadata, retaining inventory
when runtime observations are unavailable. `GET /api/plugins/runtime/health` reports
the runtime capability probe. `GET/PUT /api/plugins/manager-settings` reads/changes
global automatic installation and package-retention count. Per-plugin overrides
use `PUT /api/plugins/{plugin_id}/auto-update` with mode `follow`, `enabled` or `disabled`.

`POST /api/plugins/updates/check` discovers releases. Existing upload and URL
preview/update routes use the canonical installer. Preview a staged archive with
`POST /api/plugins/{plugin_id}/update/staged/preview`; activate with
`POST /api/plugins/{plugin_id}/update/staged` and explicit consent. A confirmed
empty permission decision denies the staged update while retaining the active release.

Lifecycle POST paths end in `/start`, `/stop`, `/enable` and `/disable`.
`/{plugin_id}/reinstall` accepts `purge: true` only with `confirmed: true`.
`/{plugin_id}/rollback` accepts a retained history ID or selects the most recent
predecessor. Deleting `/{plugin_id}/history/{history_id}` removes only that package.
Deleting `/api/plugins/{plugin_id}` uninstalls and purges plugin-owned state.

`POST /api/plugins/{plugin_id}/permissions/grant` grants selected keys declared
by the active package, including previously revoked keys. Revoke through
`/api/plugin-permissions/grants/{grant_id}/revoke`. The OpenAPI document specifies
request shapes and status codes. See [Lifecycle](plugin-lifecycle.md) and
[Permissions](plugin-permissions.md).
