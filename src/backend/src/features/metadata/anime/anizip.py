"""ani.zip: a free, keyless mapping service that joins AniList ids to
TheTVDB/AniDB episode data. It is the best source for currently airing
shows: real episode titles, synopses, screenshots and an exact air time
(`airDateUtc`) usually appear within hours of an episode airing, which
Jikan (no images), AniList (thin streaming list) and Kitsu (often late)
do not manage between them."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests

from src.features.metadata.rate_limit import throttle

_URL = "https://api.ani.zip/mappings"
_PACING_SECONDS = 0.4
_MAX_RETRIES = 2


class AniZipError(RuntimeError):
    """Raised when ani.zip cannot be reached or answers with an error."""


def _title(raw: dict[str, Any]) -> str | None:
    titles = raw.get("title") or {}
    value = titles.get("en") or titles.get("x-jat") or titles.get("ja")
    if not value:
        return None
    # ani.zip stores apostrophes as backticks
    return str(value).replace("`", "'").strip() or None


def _air_at(raw: dict[str, Any]) -> int | None:
    stamp = raw.get("airDateUtc")
    if not stamp:
        return None
    try:
        return int(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _description(raw: dict[str, Any]) -> str | None:
    text = raw.get("overview") or raw.get("summary")
    if not text:
        return None
    # the summary variant ends with a "Source: ..." credit line
    text = str(text).replace("`", "'").split("\nSource:", maxsplit=1)[0].strip()
    return text or None


class AniZipClient:
    def __init__(self, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def _get(self, anilist_id: str) -> dict[str, Any]:
        last_error = "unknown error"
        for attempt in range(_MAX_RETRIES + 1):
            throttle("anizip", _PACING_SECONDS)
            try:
                response = self.session.get(_URL, params={"anilist_id": anilist_id}, timeout=15)
            except requests.RequestException as exc:
                raise AniZipError(f"Could not reach ani.zip: {exc}") from exc
            if response.status_code == 404:
                return {}
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"status {response.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code != 200:
                raise AniZipError(f"ani.zip request failed ({response.status_code})")
            try:
                data = response.json()
            except ValueError as exc:
                raise AniZipError("ani.zip returned something that is not JSON") from exc
            return data if isinstance(data, dict) else {}
        raise AniZipError(f"ani.zip is unavailable right now ({last_error})")

    def lookup(self, anilist_id: str) -> dict[str, Any]:
        """One request, everything ani.zip knows about this AniList entry:
        its episodes (numeric keys up to the entry's own episode count, never
        the `S1`-style special keys and never a later season that TheTVDB
        files under the same show), the entry's episode count, and the exact
        Kitsu and MyAnimeList ids for it. The Kitsu id is what stops a title
        search from attaching the wrong entry (season 1's list to season 2)."""
        data = self._get(anilist_id)
        raw_episodes = data.get("episodes") or {}
        limit = data.get("episodeCount")
        results: list[dict[str, Any]] = []
        for key, raw in raw_episodes.items():
            if not str(key).isdigit() or not isinstance(raw, dict):
                continue
            number = int(key)
            if isinstance(limit, int) and 0 < limit < number:
                continue
            runtime = raw.get("runtime") or raw.get("length")
            results.append(
                {
                    "episode_number": number,
                    "title": _title(raw),
                    "description": _description(raw),
                    "air_date": raw.get("airDate") or raw.get("airdate"),
                    "runtime_minutes": int(runtime)
                    if isinstance(runtime, (int, float)) and runtime > 0
                    else None,
                    "still_url": raw.get("image"),
                    "air_at": _air_at(raw),
                }
            )
        mappings = data.get("mappings") or {}

        def mapped(name: str) -> str | None:
            value = mappings.get(name)
            return str(value) if value not in (None, "", 0) else None

        return {
            "episodes": sorted(results, key=lambda e: e["episode_number"]),
            "episode_count": limit if isinstance(limit, int) and limit > 0 else None,
            "kitsu_id": mapped("kitsu_id"),
            "mal_id": mapped("mal_id"),
        }

    def episodes(self, anilist_id: str) -> list[dict[str, Any]]:
        """Episodes of this AniList entry only (see `lookup`)."""
        episodes: list[dict[str, Any]] = self.lookup(anilist_id)["episodes"]
        return episodes
