# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class GameFieldChange(Base):
    """One entry in a game's metadata history: a single field that actually
    changed value, either from a manual edit or a metadata search/refresh
    being applied. Written by update_game (see FIELD_CHANGE_TRACKED_FIELDS
    in api/routes/games.py) and read back by the game page's History tab."""

    __tablename__ = "game_field_changes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=lambda: int(time.time())
    )
