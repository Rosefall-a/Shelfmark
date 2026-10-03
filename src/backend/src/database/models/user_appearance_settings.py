# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base

# "none" turns the badge off entirely — a 100% game just looks like any
# other card. The rest are all rendered from the same {color, image,
# placement} settings below, not independent configs each, so switching
# styles doesn't lose your color/image/placement choice.
DEFAULT_BADGE_STYLE = "border"
DEFAULT_BADGE_COLOR = "#d4af37"  # gold
DEFAULT_BADGE_PLACEMENT = "top-right"


class UserAppearanceSettings(Base):
    """Per-user cosmetic preferences for how a 100%-complete (Mastered)
    game's card is highlighted. One row per user, created lazily like
    UserScanSettings."""

    __tablename__ = "user_appearance_settings"

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
    # "none" | "glow" | "border" | "ribbon" | "corner_badge"
    completion_badge_style: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DEFAULT_BADGE_STYLE
    )
    completion_badge_color: Mapped[str] = mapped_column(
        String(7), nullable=False, default=DEFAULT_BADGE_COLOR
    )
    # "top-left" | "top-right" | "bottom-left" | "bottom-right" — ignored by
    # "glow"/"border", which wrap the whole card rather than sitting in one
    # corner
    completion_badge_placement: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DEFAULT_BADGE_PLACEMENT
    )
    # a user-uploaded image (ribbon/corner_badge only) — stored at
    # /data/badges/{user_id}.png via the same save_media_bytes helper
    # everything else's uploaded art uses. NULL means "use the built-in
    # trophy icon".
    completion_badge_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=time.time,
        onupdate=time.time,
    )
