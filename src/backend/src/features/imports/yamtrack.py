"""Import Yamtrack's CSV export into the media library.

Yamtrack exports one parent row plus optional season and episode rows for the
same media_id. The importer groups those rows before creating library items so
season/episode records never become duplicate shows.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from src.api.routes.anime import _derive_sort_title
from src.database.models.anime import Anime, AnimeEpisode, AnimeSeason, AnimeStatus
from src.database.models.movies import Movie, MovieStatus
from src.database.models.tv_show import TVEpisode, TVSeason, TVShow, TVShowStatus

MAX_BYTES = 200 * 1024 * 1024
MAX_ROWS = 50000

_STATUS = {
    "completed": "WATCHED",
    "watching": "IN_PROGRESS",
    "plan to watch": "WATCHLIST",
    "on-hold": "BACKLOG",
    "on hold": "BACKLOG",
    "dropped": "DROPPED",
    "watched": "WATCHED",
}


@dataclass
class YamtrackGroup:
    source: str
    media_id: str
    media_type: str
    parent: dict[str, str] | None = None
    seasons: dict[int, dict[str, Any]] = field(default_factory=dict)


def _date(value: str | None) -> dt.date | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None


def _int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _score(value: str | None) -> Decimal | None:
    if not value or not value.strip():
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _status(value: str | None, enum_class: Any) -> Any:
    mapped = _STATUS.get((value or "").strip().lower())
    if mapped is None:
        return enum_class.WATCHLIST
    return enum_class(mapped)


def _watched(row: dict[str, str]) -> bool:
    return bool(
        (row.get("end_date") or "").strip()
        or (row.get("status") or "").strip().lower() in {"completed", "watched"}
    )


def parse_yamtrack(raw: bytes) -> list[YamtrackGroup]:
    if len(raw) > MAX_BYTES:
        raise ValueError("The Yamtrack export is too large.")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
    except UnicodeDecodeError as exc:
        raise ValueError("The Yamtrack export must be UTF-8 CSV.") from exc

    required = {"media_id", "source", "media_type", "title"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError(
            "This does not look like a Yamtrack export; expected media_id, source, media_type and title columns."
        )

    groups: dict[tuple[str, str], YamtrackGroup] = {}
    rows = 0
    for row in reader:
        rows += 1
        if rows > MAX_ROWS:
            raise ValueError(f"The Yamtrack export contains more than {MAX_ROWS} rows.")
        source = (row.get("source") or "").strip()
        media_id = (row.get("media_id") or "").strip()
        media_type = (row.get("media_type") or "").strip().lower()
        if not source or not media_id or not media_type:
            continue
        if media_type not in {"movie", "tv", "anime", "season", "episode"}:
            continue

        key = (source.lower(), media_id)
        group = groups.get(key)
        if group is None:
            base_type = media_type if media_type in {"movie", "tv", "anime"} else "tv"
            group = groups[key] = YamtrackGroup(source, media_id, base_type)

        if media_type in {"movie", "tv", "anime"}:
            if group.parent is None:
                group.parent = row
            continue

        season_number = _int(row.get("season_number"))
        if season_number is None:
            continue
        season = group.seasons.setdefault(season_number, {"row": None, "episodes": {}})
        if media_type == "season":
            season["row"] = row
        else:
            episode_number = _int(row.get("episode_number"))
            if episode_number is not None:
                season["episodes"][episode_number] = row

    return [g for g in groups.values() if g.parent is not None]


def _season_rows(group: YamtrackGroup, season_cls: type, episode_cls: type, enum_class: Any) -> list[Any]:
    result = []
    parent_progress = _int((group.parent or {}).get("progress")) or 0
    for number in sorted(group.seasons):
        data = group.seasons[number]
        raw = data["row"] or {}
        episodes = data["episodes"]
        watched_from_episodes = sum(_watched(ep) for ep in episodes.values())
        season_progress = _int(raw.get("progress"))
        if season_progress is not None:
            watched = max(season_progress, watched_from_episodes)
        elif episodes:
            watched = watched_from_episodes
        else:
            watched = parent_progress
        episode_count = max(episodes) if episodes else None
        season = season_cls(
            season_number=number,
            episode_count=episode_count,
            episodes_watched=watched,
            status=_status(raw.get("status"), enum_class),
            air_date=_date(raw.get("start_date")),
        )
        season.episodes = [
            episode_cls(episode_number=ep_number, watched=_watched(ep), note=ep.get("notes") or None)
            for ep_number, ep in sorted(episodes.items())
        ]
        result.append(season)
    return result


def _parent_fields(group: YamtrackGroup) -> dict[str, Any]:
    row = group.parent or {}
    return {
        "title": row.get("title") or f"Yamtrack {group.media_id}",
        "sort_title": _derive_sort_title(row.get("title") or f"Yamtrack {group.media_id}"),
        "source": group.source,
        "external_id": group.media_id,
        "status": row.get("status"),
        "rating": _score(row.get("score")),
        "note": row.get("notes") or None,
        "start_date": _date(row.get("start_date")),
        "end_date": _date(row.get("end_date")),
        "poster_url": row.get("image") or None,
    }


def build_yamtrack_item(group: YamtrackGroup) -> Movie | TVShow | Anime:
    row = group.parent or {}
    if group.media_type == "movie":
        p = _parent_fields(group)
        return Movie(title=p["title"], sort_title=p["sort_title"], source=p["source"], status=_status(row.get("status"), MovieStatus), rating_overall=p["rating"], note=p["note"], start_date=p["start_date"], end_date=p["end_date"], poster_url=p["poster_url"])
    if group.media_type == "anime":
        p = _parent_fields(group)
        return Anime(title=p["title"], sort_title=p["sort_title"], source=p["source"], external_id=p["external_id"], status=_status(row.get("status"), AnimeStatus), rating_overall=p["rating"], note=p["note"], start_date=p["start_date"], end_date=p["end_date"], poster_url=p["poster_url"], seasons=_season_rows(group, AnimeSeason, AnimeEpisode, AnimeStatus))
    p = _parent_fields(group)
    return TVShow(title=p["title"], sort_title=p["sort_title"], source=p["source"], external_id=p["external_id"], status=_status(row.get("status"), TVShowStatus), rating_overall=p["rating"], note=p["note"], start_date=p["start_date"], end_date=p["end_date"], poster_url=p["poster_url"], seasons=_season_rows(group, TVSeason, TVEpisode, TVShowStatus))
