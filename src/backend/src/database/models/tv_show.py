# pylint: disable=missing-module-docstring,missing-class-docstring,too-few-public-methods,unsubscriptable-object
from datetime import date
from decimal import Decimal
from enum import Enum
import time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.database.models.user import User


class TVShowStatus(str, Enum):
    """TV show status aligned with a media library workflow — same value
    set as MovieStatus, shared here since a season also uses it (a season
    can be independently Watching/Watched/Dropped even while the show
    overall reads something else)."""

    DROPPED = "DROPPED"
    WISHLIST = "WISHLIST"
    WATCHLIST = "WATCHLIST"
    BACKLOG = "BACKLOG"
    IN_PROGRESS = "IN_PROGRESS"
    WATCHED = "WATCHED"
    FAVORITE = "FAVORITE"
    REWATCH = "REWATCH"


class TVShow(Base):
    __tablename__ = "tv_shows"

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user: Mapped["User"] = relationship()

    # set instead of actually deleting the row — same soft-delete
    # convention as Movie/Game/Card. NULL means active/not deleted.
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # ------------------------------------------------------------------
    # Basic metadata
    # ------------------------------------------------------------------

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_air_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # average minutes per episode — a show doesn't have one single runtime
    # the way a movie does
    episode_runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # a show usually has several creators/showrunners rather than a single
    # director/writer pair, unlike Movie
    creators: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    studios: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    countries: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    genres: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    features: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    age_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tmdb_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # the source provider's own id for this show (TVmaze's numeric id) —
    # kept so episode sync can hit that exact show again later instead of
    # re-searching by title and hoping for an exact match
    external_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # NULL until the airing-check loop has actually looked (nothing to
    # filter on yet); True/False once TVmaze's own show status has been
    # checked at least once. Lets the frequent airing-check loop skip a
    # show entirely once it's known to have ended, instead of re-fetching
    # its episode list every cycle forever.
    is_airing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # TVmaze's `_embedded.nextepisode.airstamp`, converted to a real
    # timestamp — populated by the same airing-check loop, alongside
    # is_airing, so a countdown and the calendar view have a real date
    # to work from instead of just a yes/no flag.
    next_episode_air_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    next_episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # when TVmaze was last asked whether this show has seasons we don't have
    seasons_checked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Days between episodes, for projecting the ones after the confirmed
    # next one (no provider gives a full future schedule). NULL = the
    # weekly default; set per show for biweekly/daily/irregular releases.
    airing_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # a direct external URL (TMDB's CDN / OMDb's Poster field), stored
    # as-is — same convention as Movie.poster_url, never downloaded/resized
    poster_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # a wide-format background image (TMDB's backdrop_path), distinct
    # from the portrait poster_url above — used for the detail page hero
    backdrop_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # names of fields an admin has manually changed away from what a
    # metadata provider last set — "Apply metadata" skips these instead
    # of silently overwriting a deliberate fix
    locked_fields: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    # ------------------------------------------------------------------
    # Personal library state
    # ------------------------------------------------------------------

    status: Mapped[TVShowStatus] = mapped_column(
        SAEnum(TVShowStatus, native_enum=False, length=30),
        nullable=False,
        default=TVShowStatus.WISHLIST,
    )
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rewatches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ------------------------------------------------------------------
    # Ratings
    # ------------------------------------------------------------------

    rating_story: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    rating_performance: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    rating_soundtrack: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    rating_overall: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)

    personal_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # eager (selectin, not the default lazy) — TVShowRead serializes
    # `seasons` straight into the API response (same reason as
    # Game.links: a lazy load can't run once the async session that
    # produced the row is out of the request's await context)
    seasons: Mapped[list["TVSeason"]] = relationship(
        back_populates="show",
        order_by="TVSeason.season_number",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------

    created_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=lambda: int(time.time())
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )


class TVSeason(Base):
    """One season of a TVShow — a real child row, so progress and status
    can be tracked per season independently of the show overall.
    `episodes_watched`/`episode_count` stay as the flat progress numbers
    used everywhere else in the app (library rows, quick add); `episodes`
    below is the optional richer breakdown, synced from the source
    provider on first request and cached rather than re-fetched."""

    __tablename__ = "tv_seasons"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    show_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tv_shows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    show: Mapped["TVShow"] = relationship(back_populates="seasons")

    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # e.g. a real subtitle ("The Long Night") vs just "Season 1" — nullable
    # since providers don't always give one
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    episode_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episodes_watched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[TVShowStatus] = mapped_column(
        SAEnum(TVShowStatus, native_enum=False, length=30, name="tvseasonstatus"),
        nullable=False,
        default=TVShowStatus.WISHLIST,
    )
    air_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    episodes: Mapped[list["TVEpisode"]] = relationship(
        back_populates="season",
        order_by="TVEpisode.episode_number",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    created_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=lambda: int(time.time())
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )


class TVEpisode(Base):
    """One episode of a TVSeason. Rows are synced in from the source
    provider (TVmaze) the first time a season's episode list is
    requested, then persisted here — later requests read straight from
    this table instead of re-fetching, and `watched`/`rating` are purely
    local, never touched by a re-sync."""

    __tablename__ = "tv_episodes"
    __table_args__ = (
        UniqueConstraint(
            "season_id", "episode_number", name="uq_tv_episodes_season_id_episode_number"
        ),
        Index("ix_tv_episodes_season_watched", "season_id", "watched"),
        Index("ix_tv_episodes_air_at", "air_at", postgresql_where=text("air_at IS NOT NULL")),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    season_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tv_seasons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    season: Mapped["TVSeason"] = relationship(back_populates="episodes")

    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    air_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    still_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    watched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    # exact air time (unix seconds) when the provider gives one; air_date
    # alone is only a calendar day
    air_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=lambda: int(time.time())
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )
