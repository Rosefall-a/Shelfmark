# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.database.models.game import Game


class GameArchive(Base):
    """A named save slot for a game — "Main World", "Pre-Nether-Update
    Backup", etc. Replaces the old convention of a save just being an
    anonymous uploaded file: an archive is the durable identity (name,
    created_at), GameArchiveVersion rows underneath it are the actual
    uploaded files, so re-uploading a save keeps the old ones as history
    instead of silently replacing them.

    kind is "save" or "world_save" — docs/modpacks stay on the simpler flat
    file system (files/{kind} routes in games.py), since naming/history
    doesn't add much for a single manual/game-file/doc."""

    __tablename__ = "game_archives"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    updated_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=time.time, onupdate=time.time
    )
    # set instead of deleting — the files move to a trash folder alongside
    # this, and a background sweep purges both after 7 days (see
    # features/trash/sweep.py). NULL means active/not deleted.
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    game: Mapped["Game"] = relationship()
    versions: Mapped[list["GameArchiveVersion"]] = relationship(
        back_populates="archive",
        cascade="all, delete-orphan",
        order_by="GameArchiveVersion.uploaded_at.desc()",
    )


class GameArchiveVersion(Base):
    """One uploaded file within an archive's history. `filename` is the
    on-disk name (already sanitized/uniqued by save_media_bytes) under
    /data/games/{folder}/{saves|world_saves}/{archive_id}/{filename}."""

    __tablename__ = "game_archive_versions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    archive_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("game_archives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    archive: Mapped["GameArchive"] = relationship(back_populates="versions")
