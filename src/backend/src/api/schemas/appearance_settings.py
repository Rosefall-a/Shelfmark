# pylint: disable=duplicate-code,cyclic-import
# pylint: disable=missing-module-docstring,missing-function-docstring
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

BadgeStyle = Literal["none", "glow", "border", "ribbon", "corner_badge"]
BadgePlacement = Literal["top-left", "top-right", "bottom-left", "bottom-right"]

BADGE_STYLES: set[str] = {"none", "glow", "border", "ribbon", "corner_badge"}
BADGE_PLACEMENTS: set[str] = {"top-left", "top-right", "bottom-left", "bottom-right"}


class AppearanceSettingsUpdate(BaseModel):
    """Partial update — every field optional."""

    completion_badge_style: BadgeStyle | None = None
    completion_badge_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    completion_badge_placement: BadgePlacement | None = None

    @field_validator("completion_badge_color")
    @classmethod
    def normalize_color(cls, value: str | None) -> str | None:
        return value.lower() if value else value


class AppearanceSettingsRead(BaseModel):
    """Full representation returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    completion_badge_style: str
    completion_badge_color: str
    completion_badge_placement: str
    completion_badge_image_url: str | None
    created_at: int
    updated_at: int
