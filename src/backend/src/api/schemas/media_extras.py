# pylint: disable=missing-class-docstring,duplicate-code
"""Schemas for the cross-media-type features (rewatch history, custom
lists, the activity feed) — see api/routes/media_extras.py."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

_MEDIA_TYPES = ("movie", "tv", "anime")


class RewatchCreate(BaseModel):
    media_type: str = Field(pattern="^(movie|tv|anime)$")
    media_id: UUID
    finished_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


class RewatchRead(BaseModel):
    id: UUID
    media_type: str
    media_id: UUID
    finished_on: date
    note: str | None
    created_at: int


class SmartRule(BaseModel):
    """Filter for a smart list — every set field must match. Evaluated
    against the whole library on every read, never stored as members."""

    media_types: list[str] | None = None
    status_buckets: list[str] | None = None
    genre: str | None = Field(default=None, max_length=100)
    min_score: float | None = Field(default=None, ge=0, le=10)
    favorite: bool | None = None


class MediaListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    smart_rule: SmartRule | None = None


class MediaListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    smart_rule: SmartRule | None = None
    cover_media_id: UUID | None = None
    pinned: bool | None = None


class MediaListRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    item_count: int
    is_smart: bool = False
    # kept by the app (Favorites): cannot be renamed, re-ruled or deleted
    is_system: bool = False
    pinned: bool = False
    position: int = 0
    # how many titles of each type it holds, so the overview can filter by type
    type_counts: dict[str, int] = Field(default_factory=dict)
    smart_rule: SmartRule | None = None
    cover_media_id: UUID | None = None
    # up to 4 poster URLs for the overview card's collage, cover first —
    # here so the grid doesn't need one detail request per list
    preview_posters: list[str | None] = Field(default_factory=list)
    created_at: int
    updated_at: int


class MediaListItemCreate(BaseModel):
    media_type: str = Field(pattern="^(movie|tv|anime)$")
    media_id: UUID


class MediaListsOrder(BaseModel):
    list_ids: list[UUID] = Field(min_length=1, max_length=500)


class MediaListReorder(BaseModel):
    item_ids: list[UUID] = Field(min_length=1)


class MediaListItemRead(BaseModel):
    id: UUID
    media_type: str
    media_id: UUID
    title: str
    poster_url: str | None
    status: str
    added_at: int


class MediaListDetailRead(MediaListRead):
    items: list[MediaListItemRead]


class ActivityEntryRead(BaseModel):
    id: UUID
    media_type: str
    media_id: UUID
    media_title: str
    event_type: str
    event_date: date
    count: int
    detail: str | None


class ActivityEntryCreate(BaseModel):
    """A manually-logged entry — for anything the app didn't catch
    automatically (imported watch history, a title tracked before this
    feature existed, etc). Goes through the same day-bucket upsert as
    every automatic entry, so a manual log on a day that already has one
    just adds to its count rather than creating a second line."""

    media_type: str = Field(pattern="^(movie|tv|anime)$")
    media_id: UUID
    event_type: str = Field(pattern="^(episodes_watched|status_changed|rewatched|rated)$")
    event_date: date
    count: int = Field(default=1, ge=1)
    detail: str | None = Field(default=None, max_length=500)


class ActivityEntryUpdate(BaseModel):
    """Partial update — every field is editable, including which title
    and event type the entry is attached to. Moving onto a bucket key
    (media_type, media_id, event_type, event_date) that already has a
    row merges into it (counts added together) rather than erroring on
    the unique constraint."""

    media_type: str | None = Field(default=None, pattern="^(movie|tv|anime)$")
    media_id: UUID | None = None
    event_type: str | None = Field(
        default=None, pattern="^(episodes_watched|status_changed|rewatched|rated)$"
    )
    event_date: date | None = None
    count: int | None = Field(default=None, ge=1)
    detail: str | None = None


class CalendarEntryRead(BaseModel):
    media_type: str
    media_id: UUID
    title: str
    poster_url: str | None
    next_episode_number: int | None
    air_at: int
    # "episode" = a next-airing-episode countdown for something already
    # being watched/airing; "release" = an upcoming release/premiere date
    # for something still on Plan to Watch — see get_calendar's docstring.
    kind: str = "episode"
    # False only for the one real, provider-confirmed next-episode date;
    # every later episode entry for the same show is a weekly-cadence
    # guess (no provider gives a full future schedule), so the frontend
    # can mark it as estimated rather than presenting it as fact.
    is_projected: bool = False
