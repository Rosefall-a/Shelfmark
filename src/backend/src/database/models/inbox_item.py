# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class InboxItem(Base):
    """A bulk-uploaded screenshot/clip/soundtrack not yet assigned to a
    game. Previously tracked only as a bare file on disk with no DB row at
    all — that meant no real upload date (the design called for one under
    each thumbnail) and no way to soft-delete, unlike every other delete
    path in the app. deleted_at follows the same pattern as
    GameArchive/GameArchiveVersion: NULL means active, set means trashed —
    the file itself moves to a sibling _trash folder (see
    features/trash/inbox_trash.py) and features/trash/sweep.py purges both
    after 7 days."""

    __tablename__ = "inbox_items"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
