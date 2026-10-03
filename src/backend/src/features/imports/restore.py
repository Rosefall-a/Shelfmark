"""Restoring movies, TV shows and anime from the app's own JSON export
(GET /api/export/library, or a scheduled backup file).

Rows are rebuilt from the mapped columns of each model rather than a field
list kept by hand, so a column added later is restored without touching this
file. What is never carried over: ids, the owner, timestamps, and links to
other rows (a linked movie or show would point at a stranger's row on
another server). A title already in the library, same name and same year, is
skipped and never overwritten, so restoring twice or onto a live library is
safe. One bad entry is reported and skipped without stopping the rest."""
# pylint: disable=missing-function-docstring,too-many-locals,broad-exception-caught

from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal, InvalidOperation
from typing import Any, TypeAlias

from sqlalchemy import Date, Numeric, select
from sqlalchemy import Enum as SAEnum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import class_mapper

from src.database.models.anime import Anime, AnimeEpisode, AnimeSeason
from src.database.models.movies import Movie
from src.database.models.tv_show import TVEpisode, TVSeason, TVShow

_NEVER = {
    "id",
    "user_id",
    "created_at",
    "updated_at",
    "deleted_at",
    "show_id",
    "season_id",
    "linked_tv_show_id",
    "linked_movie_id",
    "relations_cache",
    "relations_cached_at",
}
MAX_ENTRIES = 20000

MediaModel: TypeAlias = type[Movie] | type[TVShow] | type[Anime]


def _convert(column: Any, value: Any) -> Any:
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, Date):
        return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])
    if isinstance(kind, Numeric):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{column.key}: not a number") from exc
    if isinstance(kind, SAEnum) and kind.enum_class is not None:
        enum_class: type[enum.Enum] = kind.enum_class
        try:
            return enum_class(value)
        except ValueError as exc:
            raise ValueError(f"{column.key}: unknown value {value!r}") from exc
    return value


def _fields(model: type, data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in class_mapper(model).columns:
        if column.key in _NEVER or column.key not in data:
            continue
        out[column.key] = _convert(column, data[column.key])
    return out


def _year(value: Any) -> int | None:
    return value.year if isinstance(value, dt.date) else None


async def _existing(
    db: AsyncSession, model: MediaModel, user_id: Any, date_field: str
) -> set[tuple[str, int | None]]:
    rows = (
        await db.execute(
            select(model.title, getattr(model, date_field)).where(  # type: ignore[attr-defined]
                model.user_id == user_id,
                model.deleted_at.is_(None),
            )
        )
    ).all()
    return {(t.lower(), _year(d)) for t, d in rows}


def _add_children(
    db: AsyncSession,
    show_id: Any,
    seasons: list[dict[str, Any]],
    season_model: type,
    episode_model: type,
) -> None:
    seen_seasons: set[int] = set()
    for raw in seasons:
        number = raw.get("season_number")
        if not isinstance(number, int) or number in seen_seasons:
            continue
        seen_seasons.add(number)
        season = season_model(show_id=show_id, **_fields(season_model, raw))
        db.add(season)
        episodes = raw.get("episodes") or []
        if episodes:
            season.episodes = []
        seen_episodes: set[int] = set()
        for ep in episodes:
            n = ep.get("episode_number")
            if not isinstance(n, int) or n in seen_episodes:
                continue
            seen_episodes.add(n)
            season.episodes.append(episode_model(**_fields(episode_model, ep)))


async def restore_media(db: AsyncSession, user_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"created": {}, "skipped": {}, "errors": []}
    plan = (
        ("movies", Movie, "release_date", None, None),
        ("tv_shows", TVShow, "first_air_date", TVSeason, TVEpisode),
        ("anime", Anime, "first_air_date", AnimeSeason, AnimeEpisode),
    )
    for key, model, date_field, season_model, episode_model in plan:
        entries = payload.get(key) or []
        if not isinstance(entries, list):
            result["errors"].append(f"{key}: expected a list")
            continue
        seen = await _existing(db, model, user_id, date_field)
        created = skipped = 0
        for raw in entries[:MAX_ENTRIES]:
            title = raw.get("title") if isinstance(raw, dict) else None
            if not isinstance(title, str) or not title.strip():
                result["errors"].append(f"{key}: an entry has no title")
                continue
            try:
                fields = _fields(model, raw)
                identity = (title.lower(), _year(fields.get(date_field)))
                if identity in seen:
                    skipped += 1
                    continue
                async with db.begin_nested():
                    item = model(user_id=user_id, **fields)
                    db.add(item)
                    await db.flush()
                    if season_model is not None and episode_model is not None:
                        _add_children(
                            db, item.id, raw.get("seasons") or [], season_model, episode_model
                        )
                        await db.flush()
                seen.add(identity)
                created += 1
            except Exception as exc:  # noqa: BLE001, one bad entry must not stop the rest
                skipped += 1
                result["errors"].append(f"{title}: {exc}")
        result["created"][key] = created
        result["skipped"][key] = skipped
    await db.commit()
    result["errors"] = result["errors"][:30]
    return result
