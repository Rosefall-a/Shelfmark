# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class GameFileItem(Base):
    """A doc/manual or modpack file attached to a game. Previously tracked
    only as a bare file on disk (games.py's /files/{kind} routes walked the
    directory directly) with no DB row at all — same gap the inbox had:
    no real upload date, and no way to soft-delete it like every other
    delete path in the app now has. deleted_at follows the same pattern as
    InboxItem: NULL means active, set means trashed, and
    features/trash/sweep.py purges the row and the trashed file after 7
    days."""

    __tablename__ = "game_file_items"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # "doc" | "modpack"
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
