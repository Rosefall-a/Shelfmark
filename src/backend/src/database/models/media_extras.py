# pylint: disable=missing-class-docstring,too-few-public-methods,unsubscriptable-object
"""Cross-media-type tables — rewatch history, custom lists, and the
activity log all need to reference "a movie, a TV show, or an anime"
generically, and those three live in entirely separate tables with no
shared base, so each row here carries its own `media_type` discriminator
plus a plain `media_id` (no FK — a UUID can't reference one of three
different possible tables) instead of a real foreign key. `media_type`
is validated at the API layer, not the database's."""

from datetime import date

from enum import Enum

import time

from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class MediaType(str, Enum):
    MOVIE = "movie"
    TV = "tv"
    ANIME = "anime"


class RewatchLog(Base):
    """One completed rewatch of a title, dated to the day (not a precise
    timestamp) it was finished — "history on the day, not the hour" per
    how this is meant to be read back: a rewatch log, not an activity
    trace. `Movie.rewatches`/`TVShow.rewatches`/`Anime.rewatches` stay
    the fast denormalized count the library grid already reads; this
    table is what lets a detail page show *when* each one happened."""

    __tablename__ = "rewatch_logs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_type: Mapped[MediaType] = mapped_column(
        SAEnum(MediaType, native_enum=False, length=10), nullable=False
    )
    media_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    finished_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=lambda: int(time.time())
    )


class MediaList(Base):
    """A user-named, user-ordered grouping that can hold any mix of
    movies/TV shows/anime — "comfort watches", "watch with Sam", etc.
    Distinct from the existing per-game `Collections` feature (a
    different, games-only smart-grouping mechanism already in this
    codebase) and from a title's own `tags` array (per-item labels, not
    a browsable named group)."""

    __tablename__ = "media_lists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_media_lists_user_id_name"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A smart list has no stored members: `smart_rule` is a filter
    # ({"media_type"?, "status"?, "genre"?, "min_score"?}) evaluated
    # against the whole library every time the list is read, same idea
    # as the Games side's Smart Collections. NULL = an ordinary manual list.
    smart_rule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Which member represents the list on the overview grid; NULL = the
    # default 2x2 collage of its first four titles.
    cover_media_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # a list the app keeps for you (Favorites): it cannot be renamed or deleted
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # pinned lists sit first; within that, lowest position first (the user's
    # own order), ties falling back to Favorites then name
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=lambda: int(time.time())
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )


class MediaListItem(Base):
    """One title's membership in one list."""

    __tablename__ = "media_list_items"
    __table_args__ = (
        UniqueConstraint(
            "list_id", "media_type", "media_id", name="uq_media_list_items_list_media"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    list_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("media_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_type: Mapped[MediaType] = mapped_column(
        SAEnum(MediaType, native_enum=False, length=10), nullable=False
    )
    media_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    # user-defined order within the list (lowest first); ties fall back
    # to newest-added-first, the old behavior
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=lambda: int(time.time())
    )


class ActivityEventType(str, Enum):
    EPISODES_WATCHED = "episodes_watched"
    STATUS_CHANGED = "status_changed"
    RATED = "rated"
    REWATCHED = "rewatched"


class ActivityLog(Base):
    """A day-granular history feed, not a per-action audit trail —
    checking off ten episodes in one sitting is one row (`count=10`) for
    that day, not ten. Written by upserting on
    (user_id, media_type, media_id, event_type, event_date) and
    incrementing `count`/refreshing `detail` rather than inserting a new
    row per event, so a day with a lot of activity still reads back as
    one line: "12 episodes of X watched" instead of a wall of
    timestamps."""

    __tablename__ = "activity_log"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "media_type",
            "media_id",
            "event_type",
            "event_date",
            name="uq_activity_log_bucket",
        ),
        Index("ix_activity_log_user_event_date", "user_id", "event_date"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_type: Mapped[MediaType] = mapped_column(
        SAEnum(MediaType, native_enum=False, length=10), nullable=False
    )
    media_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    media_title: Mapped[str] = mapped_column(String(500), nullable=False)
    event_type: Mapped[ActivityEventType] = mapped_column(
        SAEnum(ActivityEventType, native_enum=False, length=20), nullable=False
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )
