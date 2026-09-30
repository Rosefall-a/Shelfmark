"""Application configuration resolved through the central configuration handler."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.config_registry import CONFIG_REGISTRY
from src.core.env_handler import EnvConfigHandler


class Settings(BaseSettings):
    """Runtime settings; source and default policy live in EnvConfigHandler."""

    DATABASE_URL: str = ""
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: str | None = None
    POSTGRES_DB: str | None = None
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    STEAMGRIDDB_API_KEY: str | None = None
    RETROACHIEVEMENTS_API_KEY: str | None = None
    GIANTBOMB_API_KEY: str | None = None
    PRIMARY_USER_USERNAME: str = ""
    PRIMARY_USER_EMAIL: str = ""
    PRIMARY_USER_PASSWORD: str = ""

    AUTH_COOKIE_SECURE: bool = False
    DEBUG: bool = False
    SECRET_KEY: str = ""
    STARTUP_MODE: str = ""
    MAX_UPLOAD_SIZE_MB: int = 15
    MAX_SAVE_ARCHIVE_SIZE_MB: int = 4096
    MAX_CLIP_SIZE_MB: int = 500
    MAX_WORLD_SAVE_SIZE_MB: int = 2000

    IGDB_CLIENT_ID: str | None = None
    IGDB_CLIENT_SECRET: str | None = None
    TMDB_API_KEY: str | None = None
    OMDB_API_KEY: str | None = None
    TVDB_API_KEY: str | None = None
    XBOX_CLIENT_ID: str | None = None
    XBOX_CLIENT_SECRET: str | None = None
    SCREENSCRAPER_DEVID: str | None = None
    SCREENSCRAPER_DEVPASSWORD: str | None = None
    SCREENSCRAPER_SSID: str | None = None
    SCREENSCRAPER_SSPASSWORD: str | None = None

    OIDC_ISSUER_URL: str | None = None
    OIDC_CLIENT_ID: str | None = None
    OIDC_CLIENT_SECRET: str | None = None
    OIDC_REDIRECT_URI: str | None = None
    OIDC_SCOPES: str = "openid profile email"
    OIDC_GROUPS_CLAIM: str = "groups"
    OIDC_ADMIN_GROUP: str | None = None
    OIDC_USER_MATCH_FIELD: str = "email"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def resolve_database(self) -> "Settings":
        components = {
            "POSTGRES_USER": self.POSTGRES_USER,
            "POSTGRES_PASSWORD": self.POSTGRES_PASSWORD,
            "POSTGRES_DB": self.POSTGRES_DB,
        }
        present = [bool(value and str(value).strip()) for value in components.values()]

        if all(present):
            self.DATABASE_URL = (
                "postgresql+psycopg://"
                f"{quote_plus(str(self.POSTGRES_USER))}:"
                f"{quote_plus(str(self.POSTGRES_PASSWORD))}@"
                f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/"
                f"{quote_plus(str(self.POSTGRES_DB))}"
            )
            return self

        # DATABASE_URL is an alternative to the component form. If both are
        # supplied, the explicit component set remains authoritative when it
        # is complete; a partial component set must not make an otherwise
        # valid DATABASE_URL deployment fail.
        if self.DATABASE_URL.strip():
            # Compatibility for existing deployments. New deployments should use
            # POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB instead.
            url = self.DATABASE_URL.strip()
            if url.startswith("postgres://"):
                url = "postgresql+psycopg://" + url.removeprefix("postgres://")
            elif url.startswith("postgresql://"):
                url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
            self.DATABASE_URL = url
            return self

        raise ValueError(
            "Database configuration is required. Set POSTGRES_USER, "
            "POSTGRES_PASSWORD, and POSTGRES_DB."
        )


logger = logging.getLogger(__name__)

_handler = EnvConfigHandler()
for _spec in CONFIG_REGISTRY:
    if _spec.deprecated and _handler.has(_spec.name):
        logger.warning("%s", _spec.deprecated_message)

_settings_values = {
    spec.name: _handler.get(spec.name)
    for spec in CONFIG_REGISTRY
    if spec.name != "VITE_USE_MOCK_DATA" and _handler.get(spec.name) is not None
}
settings = Settings(**_settings_values)  # type: ignore[call-arg]
if not settings.SECRET_KEY:
    settings.SECRET_KEY = _handler.resolved()["SECRET_KEY"]
