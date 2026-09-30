"""Declarative application configuration metadata.

The registry is intentionally the single source of truth for configuration
that can be presented by the setup/settings UI. The frontend receives sections,
field types, labels, defaults, requirements, and source ownership from here.

Runtime resolution is handled by EnvConfigHandler. Database persistence is
described by the storage attribute and is applied by setup/settings routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConfigSource(str, Enum):
    ENV = "env"
    SETUP = "setup"
    BOTH = "both"


class DefaultMode(str, Enum):
    DEFAULT = "default"
    DEVELOPMENT = "development"
    TESTING = "testing"


@dataclass(frozen=True)
class ConfigSectionSpec:
    id: str
    title: str
    description: str
    order: int
    required: bool = False
    default: bool = False
    removable: bool = True
    visible: bool = True
    # Optional navigation/menu grouping. Multiple sections may share one menu
    # identifier, allowing future multi-screen menus without changing the registry shape.
    menu: str | None = None


@dataclass(frozen=True)
class ConfigSpec:
    name: str
    section: str = "general"
    source: ConfigSource = ConfigSource.BOTH
    input_type: str = "text"
    label: str = ""
    heading: str = ""
    description: str = ""
    hint: str = ""
    placeholder: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    default: Any = None
    development_default: Any = None
    testing_default: Any = None
    required: bool = False
    required_group: str | None = None
    secret: bool = False
    generated: bool = False
    deprecated: bool = False
    deprecated_message: str = "This setting is deprecated and will be removed in a future release."
    # visible controls whether the field appears in generated UI.
    # It is deliberately separate from source ownership: an ENV-owned boolean
    # can be visible/read-only, while a sensitive deployment field can be hidden entirely.
    visible: bool = True
    storage: str | None = None


CONFIG_SECTIONS: tuple[ConfigSectionSpec, ...] = (
    ConfigSectionSpec(
        "database",
        "Database",
        "Deployment-owned PostgreSQL connection settings.",
        1000,
        required=True,
        removable=False,
        visible=False,
    ),
    ConfigSectionSpec(
        "first_admin",
        "First administrator",
        "Create the first local administrator. Environment-provided bootstrap values can complete this section automatically.",
        10,
        required=True,
        removable=False,
    ),
    ConfigSectionSpec(
        "general",
        "General",
        "Optional deployment-wide metadata and integration credentials.",
        20,
        required=False,
        removable=False,
        default=True,
    ),
    ConfigSectionSpec(
        "api_keys",
        "API keys",
        "Optional deployment-wide metadata and integration credentials.",
        30,
    ),
    ConfigSectionSpec(
        "oidc",
        "OpenID Connect / SSO",
        "Optional SSO configuration. Selecting this section enables OIDC once its provider credentials are saved.",
        40,
    ),
)

# Add a field here first when introducing a new deployment/setup variable.
# docs/CONFIGURATION.md contains the complete workflow for wiring that variable
# through resolution, validation, persistence, and the generated UI.
CONFIG_REGISTRY: tuple[ConfigSpec, ...] = (
    ConfigSpec(
        "POSTGRES_USER",
        "database",
        ConfigSource.ENV,
        label="PostgreSQL user",
        required=True,
        required_group="database:postgres",
        visible=False,
    ),
    ConfigSpec(
        "POSTGRES_PASSWORD",
        "database",
        ConfigSource.ENV,
        label="PostgreSQL password",
        input_type="secret",
        required=True,
        required_group="database:postgres",
        secret=True,
        visible=False,
    ),
    ConfigSpec(
        "POSTGRES_DB",
        "database",
        ConfigSource.ENV,
        label="PostgreSQL database",
        required=True,
        required_group="database:postgres",
        visible=False,
    ),
    ConfigSpec(
        "POSTGRES_HOST",
        "database",
        ConfigSource.ENV,
        label="PostgreSQL host",
        default="db",
        visible=False,
    ),
    ConfigSpec(
        "POSTGRES_PORT",
        "database",
        ConfigSource.ENV,
        label="PostgreSQL port",
        input_type="integer",
        default=5432,
        visible=False,
    ),
    ConfigSpec(
        "DATABASE_URL",
        "database",
        ConfigSource.ENV,
        label="Legacy database URL",
        deprecated=True,
        description="Legacy compatibility setting; prefer the individual PostgreSQL variables.",
        deprecated_message="DATABASE_URL is deprecated; use POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB instead.",
        required_group="database:url",
        visible=False,
    ),
    ConfigSpec(
        "SECRET_KEY",
        "general",
        ConfigSource.ENV,
        label="Secret key",
        input_type="secret",
        secret=True,
        generated=True,
        visible=False,
        description="Stable Fernet/session signing key; generated and persisted when omitted.",
    ),
    ConfigSpec(
        "AUTH_COOKIE_SECURE",
        "general",
        ConfigSource.BOTH,
        label="Secure authentication cookies",
        input_type="boolean",
        default=False,
        description="Use secure cookies when the application is served over HTTPS.",
    ),
    ConfigSpec(
        "DEBUG",
        "general",
        ConfigSource.BOTH,
        label="Debug mode",
        input_type="boolean",
        default=False,
        development_default=True,
        heading="Debug mode",
    ),
    ConfigSpec(
        "PRIMARY_USER_USERNAME",
        "first_admin",
        label="Username",
        required=True,
        default="admin",
        development_default="admin",
        storage="bootstrap",
    ),
    ConfigSpec(
        "PRIMARY_USER_EMAIL",
        "first_admin",
        label="Email",
        input_type="email",
        required=True,
        default="admin@localhost",
        development_default="admin@localhost",
        storage="bootstrap",
    ),
    ConfigSpec(
        "PRIMARY_USER_PASSWORD",
        "first_admin",
        label="Password",
        input_type="secret",
        required=True,
        secret=True,
        development_default="Change-this-during-setup",
        storage="bootstrap",
    ),
    ConfigSpec(
        "STEAMGRIDDB_API_KEY",
        "api_keys",
        label="SteamGridDB API key",
        input_type="secret",
        secret=True,
        storage="app_integration",
    ),
    ConfigSpec(
        "RETROACHIEVEMENTS_API_KEY",
        "api_keys",
        label="RetroAchievements API key",
        input_type="secret",
        secret=True,
        storage="app_integration",
    ),
    ConfigSpec(
        "GIANTBOMB_API_KEY",
        "api_keys",
        label="GiantBomb API key",
        input_type="secret",
        secret=True,
        visible=False,
        storage="app_integration",
    ),
    ConfigSpec("IGDB_CLIENT_ID", "api_keys", label="IGDB client ID", storage="app_integration"),
    ConfigSpec(
        "IGDB_CLIENT_SECRET",
        "api_keys",
        label="IGDB client secret",
        input_type="secret",
        secret=True,
        visible=False,
        storage="app_integration",
    ),
    ConfigSpec(
        "TMDB_API_KEY",
        "api_keys",
        label="TMDB API key",
        input_type="secret",
        secret=True,
        visible=False,
        storage="app_integration",
    ),
    ConfigSpec(
        "OMDB_API_KEY",
        "api_keys",
        label="OMDB API key",
        input_type="secret",
        secret=True,
        visible=False,
        storage="app_integration",
    ),
    ConfigSpec(
        "TVDB_API_KEY",
        "api_keys",
        label="TVDB API key",
        input_type="secret",
        secret=True,
        visible=False,
        storage="app_integration",
    ),
    ConfigSpec(
        "SCREENSCRAPER_DEVID",
        "api_keys",
        label="ScreenScraper developer ID",
        storage="app_integration",
    ),
    ConfigSpec(
        "SCREENSCRAPER_DEVPASSWORD",
        "api_keys",
        label="ScreenScraper developer password",
        input_type="secret",
        secret=True,
        visible=False,
        storage="app_integration",
    ),
    ConfigSpec(
        "SCREENSCRAPER_SSID",
        "api_keys",
        label="ScreenScraper session ID",
        storage="app_integration",
    ),
    ConfigSpec(
        "SCREENSCRAPER_SSPASSWORD",
        "api_keys",
        label="ScreenScraper session password",
        input_type="secret",
        secret=True,
        visible=False,
        storage="app_integration",
    ),
    ConfigSpec("XBOX_CLIENT_ID", "api_keys", label="Xbox client ID", storage="app_integration"),
    ConfigSpec(
        "XBOX_CLIENT_SECRET",
        "api_keys",
        label="Xbox client secret",
        input_type="secret",
        secret=True,
        visible=False,
        storage="app_integration",
    ),
    ConfigSpec(
        "OIDC_PROVIDER_NAME",
        "oidc",
        label="Provider name",
        input_type="text",
        default="Provider 1",
        storage="oidc",
        required=True,
    ),
    ConfigSpec(
        "OIDC_PROVIDER_SLUG",
        "oidc",
        label="Provider slug",
        input_type="text",
        default="provider-1",
        storage="oidc",
        required=True,
    ),
    ConfigSpec(
        "OIDC_ISSUER_URL",
        "oidc",
        label="Issuer / discovery URL",
        input_type="url",
        placeholder="https://login.example.com/realms/archive",
        required=True,
        storage="oidc",
    ),
    ConfigSpec("OIDC_CLIENT_ID", "oidc", label="Client ID", required=True, storage="oidc"),
    ConfigSpec(
        "OIDC_CLIENT_SECRET",
        "oidc",
        label="Client secret",
        input_type="secret",
        secret=True,
        required=True,
        storage="oidc",
    ),
    ConfigSpec(
        "OIDC_REDIRECT_URI",
        "oidc",
        label="Redirect URI",
        input_type="url",
        generated=True,
        visible=True,
        description="Automatically generated from the address currently used to access the application.",
        storage="oidc",
    ),
    ConfigSpec(
        "OIDC_SCOPES",
        "oidc",
        label="Scopes",
        default="openid profile email",
        hint="Space-separated OIDC scopes.",
        storage="oidc",
    ),
    ConfigSpec("OIDC_GROUPS_CLAIM", "oidc", label="Groups claim", default="groups", storage="oidc"),
    ConfigSpec("OIDC_ADMIN_GROUP", "oidc", label="Admin group", storage="oidc"),
    ConfigSpec(
        "OIDC_USER_MATCH_FIELD",
        "oidc",
        label="Match users by",
        input_type="choice",
        choices=(("email", "Email"), ("username", "Username")),
        default="email",
        storage="oidc",
    ),
    ConfigSpec(
        "OIDC_ALLOW_NEW_USERS",
        "oidc",
        label="Allow new users",
        input_type="boolean",
        default=True,
        storage="oidc",
    ),
    ConfigSpec(
        "OIDC_DEFAULT_LOGIN_METHOD",
        "oidc",
        label="Default login method",
        input_type="choice",
        choices=(("local", "Local username & password"), ("sso", "SSO")),
        default="local",
        storage="oidc",
    ),
    ConfigSpec(
        "OIDC_LOGIN_BUTTON_TEXT",
        "oidc",
        label="Login button text",
        default="Continue with SSO",
        storage="oidc",
    ),
    ConfigSpec(
        "STARTUP_MODE",
        "general",
        ConfigSource.ENV,
        label="Startup mode",
        default="",
        description="Optional profile: development, testing, or empty/default.",
        visible=False,
    ),
    ConfigSpec(
        "MAX_UPLOAD_SIZE_MB",
        "general",
        ConfigSource.BOTH,
        label="Maximum upload size (MB)",
        input_type="integer",
        heading="Max sizes",
        default=15,
    ),
    ConfigSpec(
        "MAX_SAVE_ARCHIVE_SIZE_MB",
        "general",
        ConfigSource.BOTH,
        label="Maximum save archive size (MB)",
        input_type="integer",
        heading="Max sizes",
        default=4096,
    ),
    ConfigSpec(
        "MAX_CLIP_SIZE_MB",
        "general",
        ConfigSource.BOTH,
        label="Maximum clip size (MB)",
        input_type="integer",
        heading="Max sizes",
        default=500,
    ),
    ConfigSpec(
        "MAX_WORLD_SAVE_SIZE_MB",
        "general",
        ConfigSource.BOTH,
        label="Maximum world save size (MB)",
        input_type="integer",
        heading="Max sizes",
        default=2000,
    ),
    ConfigSpec(
        "VITE_USE_MOCK_DATA",
        "general",
        ConfigSource.ENV,
        label="Frontend mock data",
        input_type="boolean",
        default=False,
        visible=False,
        description="Early-stage frontend development/testing switch; never exposed through the backend setup schema.",
    ),
)


def get_config_spec(name: str) -> ConfigSpec:
    for spec in CONFIG_REGISTRY:
        if spec.name == name:
            return spec
    raise KeyError(name)


def get_config_section(section_id: str) -> ConfigSectionSpec:
    for section in CONFIG_SECTIONS:
        if section.id == section_id:
            return section
    raise KeyError(section_id)
