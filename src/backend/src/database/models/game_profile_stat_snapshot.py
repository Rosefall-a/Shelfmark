# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import JSON as PG_JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class GameProfileStatSnapshot(Base):
    """A dated copy of GameProfile.stats — written automatically every
    time stats change (a WiseOldMan sync or a manual edit), plus
    backfilled from WiseOldMan's own snapshot history on a profile's
    first sync when it has one. This is what lets progression ("what was
    my Zulrah KC a month ago?") be shown over time instead of only ever
    seeing the current numbers GameProfile.stats holds."""

    __tablename__ = "game_profile_stat_snapshots"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("game_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stats: Mapped[dict[str, str]] = mapped_column(PG_JSON, nullable=False, default=dict)
    # raw integers alongside `stats`' display strings — a manual edit never
    # sets these (empty dicts), a WiseOldMan sync always does. Needed to
    # compute an accurate day-to-day gain: a single skill level can span
    # tens of thousands of XP, so diffing the level number alone would be
    # meaningless for a "gained this much XP" readout.
    xp: Mapped[dict[str, int]] = mapped_column(PG_JSON, nullable=False, default=dict)
    kc: Mapped[dict[str, int]] = mapped_column(PG_JSON, nullable=False, default=dict)
    # when this snapshot represents (may be backdated for WOM-imported
    # history) — distinct from row-insert time, which SQLAlchemy/Postgres
    # never exposes here anyway since there's no separate created_at
    recorded_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=time.time, index=True
    )
