"""Movie and TV lists from other sites: Letterboxd and IMDb exports.

- Letterboxd: the export ZIP (watched, ratings, diary, watchlist, liked films)
  or one of its CSV files. Films only.
- IMDb: a ratings or watchlist export CSV. Movies and TV series; episodes,
  games and the like are skipped and counted.

Only what the file states is used. A rating means it was watched. Letterboxd
rates 0.5 to 5 and is doubled onto the app's 10-point scale. A TV series that
was rated or marked watched has its seasons filled in from TMDB and counted as
fully watched, which is stated in the result, because a rating on its own does
not say how far someone got. Posters, genres and the like come from TMDB by
title and year afterwards, and only fill fields that are still blank."""
# pylint: disable=missing-class-docstring,too-many-instance-attributes,missing-function-docstring,too-many-locals,too-many-branches,broad-exception-caught

from __future__ import annotations

import csv
import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

MAX_BYTES = 30 * 1024 * 1024
_MOVIE_TYPES = {"movie", "tvmovie", "short", "tvshort", "video", "tvspecial"}
_TV_TYPES = {"tvseries", "tvminiseries"}


class ListImportError(ValueError):
    pass


@dataclass
class ImportedTitle:
    kind: str  # "movie" | "tv"
    title: str
    year: int | None
    status: str  # "WATCHED" | "WATCHLIST"
    rating: Decimal | None = None
    favorite: bool = False
    rewatches: int = 0
    watched_on: date | None = None
    genres: list[str] = field(default_factory=list)
    runtime: int | None = None

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.title.lower()}:{self.year or ''}"


