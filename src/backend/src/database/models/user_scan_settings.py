# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base

# default ordering is "best of category first" — IGDB and GiantBomb are the
# broadest, most consistently populated general databases; GOG's public
# catalog is also solid and needs no key; Steam is accurate but
# store-page-only; RetroAchievements is excellent but retro-only;
# HowLongToBeat contributes a single field, so it's least useful to check
# first. SteamGridDB's library and curation (community-rated, purpose-built
# for cover art) beats ScreenScraper's narrower retro-focused art.
DEFAULT_PROVIDER_ORDER = ["IGDB", "GiantBomb", "GOG", "Steam", "RetroAchievements", "HowLongToBeat"]
DEFAULT_IMAGE_PROVIDER_ORDER = ["SteamGridDB", "ScreenScraper"]


class UserScanSettings(Base):
    """Per-user metadata search preferences — provider priority and which
    fields a search result is allowed to save. One row per user."""

    __tablename__ = "user_scan_settings"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider_order: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: list(DEFAULT_PROVIDER_ORDER)
    )
    # separate priority order for the image/art layer — SteamGridDB and
    # ScreenScraper can both contribute the same art fields, so this decides
    # which one wins, independent of the data-field provider_order above
    image_provider_order: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: list(DEFAULT_IMAGE_PROVIDER_ORDER)
    )
    save_developer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_publisher: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_series: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_tags: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_features: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_description: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_age_rating: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_release_date: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_time_to_beat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_key_art: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_banner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_logo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    save_icon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # {provider name: epoch seconds} — last time that provider actually
    # returned a result during a search (games.py's search_metadata route
    # updates this after each call), so Scan Settings can show "last used"
    # instead of a bare on/off toggle with no history
    provider_last_used: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=time.time,
        onupdate=time.time,
    )
