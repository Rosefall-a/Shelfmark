"""Matching an imported movie/TV list against the library, and applying it.

Same rules as the MyAnimeList import: a title already on the site (same kind,
same title, same year when both have one) is kept exactly as it is unless the
user picks it, and taking the file's data changes only what the file states.
Metadata from TMDB only fills blank fields."""
# pylint: disable=missing-class-docstring,missing-function-docstring,unused-argument

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models.movies import Movie, MovieStatus
from src.database.models.tv_show import TVSeason, TVShow, TVShowStatus
from src.features.imports.lists import ImportedTitle, fill_blanks, lookup_tmdb


@dataclass
class ListMatch:
    imported: ImportedTitle
    existing: Any | None


def _label(status: Any) -> str:
    return str(getattr(status, "value", status)).replace("_", " ").title()


def _sort_title(title: str) -> str:
    lowered = title.strip().lower()
    for article in ("the ", "an ", "a "):
        if lowered.startswith(article):
            return lowered[len(article) :]
    return lowered


async def match_titles(
    db: AsyncSession, user_id: Any, items: list[ImportedTitle]
) -> list[ListMatch]:
    movies = (
        (
            await db.execute(
                select(Movie).where(Movie.user_id == user_id, Movie.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    shows = (
        (
            await db.execute(
                select(TVShow)
                .where(TVShow.user_id == user_id, TVShow.deleted_at.is_(None))
                .options(selectinload(TVShow.seasons))
            )
        )
        .scalars()
        .all()
    )

    def index(rows: list[Any], date_field: str) -> dict[tuple[str, int | None], Any]:
        out: dict[tuple[str, int | None], Any] = {}
        for r in rows:
            day = getattr(r, date_field)
            out[(r.title.lower(), day.year if day else None)] = r
        return out

    by_kind = {
        "movie": index(list(movies), "release_date"),
        "tv": index(list(shows), "first_air_date"),
    }
    matches = []
    for item in items:
        known = by_kind[item.kind]
        # a title added by an earlier import has no date until metadata fills it,
        # so a stored title without a year still counts as the same title
        found = known.get((item.title.lower(), item.year)) or known.get((item.title.lower(), None))
        if found is None and item.year is None:
            found = next((v for (t, _), v in known.items() if t == item.title.lower()), None)
        matches.append(ListMatch(item, found))
    return matches


def differences(existing: Any, item: ImportedTitle) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(field: str, site: Any, imported: Any) -> None:
        if imported is not None and site != imported:
            out.append(
                {"field": field, "site": None if site is None else str(site), "mal": str(imported)}
            )

    add("Status", _label(existing.status), _label(item.status))
    add(
        "Score",
        None if existing.rating_overall is None else float(existing.rating_overall),
        None if item.rating is None else float(item.rating),
    )
    if item.rewatches:
        add("Rewatches", existing.rewatches, item.rewatches)
    if item.favorite:
        add("Favorite", "yes" if existing.favorite else "no", "yes")
    return out


def apply_tracking(existing: Any, item: ImportedTitle) -> None:
    existing.status = (MovieStatus if item.kind == "movie" else TVShowStatus)(item.status)
    if item.rating is not None:
        existing.rating_overall = item.rating
    if item.rewatches:
        existing.rewatches = item.rewatches
    if item.favorite:
        existing.favorite = True
    if item.watched_on and item.status == "WATCHED":
        existing.end_date = item.watched_on


def new_title(user_id: Any, item: ImportedTitle) -> Movie | TVShow:
    common: dict[str, Any] = {
        "user_id": user_id,
        "title": item.title,
        "sort_title": _sort_title(item.title),
        "source": "List import",
        "rating_overall": item.rating,
        "favorite": item.favorite,
        "rewatches": item.rewatches,
        "genres": item.genres,
        "studios": [],
        "countries": [],
        "languages": [],
        "tags": [],
        "features": [],
        "locked_fields": [],
        "end_date": item.watched_on if item.status == "WATCHED" else None,
    }
    if item.kind == "movie":
        movie = Movie(status=MovieStatus(item.status), runtime_minutes=item.runtime, **common)
        return movie
    return TVShow(
        status=TVShowStatus(item.status),
        creators=[],
        episode_runtime_minutes=item.runtime,
        seasons=[],
        **common,
    )


class OmdbLookup:
    """Lets the importer use OMDb where it expects a TMDB client: same two
    methods, one exact lookup each."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def search(self, title: str, limit: int = 1, year: int | None = None) -> list[dict[str, Any]]:
        found = self.client.lookup(title, year, "movie")
        return [found] if found else []

    def search_tv(
        self, title: str, limit: int = 1, year: int | None = None
    ) -> list[dict[str, Any]]:
        found = self.client.lookup(title, year, "tv")
        return [found] if found else []


def _seasons_from(meta: dict[str, Any], watched: bool) -> list[TVSeason]:
    status = TVShowStatus.WATCHED if watched else TVShowStatus.WATCHLIST
    return [
        TVSeason(
            season_number=s["season_number"],
            name=s.get("name"),
            episode_count=s.get("episode_count"),
            # a series marked watched counts as fully watched, stated in the result
            episodes_watched=(s.get("episode_count") or 0) if watched else 0,
            status=status,
            air_date=_day(s.get("air_date")),
            poster_url=s.get("poster_url"),
        )
        for s in meta.get("seasons") or []
        if isinstance(s.get("season_number"), int)
    ]


def _day(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


async def fill_details(
    client: Any, touched: list[tuple[ImportedTitle, Any, bool]]
) -> dict[str, int]:
    """TMDB lookups by title and year, a few at a time, filling blank fields.
    A TV series with no seasons yet gets them from TMDB, but only when the
    import is what is adding or changing it (the flag), never for a title the
    user chose to keep as it is."""
    jobs = list({(i.kind, i.title, i.year) for i, _, _ in touched})
    if not jobs:
        return {"filled": 0, "not_found": 0, "seasons_assumed_watched": 0}
    found = await asyncio.to_thread(lookup_tmdb, client, jobs)
    filled = not_found = assumed = 0
    for item, row, may_add_seasons in touched:
        meta = found.get((item.kind, item.title, item.year))
        if not meta:
            not_found += 1
            continue
        if fill_blanks(row, item.kind, meta):
            filled += 1
        if item.kind == "tv" and may_add_seasons and not row.seasons:
            seasons = _seasons_from(meta, row.status == TVShowStatus.WATCHED)
            row.seasons.extend(seasons)
            if seasons and row.status == TVShowStatus.WATCHED:
                assumed += 1
    return {"filled": filled, "not_found": not_found, "seasons_assumed_watched": assumed}
