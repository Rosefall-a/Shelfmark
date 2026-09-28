"""Pydantic schemas for scan and metadata import settings."""

# The scan settings API intentionally mirrors adjacent settings schemas.
# pylint: disable=duplicate-code
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# strictly separated — a data provider never contributes art and an image
# provider never contributes data (see search.py's search_game_metadata)
DATA_PROVIDERS = {"Steam", "IGDB", "RetroAchievements", "GiantBomb", "GOG", "HowLongToBeat"}
IMAGE_PROVIDERS = {"SteamGridDB", "ScreenScraper"}

DataProvider = Literal["Steam", "IGDB", "RetroAchievements", "GiantBomb", "GOG", "HowLongToBeat"]
ImageProvider = Literal["SteamGridDB", "ScreenScraper"]


class ScanSettingsUpdate(BaseModel):
    """Partial update — every field optional."""

    provider_order: list[DataProvider] | None = Field(default=None, max_length=6)
    image_provider_order: list[ImageProvider] | None = Field(default=None, max_length=2)
    save_developer: bool | None = None
    save_publisher: bool | None = None
    save_series: bool | None = None
    save_tags: bool | None = None
    save_features: bool | None = None
    save_description: bool | None = None
    save_age_rating: bool | None = None
    save_release_date: bool | None = None
    save_time_to_beat: bool | None = None
    save_key_art: bool | None = None
    save_banner: bool | None = None
    save_logo: bool | None = None
    save_icon: bool | None = None

    @field_validator("provider_order")
    @classmethod
    def validate_provider_order(cls, value: list[str] | None) -> list[str] | None:
        """Validate the configured order of metadata providers."""
        return _validate_order(value, DATA_PROVIDERS)

    @field_validator("image_provider_order")
    @classmethod
    def validate_image_provider_order(cls, value: list[str] | None) -> list[str] | None:
        """Validate the configured order of image providers."""
        return _validate_order(value, IMAGE_PROVIDERS)


def _validate_order(value: list[str] | None, valid: set[str]) -> list[str] | None:
    if value is None:
        return None
    if len(set(value)) != len(value):
        raise ValueError("provider order cannot contain duplicates.")
    if not set(value).issubset(valid):
        raise ValueError(f"provider order values must be a subset of {sorted(valid)}.")
    return value


class ScanSettingsRead(BaseModel):
    """Full representation returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    provider_order: list[str]
    image_provider_order: list[str]
    save_developer: bool
    save_publisher: bool
    save_series: bool
    save_tags: bool
    save_features: bool
    save_description: bool
    save_age_rating: bool
    save_release_date: bool
    save_time_to_beat: bool
    save_key_art: bool
    save_banner: bool
    save_logo: bool
    save_icon: bool
    # {provider name: epoch seconds last used} — read-only, updated by
    # games.py's search_metadata route, not settable via ScanSettingsUpdate
    provider_last_used: dict[str, int]
    created_at: int
    updated_at: int
