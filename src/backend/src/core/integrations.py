# pylint: disable=missing-class-docstring,missing-function-docstring
"""The metadata provider keys in effect, from whichever place holds them.

A key entered in Settings (stored encrypted in the database) wins; if there
is none, the server's environment is used (IGDB_CLIENT_ID, IGDB_CLIENT_SECRET,
TMDB_API_KEY, OMDB_API_KEY, TVDB_API_KEY). That lets a deploy be configured
from its compose file while the Settings screen still works and overrides it.
Nothing is shipped with the app: with neither set, the provider is off."""

from dataclasses import dataclass
from typing import Literal

from src.core.config import settings
from src.core.crypto import decrypt_secret
from src.database.models.app_integration_settings import AppIntegrationSettings

Source = Literal["database", "environment"]

_ENV = {
    "igdb_client_id": settings.IGDB_CLIENT_ID,
    "igdb_client_secret": settings.IGDB_CLIENT_SECRET,
    "tmdb_api_key": settings.TMDB_API_KEY,
    "omdb_api_key": settings.OMDB_API_KEY,
    "tvdb_api_key": settings.TVDB_API_KEY,
}
_ENCRYPTED = ("igdb_client_secret", "tmdb_api_key", "omdb_api_key", "tvdb_api_key")


@dataclass(frozen=True)
class Integrations:
    igdb_client_id: str | None
    igdb_client_secret: str | None
    tmdb_api_key: str | None
    omdb_api_key: str | None
    tvdb_api_key: str | None
    sources: dict[str, Source]

    @property
    def igdb_configured(self) -> bool:
        return bool(self.igdb_client_id and self.igdb_client_secret)


def resolve_integrations(row: AppIntegrationSettings) -> Integrations:
    values: dict[str, str | None] = {}
    sources: dict[str, Source] = {}
    for name, from_env in _ENV.items():
        stored = getattr(row, name)
        if stored:
            values[name] = decrypt_secret(stored) if name in _ENCRYPTED else stored
            sources[name] = "database"
        elif from_env:
            values[name] = from_env
            sources[name] = "environment"
        else:
            values[name] = None
    return Integrations(sources=sources, **values)
