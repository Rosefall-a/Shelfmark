# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class GameChecklistItem(Base):
    """One to-do line on a game's Notes tab — e.g. "get quest cape" or
    "finish collection log". profile_id is NULL for a checklist item that
    applies to the game as a whole; set when it belongs to one specific
    GameProfile (e.g. one OSRS account) so accounts don't share a single
    undifferentiated list. sort_order is a plain float (like a linked-list
    gap) so reordering one item only ever rewrites that one row."""

    __tablename__ = "game_checklist_items"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("game_profiles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # a section header (e.g. "Quest cape reqs") rendered as a divider rather
    # than a checkable row — lives in the same ordered list as real items
    # instead of a separate table, so it can sit anywhere in the sort order
    is_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[float] = mapped_column(nullable=False, default=0.0)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
