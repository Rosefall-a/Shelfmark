# Configuration

Unnamed Tracking App uses a backend configuration registry to describe setup fields, defaults, ownership, validation, and visibility.

## Configuration ownership

Each configuration field has an ownership source:

- **ENV** — deployment-owned. An environment value is authoritative and the setup UI treats the field as locked.
- **SETUP** — application-owned. The setup UI can configure and persist the value.
- **BOTH** — the setup UI can configure it, but an environment value takes precedence.

The effective resolution order is:

```
process environment
    ↓
.env
    ↓
persisted application configuration
    ↓
STARTUP_MODE defaults
    ↓
registry defaults
```

This allows a deployment to provide only the environment variables it needs while leaving application-owned settings to the setup UI.

## Setup configuration

The setup page is generated from the backend configuration schema. The frontend does not need a separate hard-coded list of configuration fields.

On first setup:

1. The frontend requests the setup status and configuration schema.
2. The backend resolves environment and persisted values.
3. Required sections are selected automatically.
4. Optional sections such as API keys and OIDC can be selected when needed.
5. Environment-owned fields are populated and locked.
6. The first administrator is created when setup is completed.

After the first administrator exists, setup becomes a configuration editor and configuration changes require an authenticated administrator.

Secrets are never returned to the browser. A configured secret is represented as configured while its actual value remains hidden.

## Environment variables

The complete list of supported environment variables is maintained on the [Environment Variables](environment-variables.md) page.

For a normal deployment, do not copy every variable into your environment. Set only the values you need to override.

## Startup modes

`STARTUP_MODE` controls both startup defaults and whether the setup UI is shown:

- `dev` or `development` — use development defaults and skip the setup/configuration UI after installation.
- `testing` — show the setup UI and use testing-specific defaults where defined, otherwise development defaults.
- Empty or any other value — show the setup UI and use normal defaults.

Explicit environment values take precedence over all startup-mode defaults.

There is no separate `STARTUP_UI` setting.

## SECRET_KEY

`SECRET_KEY` is deployment-owned when supplied through the environment.

If it is omitted, the application generates and persists a stable Fernet key under:

```text
APP_DATA_DIR/config/fernet.key
```

Redundant key copies are maintained so the same key can be recovered after restarts.

Changing or replacing an existing installation's encryption key without preserving the old key can make existing encrypted values unreadable. Treat a manually supplied `SECRET_KEY` as persistent deployment data.

## Adding a configuration variable

When adding a new environment-backed setting:

1. Add the field to the backend configuration registry.
2. Choose its ownership: ENV, SETUP, or BOTH.
3. Define its type, default, validation, and visibility.
4. Add explicit persistence mapping if the setting is application-owned.
5. Add a safe example to `example.env`.
6. Document it on the Environment Variables page.
7. Add focused tests for resolution, validation, and secret handling where applicable.

Do not add normal configuration fields directly to `Setup.vue`. The registry is the source of truth.

## Security rules

- Never return raw secret values from setup/configuration APIs.
- Never allow a request to override an environment-owned field.
- Do not put real credentials in `example.env`.
- Keep first-administrator creation separate from ordinary configuration.
- Keep application-owned secrets encrypted at rest.
