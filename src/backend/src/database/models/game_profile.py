# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON as PG_JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class GameProfile(Base):
    """A named sub-scope within one game — e.g. separate OSRS accounts
    (Main, Ironman) or separate save slots you're tracking independently.
    Not a new Game row: a profile shares the parent game's library entry
    entirely and only exists to let checklist items and media be filtered
    down to one account instead of digging through everything the game has.
    No file storage of its own, so trash here is just the row (see
    features/trash/sweep.py) — nothing on disk to move."""

    __tablename__ = "game_profiles"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # free text — "what I'm working toward on this account", separate from
    # the game-level Notes tab's markdown notes
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # free-form key/value pairs (e.g. {"Overall": "1450", "Combat": "110"})
    # — manually edited, or filled in bulk by a WiseOldMan sync. A JSON blob
    # rather than a separate table since order/typing don't matter here,
    # it's just a small label/value list rendered as-is.
    stats: Mapped[dict[str, str]] = mapped_column(PG_JSON, nullable=False, default=dict)
    # RuneScape username used to pull stats from wiseoldman.net (OSRS-
    # specific, unlike the rest of this model) — nullable since most
    # profiles on most games never use this
    wiseoldman_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
