from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class Set(Base):
    """A user-defined grouping of Cards with a position/total — per the
    design spec, set membership ("07/24") is collector-footer information
    a *card* carries, not a property of the game itself. See
    database/models/card.py's `set_id`. Distinct from the unrelated
    Collections smart-grouping feature and from Game's own legacy
    free-text `series` string (untouched, still populated by metadata
    sync — a Set is the real, position-aware grouping, that string is
    just display metadata)."""

    __tablename__ = "sets"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_sets_user_id_name"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # the user's stated expected total for this set, e.g. "24" for a
    # numbered set they know the full size of. NULL means unknown — the
    # set shows a running count but never counts as "complete".
    target_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    updated_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=time.time, onupdate=time.time
    )
