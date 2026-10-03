"""Server-side per-user preferences: defaults live here, the database row
(UserPreferences.data) only stores what the user changed. Adding an
option is a one-line change to DEFAULTS, not a migration."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.user_preferences import UserPreferences

DEFAULTS: dict[str, Any] = {
    "calendar_game_releases": True,
    "calendar_game_history": True,
    "calendar_default_view": "month",
    "calendar_week_start": 0,
    "calendar_hide_games": False,
    "calendar_show_estimated": True,
    "calendar_airing_statuses": ["watching", "plan", "hold"],
    "notify_episode_aired": True,
    "notify_season_started": True,
    "notify_sequel_announced": True,
    "notify_movie_released": True,
    "notify_session_anomaly": True,
    "notify_statuses": ["watching", "plan", "hold"],
    "notify_media_types": ["anime", "tv", "movie"],
    "notification_retention_days": 30,
    "library_default_layout": "list",
    "title_language": "english",
    "lists_default_sort": "custom",
    "stats_include_plan": True,
    "anilist_import_enabled": False,
    "anilist_import_username": "",
    "anilist_import_interval_minutes": 24 * 60,
    "anilist_import_update_existing": False,
    "anilist_import_last_run_at": None,
}

_CHOICES: dict[str, tuple[Any, ...]] = {
    "calendar_default_view": ("month", "week", "agenda"),
    "calendar_week_start": (0, 1),
    "notification_retention_days": (0, 7, 14, 30, 90),
    "library_default_layout": ("list", "shelf", "board"),
    "lists_default_sort": ("custom", "name", "count", "recent"),
    "title_language": ("english", "romaji", "native"),
}

_SET_CHOICES: dict[str, tuple[str, ...]] = {
    "notify_statuses": ("watching", "plan", "hold"),
    "calendar_airing_statuses": ("watching", "plan", "hold"),
    "notify_media_types": ("anime", "tv", "movie"),
}


def validate_preference(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise ValueError(f"Unknown preference {key!r}")
    default = DEFAULTS[key]
    if key in _SET_CHOICES:
        allowed = _SET_CHOICES[key]
        if not isinstance(value, list) or any(v not in allowed for v in value):
            raise ValueError(f"{key} must be a list drawn from {list(allowed)}")
        return [v for v in allowed if v in value]
    if key in _CHOICES:
        if value not in _CHOICES[key]:
            raise ValueError(f"{key} must be one of {list(_CHOICES[key])}")
        return value
    if key == "anilist_import_username":
        if not isinstance(value, str) or len(value.strip()) > 100:
            raise ValueError("anilist_import_username must be a string of at most 100 characters")
        return value.strip()
    if key == "anilist_import_interval_minutes":
        if not isinstance(value, int) or isinstance(value, bool) or not 60 <= value <= 30 * 24 * 60:
            raise ValueError("anilist_import_interval_minutes must be between 60 and 43200")
        return value
    if key == "anilist_import_last_run_at":
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ValueError("anilist_import_last_run_at must be a Unix timestamp or null")
        return value
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    return value


async def load_preferences(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    row = await db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))
    return {**DEFAULTS, **(row.data if row else {})}


async def save_preferences(
    db: AsyncSession, user_id: UUID, changes: dict[str, Any]
) -> dict[str, Any]:
    clean = {k: validate_preference(k, v) for k, v in changes.items()}
    row = await db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))
    if row is None:
        row = UserPreferences(user_id=user_id, data={})
        db.add(row)
    row.data = {**row.data, **clean}
    await db.commit()
    return {**DEFAULTS, **row.data}
