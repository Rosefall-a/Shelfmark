# pylint: disable=duplicate-code
# These modules intentionally keep domain/provider-specific logic separate; similar
# structures here represent parallel APIs rather than accidental copy/paste.

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.database.models.tv_show import TVShowStatus


class TVShowBase(BaseModel):
    """Fields shared by create and update payloads."""

    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    first_air_date: date | None = None
    episode_runtime_minutes: int | None = Field(default=None, ge=0)
    creators: list[str] = Field(default_factory=list)
    studios: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    age_rating: str | None = Field(default=None, max_length=20)
    tmdb_score: Decimal | None = Field(default=None, ge=0, le=10)
    source: str | None = Field(default=None, max_length=50)
    external_id: str | None = Field(default=None, max_length=50)
    poster_url: str | None = None
    backdrop_url: str | None = None

    status: TVShowStatus = TVShowStatus.WISHLIST
    priority: str | None = Field(default=None, max_length=20)
    favorite: bool = False
    rewatches: int = Field(default=0, ge=0)
    note: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    rating_story: Decimal | None = Field(default=None, ge=0, le=10)
    rating_performance: Decimal | None = Field(default=None, ge=0, le=10)
    rating_soundtrack: Decimal | None = Field(default=None, ge=0, le=10)
    rating_overall: Decimal | None = Field(default=None, ge=0, le=10)

    personal_rank: int | None = None


class SeasonInput(BaseModel):
    """One season to bulk-create alongside a show — used when a metadata
    search result already carries its full season list (TMDB's `/tv/{id}`
    details response includes every season in one call), so the user
    doesn't have to type each one in by hand."""

    season_number: int
    name: str | None = Field(default=None, max_length=200)
    episode_count: int | None = Field(default=None, ge=0)
    air_date: date | None = None
    poster_url: str | None = None


class TVShowCreate(TVShowBase):
    """Payload for creating a show. sort_title is derived if not given.
    `seasons`, if provided, is bulk-created in the same transaction."""

    sort_title: str | None = Field(default=None, max_length=500)
    seasons: list[SeasonInput] = Field(default_factory=list)


class TVShowUpdate(BaseModel):
    """Payload for partial updates — every field optional. Seasons are
    never touched here; they have their own nested CRUD endpoints."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    sort_title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    first_air_date: date | None = None
    episode_runtime_minutes: int | None = Field(default=None, ge=0)
    creators: list[str] | None = None
    studios: list[str] | None = None
    countries: list[str] | None = None
    languages: list[str] | None = None
    genres: list[str] | None = None
    tags: list[str] | None = None
    features: list[str] | None = None
    age_rating: str | None = Field(default=None, max_length=20)
    tmdb_score: Decimal | None = Field(default=None, ge=0, le=10)
    source: str | None = Field(default=None, max_length=50)
    external_id: str | None = Field(default=None, max_length=50)
    poster_url: str | None = None
    backdrop_url: str | None = None

    status: TVShowStatus | None = None
    priority: str | None = Field(default=None, max_length=20)
    favorite: bool | None = None
    rewatches: int | None = Field(default=None, ge=0)
    note: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    rating_story: Decimal | None = Field(default=None, ge=0, le=10)
    rating_performance: Decimal | None = Field(default=None, ge=0, le=10)
    rating_soundtrack: Decimal | None = Field(default=None, ge=0, le=10)
    rating_overall: Decimal | None = Field(default=None, ge=0, le=10)

    personal_rank: int | None = None
    airing_interval_days: int | None = Field(default=None, ge=1, le=90)


class SeasonCreate(BaseModel):
    season_number: int
    name: str | None = Field(default=None, max_length=200)
    episode_count: int | None = Field(default=None, ge=0)
    air_date: date | None = None
    poster_url: str | None = None
    status: TVShowStatus = TVShowStatus.WISHLIST


class SeasonUpdate(BaseModel):
    """Partial update — every field optional, including progress."""

    season_number: int | None = None
    name: str | None = Field(default=None, max_length=200)
    episode_count: int | None = Field(default=None, ge=0)
    episodes_watched: int | None = Field(default=None, ge=0)
    air_date: date | None = None
    poster_url: str | None = None
    status: TVShowStatus | None = None


class EpisodeUpdate(BaseModel):
    """Partial update for a single episode — only the two fields a user
    can actually change; everything else is provider-synced."""

    watched: bool | None = None
    rating: Decimal | None = Field(default=None, ge=0, le=10)
    note: str | None = Field(default=None, max_length=2000)


class EpisodesBulkWatched(BaseModel):
    """Sets `watched` on a batch of episodes in one request — a range
    select or "mark watched up to here" shouldn't cost one round trip
    per episode, especially on a long-running show."""

    episode_ids: list[UUID] = Field(min_length=1, max_length=2000)
    watched: bool


class EpisodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    season_id: UUID
    episode_number: int
    title: str | None
    description: str | None
    air_date: date | None
    runtime_minutes: int | None
    still_url: str | None
    watched: bool
    rating: Decimal | None
    note: str | None = None
    created_at: int
    updated_at: int


class SeasonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    show_id: UUID
    season_number: int
    name: str | None
    episode_count: int | None
    episodes_watched: int
    status: TVShowStatus
    air_date: date | None
    poster_url: str | None
    episodes: list[EpisodeRead] = Field(default_factory=list)
    created_at: int
    updated_at: int


class TVShowReadBase(TVShowBase):
    """Full representation returned to clients, seasons included so the
    detail page loads everything in one request."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    sort_title: str
    locked_fields: list[str] = Field(default_factory=list)
    created_at: int = Field(description="Unix timestamp in seconds when the show was created.")
    updated_at: int = Field(description="Unix timestamp in seconds when the show was last updated.")

    is_airing: bool | None = None
    next_episode_air_at: int | None = None
    next_episode_number: int | None = None
    airing_interval_days: int | None = None


class TVShowLibrarySeasonRead(BaseModel):
    """Season progress returned by library list endpoints; episode rows stay on detail endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    show_id: UUID
    season_number: int
    name: str | None
    episode_count: int | None
    episodes_watched: int
    status: TVShowStatus
    air_date: date | None
    poster_url: str | None
    created_at: int
    updated_at: int


class TVShowRead(TVShowReadBase):
    """Full representation returned to clients, seasons included so the
    detail page loads everything in one request."""

    seasons: list[SeasonRead] = Field(default_factory=list)


class TVShowLibraryRead(TVShowReadBase):
    """Lightweight library representation without episode rows."""

    seasons: list[TVShowLibrarySeasonRead] = Field(default_factory=list)
