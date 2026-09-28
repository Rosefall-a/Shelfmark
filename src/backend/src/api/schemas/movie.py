# pylint: disable=duplicate-code,missing-module-docstring,cyclic-import
# Domain schemas intentionally mirror the corresponding database/provider models.

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.database.models.movies import MovieStatus


class MovieBase(BaseModel):
    """Fields shared by create and update payloads."""

    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    director: str | None = Field(default=None, max_length=200)
    writer: str | None = Field(default=None, max_length=200)
    studios: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    age_rating: str | None = Field(default=None, max_length=20)
    tmdb_score: Decimal | None = Field(default=None, ge=0, le=10)
    source: str | None = Field(default=None, max_length=50)
    poster_url: str | None = None
    backdrop_url: str | None = None

    status: MovieStatus = MovieStatus.WISHLIST
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


class MovieCreate(MovieBase):
    """Payload for creating a movie. sort_title is derived if not given."""

    sort_title: str | None = Field(default=None, max_length=500)


class MovieUpdate(BaseModel):
    """Payload for partial updates — every field optional."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    sort_title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    director: str | None = Field(default=None, max_length=200)
    writer: str | None = Field(default=None, max_length=200)
    studios: list[str] | None = None
    countries: list[str] | None = None
    languages: list[str] | None = None
    genres: list[str] | None = None
    tags: list[str] | None = None
    features: list[str] | None = None
    age_rating: str | None = Field(default=None, max_length=20)
    tmdb_score: Decimal | None = Field(default=None, ge=0, le=10)
    source: str | None = Field(default=None, max_length=50)
    poster_url: str | None = None
    backdrop_url: str | None = None

    status: MovieStatus | None = None
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


class MovieRead(MovieBase):
    """Full representation returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    sort_title: str
    locked_fields: list[str] = Field(default_factory=list)
    created_at: int = Field(description="Unix timestamp in seconds when the movie was created.")
    updated_at: int = Field(
        description="Unix timestamp in seconds when the movie was last updated."
    )
