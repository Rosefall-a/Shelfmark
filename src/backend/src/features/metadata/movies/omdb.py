# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests

_BASE_URL = "https://www.omdbapi.com/"
_RUNTIME_RE = re.compile(r"(\d+)")


class OMDBError(RuntimeError):
    """Raised when OMDb responds unsuccessfully or the API key is missing."""


def _parse_runtime(value: str | None) -> int | None:
    if not value:
        return None
    match = _RUNTIME_RE.search(value)
    return int(match.group(1)) if match else None


def _parse_list(value: str | None) -> list[str]:
    if not value or value == "N/A":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _clean(value: str | None) -> str | None:
    return None if not value or value == "N/A" else value


def _parse_date(value: str | None) -> str | None:
    """OMDb's "Released" field reads like "16 Jul 2010" — convert to
    ISO (YYYY-MM-DD) since that's what the rest of the app stores/expects."""
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%d %b %Y").date().isoformat()
    except ValueError:
        return None


class OMDBClient:
    """Minimal client for the OMDb API (IMDb-backed movie data). One
    deployment-wide API key (see database/models/app_integration_settings.py),
    no per-user auth."""

    def __init__(self, api_key: str | None, *, session: requests.Session | None = None) -> None:
        if not api_key:
            raise OMDBError("OMDB_API_KEY is not configured on the server.")
        self.api_key = api_key
        self.session = session or requests.Session()

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = self.session.get(
                _BASE_URL, params={**params, "apikey": self.api_key}, timeout=15
            )
        except requests.RequestException as exc:
            raise OMDBError(f"Could not reach OMDb: {exc}") from exc
        if response.status_code >= 400:
            raise OMDBError(f"OMDb request failed ({response.status_code}): {response.text[:200]}")
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise OMDBError("OMDb returned invalid JSON.") from exc
        if payload.get("Response") == "False":
            raise OMDBError(payload.get("Error", "OMDb returned no results."))
        return payload

    def lookup(self, title: str, year: int | None, kind: str) -> dict[str, Any] | None:
        """One exact title (and year) lookup, for importing a list: a single
        request, no candidate list. `kind` is "movie" or "tv". None when OMDb
        does not know the title. OMDb has no season list, so `seasons` is
        always empty."""
        params = {"t": title, "type": "movie" if kind == "movie" else "series"}
        if year:
            params["y"] = str(year)
        try:
            d = self._get(params)
        except OMDBError as exc:
            if "not found" in str(exc).lower():
                return None
            raise
        rating = _clean(d.get("imdbRating"))
        released = _parse_date(d.get("Released"))
        return {
            "overview": _clean(d.get("Plot")),
            "release_date": released,
            "first_air_date": released,
            "runtime_minutes": _parse_runtime(d.get("Runtime")),
            "episode_runtime_minutes": _parse_runtime(d.get("Runtime")),
            "director": _clean(d.get("Director")),
            "writer": _clean(d.get("Writer")),
            "creators": [],
            "studios": [],
            "countries": _parse_list(d.get("Country")),
            "languages": _parse_list(d.get("Language")),
            "genres": _parse_list(d.get("Genre")),
            "poster_url": _clean(d.get("Poster")),
            "vote_average": float(rating) if rating else None,
            "seasons": [],
        }

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        try:
            payload = self._get({"s": query, "type": "movie"})
        except OMDBError as exc:
            # "Movie not found!" is OMDb's normal zero-results response, not
            # a real failure — swallow only that one message so it reads as
            # an empty search instead of a scary error. Anything else (bad
            # key, rate limit, ...) propagates so the caller can surface it.
            if "not found" in str(exc).lower():
                return []
            raise
        candidates = payload.get("Search") or []

        results: list[dict[str, Any]] = []
        for candidate in candidates[:limit]:
            imdb_id = candidate.get("imdbID")
            if not imdb_id:
                continue
            try:
                details = self._get({"i": imdb_id})
            except OMDBError:
                details = candidate

            imdb_rating = _clean(details.get("imdbRating"))
            poster = _clean(details.get("Poster"))
            results.append(
                {
                    "id": imdb_id,
                    "title": _clean(details.get("Title")) or candidate.get("Title"),
                    "overview": _clean(details.get("Plot")),
                    "release_date": _parse_date(details.get("Released")),
                    "runtime_minutes": _parse_runtime(details.get("Runtime")),
                    "director": _clean(details.get("Director")),
                    "writer": _clean(details.get("Writer")),
                    "studios": [],
                    "countries": _parse_list(details.get("Country")),
                    "languages": _parse_list(details.get("Language")),
                    "genres": _parse_list(details.get("Genre")),
                    "poster_url": poster,
                    "vote_average": float(imdb_rating) if imdb_rating else None,
                    "url": f"https://www.imdb.com/title/{imdb_id}/",
                }
            )
        return results

    def search_tv(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Like `search`, but for series. OMDb's `totalSeasons` gives a
        count only — no per-season episode counts or air dates, unlike
        TMDB's `seasons` array, so this never contributes a season list."""
        if not query.strip():
            return []
        try:
            payload = self._get({"s": query, "type": "series"})
        except OMDBError as exc:
            if "not found" in str(exc).lower():
                return []
            raise
        candidates = payload.get("Search") or []

        results: list[dict[str, Any]] = []
        for candidate in candidates[:limit]:
            imdb_id = candidate.get("imdbID")
            if not imdb_id:
                continue
            try:
                details = self._get({"i": imdb_id})
            except OMDBError:
                details = candidate

            imdb_rating = _clean(details.get("imdbRating"))
            poster = _clean(details.get("Poster"))
            results.append(
                {
                    "id": imdb_id,
                    "title": _clean(details.get("Title")) or candidate.get("Title"),
                    "overview": _clean(details.get("Plot")),
                    "first_air_date": _parse_date(details.get("Released")),
                    "episode_runtime_minutes": _parse_runtime(details.get("Runtime")),
                    "creators": _parse_list(details.get("Writer")),
                    "studios": [],
                    "countries": _parse_list(details.get("Country")),
                    "languages": _parse_list(details.get("Language")),
                    "genres": _parse_list(details.get("Genre")),
                    "poster_url": poster,
                    "vote_average": float(imdb_rating) if imdb_rating else None,
                    "seasons": [],
                    "url": f"https://www.imdb.com/title/{imdb_id}/",
                }
            )
        return results