def _rows(raw: bytes) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    return [
        {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        for row in csv.DictReader(io.StringIO(text))
    ]


def _year(value: str) -> int | None:
    match = re.search(r"\d{4}", value or "")
    return int(match.group()) if match else None


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _files(raw: bytes, filename: str) -> dict[str, bytes]:
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                total = sum(i.file_size for i in archive.infolist())
                if total > MAX_BYTES * 3:
                    raise ListImportError("The archive is too large to be a list export.")
                return {
                    i.filename.lower(): archive.read(i)
                    for i in archive.infolist()
                    if i.filename.lower().endswith(".csv") and not i.is_dir()
                }
        except zipfile.BadZipFile as exc:
            raise ListImportError("This looks like a zip file but could not be opened.") from exc
    return {filename.lower(): raw}


def parse_letterboxd(raw: bytes, filename: str = "") -> list[ImportedTitle]:
    zipped = raw[:2] == b"PK"
    files = _files(raw, filename)
    titles: dict[tuple[str, int | None], ImportedTitle] = {}

    def entry(row: dict[str, str]) -> ImportedTitle | None:
        name = row.get("Name") or ""
        if not name:
            return None
        year = _year(row.get("Year", ""))
        key = (name.lower(), year)
        if key not in titles:
            titles[key] = ImportedTitle("movie", name, year, "WATCHLIST")
        return titles[key]

    def find(base: str) -> list[dict[str, str]] | None:
        # in the zip the files have exact names (custom lists live under
        # lists/); a single uploaded file is recognised by its name
        for name, data in files.items():
            leaf = name.rsplit("/", 1)[-1]
            if "lists/" in name:
                continue
            if (leaf == f"{base}.csv") if zipped else (base in leaf):
                return _rows(data)
        return None

    def score(value: str) -> Decimal | None:
        try:
            return Decimal(value) * 2 if value else None
        except ArithmeticError:
            return None

    watchlist, watched, ratings, diary = (
        find("watchlist"),
        find("watched"),
        find("ratings"),
        find("diary"),
    )
    if all(x is None for x in (watchlist, watched, ratings, diary)) and not zipped:
        watched = _rows(
            next(iter(files.values()))
        )  # an unrecognised single file: taken as films watched
    for row in watchlist or []:
        entry(row)
    for row in watched or []:
        if item := entry(row):
            item.status = "WATCHED"
    for row in ratings or []:
        if item := entry(row):
            item.status = "WATCHED"
            item.rating = score(row.get("Rating", "")) or item.rating
    for row in diary or []:
        if item := entry(row):
            item.status = "WATCHED"
            item.rating = item.rating or score(row.get("Rating", ""))
            if row.get("Rewatch", "").lower() == "yes":
                item.rewatches += 1
            seen = _day(row.get("Watched Date", ""))
            if seen and (item.watched_on is None or seen > item.watched_on):
                item.watched_on = seen
    for name, data in files.items():
        if name.endswith("likes/films.csv"):
            for row in _rows(data):
                if item := entry(row):
                    item.favorite = True
    if not titles:
        raise ListImportError(
            "No Letterboxd data found. Use the zip from Letterboxd's data export, or one of its CSV files."
        )
    return list(titles.values())


def parse_imdb(raw: bytes) -> tuple[list[ImportedTitle], int]:
    rows = _rows(raw)
    if not rows or "Const" not in rows[0]:
        raise ListImportError("This does not look like an IMDb export (no Const column).")
    out: list[ImportedTitle] = []
    skipped = 0
    for row in rows:
        kind_raw = row.get("Title Type", "").replace(" ", "").lower()
        if kind_raw in _MOVIE_TYPES:
            kind = "movie"
        elif kind_raw in _TV_TYPES:
            kind = "tv"
        else:
            skipped += 1
            continue
        title = row.get("Title") or row.get("Original Title") or ""
        if not title:
            skipped += 1
            continue
        rating: Decimal | None = None
        if row.get("Your Rating"):
            try:
                rating = Decimal(row["Your Rating"])
            except ArithmeticError:
                rating = None
        runtime = row.get("Runtime (mins)", "")
        out.append(
            ImportedTitle(
                kind=kind,
                title=title,
                year=_year(row.get("Year", "")),
                status="WATCHED" if row.get("Your Rating") else "WATCHLIST",
                rating=rating,
                watched_on=_day(row.get("Date Rated", "")),
                genres=[g.strip() for g in row.get("Genres", "").split(",") if g.strip()],
                runtime=int(runtime) if runtime.isdigit() else None,
            )
        )
    if not out:
        raise ListImportError("No movies or TV series were found in this file.")
    return out, skipped


# ---------------------------------------------------------------- metadata
_MOVIE_FILL = (
    ("description", "overview"),
    ("release_date", "release_date"),
    ("runtime_minutes", "runtime_minutes"),
    ("director", "director"),
    ("writer", "writer"),
    ("studios", "studios"),
    ("countries", "countries"),
    ("languages", "languages"),
    ("genres", "genres"),
    ("poster_url", "poster_url"),
    ("backdrop_url", "backdrop_url"),
    ("tmdb_score", "vote_average"),
)
_TV_FILL = (
    ("description", "overview"),
    ("first_air_date", "first_air_date"),
    ("episode_runtime_minutes", "episode_runtime_minutes"),
    ("creators", "creators"),
    ("studios", "studios"),
    ("countries", "countries"),
    ("languages", "languages"),
    ("genres", "genres"),
    ("poster_url", "poster_url"),
    ("backdrop_url", "backdrop_url"),
    ("tmdb_score", "vote_average"),
)


def _to_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def fill_blanks(item: Any, kind: str, meta: dict[str, Any]) -> bool:
    changed = False
    for attr, key in _MOVIE_FILL if kind == "movie" else _TV_FILL:
        value = meta.get(key)
        if value in (None, "", []) or getattr(item, attr, None) not in (None, "", []):
            continue
        if attr in ("release_date", "first_air_date"):
            value = _to_date(value)
            if value is None:
                continue
        setattr(item, attr, value)
        changed = True
    return changed


def lookup_tmdb(
    client: Any, wanted: list[tuple[str, str, int | None]]
) -> dict[tuple[str, str, int | None], dict[str, Any]]:
    """One TMDB lookup per (kind, title, year), a few at a time. A title TMDB
    does not know, or a request that fails, is simply absent from the result."""

    def one(
        job: tuple[str, str, int | None],
    ) -> tuple[tuple[str, str, int | None], dict[str, Any] | None]:
        kind, title, year = job
        search = client.search if kind == "movie" else client.search_tv
        try:
            found = search(title, 1, year) or (search(title, 1) if year else [])
        except Exception:  # noqa: BLE001, one failed lookup must not stop the rest
            return job, None
        return job, found[0] if found else None

    with ThreadPoolExecutor(max_workers=6) as pool:
        return {job: meta for job, meta in pool.map(one, wanted) if meta}
