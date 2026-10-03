"""User-owned provider links, playback snapshots and independently identified sessions.

Like media_extras, the media discriminator references three separate domain tables.
No plugin may query these tables directly; the public media.sync API owns writes.
"""

from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class MediaProviderLink(Base):
    """One stable remote identity, including its last successfully applied snapshot."""

    __tablename__ = "media_provider_links"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "plugin_id",
            "source",
            "source_scope",
            "external_id",
            name="uq_media_provider_identity",
        ),
        Index("ix_media_provider_target", "user_id", "media_type", "media_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_scope: Mapped[str] = mapped_column(String(512), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    media_type: Mapped[str] = mapped_column(String(10), nullable=False)
    media_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    applied_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class MediaPlaybackEvent(Base):
    """A reported session, or a explicitly labelled observation of last-played state."""

    __tablename__ = "media_playback_events"
    __table_args__ = (
        UniqueConstraint("link_id", "external_id", name="uq_media_playback_event"),
        Index("ix_media_playback_history", "user_id", "media_id", "played_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    link_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("media_provider_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    episode_external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    played_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provenance: Mapped[str] = mapped_column(String(30), nullable=False)
