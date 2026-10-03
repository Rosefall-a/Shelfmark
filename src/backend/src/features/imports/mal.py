"""MyAnimeList list export -> anime entries.

MAL's "Export" gives an XML file (often gzipped) with one <anime> per list
entry. Only what the file states is used: the status, the episodes watched,
the score, the rewatch count, the dates, the tags and the comment. Posters,
genres and the like are not in the file, so the entry keeps MAL's id and the
existing metadata refresh fills the rest in afterwards.

A "Completed" entry that lists no watched episodes is taken as fully watched,
which is what Completed means on MAL, and is counted in the result so it is
never silent."""
# pylint: disable=missing-class-docstring,too-many-instance-attributes,missing-function-docstring

from __future__ import annotations

import gzip
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.database.models.anime import AnimeStatus

MAX_BYTES = 30 * 1024 * 1024

_STATUS = {
    "watching": AnimeStatus.IN_PROGRESS,
    "completed": AnimeStatus.WATCHED,
    "on-hold": AnimeStatus.BACKLOG,
    "on hold": AnimeStatus.BACKLOG,
    "dropped": AnimeStatus.DROPPED,
    "plan to watch": AnimeStatus.WATCHLIST,
    # the numeric codes some exporters write
    "1": AnimeStatus.IN_PROGRESS,
    "2": AnimeStatus.WATCHED,
    "3": AnimeStatus.BACKLOG,
    "4": AnimeStatus.DROPPED,
    "6": AnimeStatus.WATCHLIST,
}
# the same labels the AniList lookup stores, so a title reads the same whichever way it was added
_FORMAT = {
    "tv": "TV",
    "movie": "Movie",
    "ova": "OVA",
    "ona": "ONA",
    "special": "Special",
    "music": "Music",
}


class MalImportError(ValueError):
    pass


@dataclass
class MalEntry:
    mal_id: str
    title: str
    format: str | None
    episodes: int | None
    watched: int
    score: Decimal | None
    status: AnimeStatus
    rewatches: int
    started: date | None
    finished: date | None
    comment: str | None
    tags: list[str] = field(default_factory=list)
    assumed_complete: bool = False


def _text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    return (child.text or "").strip() if child is not None and child.text else ""


def _int(value: str) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _date(value: str) -> date | None:
    # MAL writes 0000-00-00 (or a zero month/day) for "not set"
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return None
    try:
        return date(*(int(g) for g in match.groups()))
    except ValueError:
        return None


def parse_mal_export(raw: bytes) -> list[MalEntry]:
    if raw[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
                raw = gz.read(MAX_BYTES + 1)
        except OSError as exc:
            raise MalImportError("The file looks gzipped but could not be unpacked.") from exc
    if len(raw) > MAX_BYTES:
        raise MalImportError("The file is too large to be a list export.")
    # entity declarations are how XML "bombs" are built, and a list export
    # never has any
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise MalImportError(
            "This XML has a document type declaration, which a MyAnimeList export never has."
        )
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise MalImportError(f"Could not read the file as XML: {exc}") from exc
    if root.tag != "myanimelist":
        raise MalImportError("This is not a MyAnimeList export (no <myanimelist> element).")

    entries: list[MalEntry] = []
    for node in root.findall("anime"):
        title = _text(node, "series_title")
        mal_id = _text(node, "series_animedb_id")
        if not title or not mal_id:
            continue
        total = _int(_text(node, "series_episodes")) or None
        watched = _int(_text(node, "my_watched_episodes"))
        status = _STATUS.get(_text(node, "my_status").lower(), AnimeStatus.WATCHLIST)
        assumed = status is AnimeStatus.WATCHED and watched == 0 and total is not None
        if assumed and total is not None:
            watched = total
        if total is not None:
            watched = min(watched, total)
        score = _int(_text(node, "my_score"))
        tags = [t.strip() for t in _text(node, "my_tags").split(",") if t.strip()]
        entries.append(
            MalEntry(
                mal_id=mal_id,
                title=title,
                format=_FORMAT.get(_text(node, "series_type").lower()),
                episodes=total,
                watched=watched,
                score=Decimal(min(10, score)) if score else None,
                status=status,
                rewatches=_int(_text(node, "my_times_watched")),
                started=_date(_text(node, "my_start_date")),
                finished=_date(_text(node, "my_finish_date")),
                comment=_text(node, "my_comments") or None,
                tags=tags,
                assumed_complete=assumed,
            )
        )
    return entries
