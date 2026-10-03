# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

import time
from typing import Any

import requests

from src.features.metadata.rate_limit import throttle

_BASE_URL = "https://kitsu.io/api/edge"
_EPISODE_PAGE_SIZE = 20

# Same shape as anilist.py/jikan.py's retry+throttle — see rate_limit.py
# for why a shared, process-wide gap matters here even though Kitsu
# hasn't been observed rate-limiting yet: the several background loops
# that walk the anime library can still burst it the same way they did
# AniList and Jikan.
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 10.0
_PACING_SECONDS = 0.4


class KitsuError(RuntimeError):
    """Raised when Kitsu responds unsuccessfully."""


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


class KitsuClient:
    """Minimal client for Kitsu's public, keyless JSON:API — the third
    episode-data source alongside Jikan and AniList. Kitsu's own episode
    endpoint carries a real per-episode thumbnail (Jikan has none at
    all) plus a synopsis and air date, so it's a genuine third chance to
    fill in whatever the other two are still missing, not just a
    duplicate of one of them."""

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        for attempt in range(_MAX_RETRIES + 1):
            throttle("kitsu", _PACING_SECONDS)
            try:
                response = self.session.get(f"{_BASE_URL}{path}", params=params, timeout=15)
            except requests.RequestException as exc:
                raise KitsuError(f"Could not reach Kitsu: {exc}") from exc
            if response.status_code == 429:
                if attempt >= _MAX_RETRIES:
                    break
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.replace(".", "", 1).isdigit()
                    else _BASE_BACKOFF_SECONDS * (2**attempt)
                )
                time.sleep(min(delay, _MAX_BACKOFF_SECONDS))
                continue
            if response.status_code >= 400:
                raise KitsuError(
                    f"Kitsu request failed ({response.status_code}): {response.text[:200]}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise KitsuError("Kitsu returned invalid JSON.") from exc
        raise KitsuError("Kitsu is rate-limiting requests right now — wait a bit and try again.")

    def find_exact(self, title: str, year: int | None = None) -> str | None:
        """Searches by title and returns the id only when a result's own
        title matches exactly (case/whitespace-insensitive) — the same
        safety net `_find_by_exact_title` uses for AniList, so a search
        miss never silently attaches episode data from an unrelated
        show. Checks both the canonical title and any alternate titles
        Kitsu lists, since its canonical title is sometimes the Japanese
        romaji rather than the English name this app stores.

        Title alone is not always enough to disambiguate, though: Kitsu's
        `en_us` field for a franchise's TV series can be the bare title
        with no year/season qualifier (e.g. "JoJo's Bizarre Adventure"
        for the 2012 TV series) while the real match — an earlier OVA of
        the same franchise — carries the qualifier instead (e.g. "JoJo's
        Bizarre Adventure (1993)"), so an exact-title check alone picks
        the wrong one. When `year` is given, a candidate is only accepted
        if its own start year is within 1 of it; a title match with a
        wildly different year is treated as no match rather than a
        confident one."""
        payload = self._get("/anime", {"filter[text]": title, "page[limit]": "5"})

        target = _normalize_title(title)
        for entry in payload.get("data") or []:
            attrs = entry.get("attributes") or {}
            candidates = [attrs.get("canonicalTitle")] + list((attrs.get("titles") or {}).values())
            if not any(c and _normalize_title(c) == target for c in candidates):
                continue
            if year is not None:
                start_date = attrs.get("startDate") or ""
                candidate_year = int(start_date[:4]) if start_date[:4].isdigit() else None
                if candidate_year is None or abs(candidate_year - year) > 1:
                    continue
            return str(entry["id"])
        return None

    def episodes(self, kitsu_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self._get(
                f"/anime/{kitsu_id}/episodes",
                {"page[limit]": str(_EPISODE_PAGE_SIZE), "page[offset]": str(offset)},
            )
            entries = payload.get("data") or []
            for entry in entries:
                attrs = entry.get("attributes") or {}
                number = attrs.get("number")
                if number is None:
                    continue
                thumb = attrs.get("thumbnail") or {}
                # Kitsu uses the same literal "Untitled" placeholder
                # AniList does when the episode has no real title — kept
                # as None so a richer source (Jikan, TMDB) still gets a
                # chance to fill it in on merge, instead of "Untitled"
                # counting as an already-known title forever.
                title = attrs.get("canonicalTitle")
                if title and title.strip().lower() == "untitled":
                    title = None
                results.append(
                    {
                        "episode_number": number,
                        "title": title,
                        "description": attrs.get("synopsis") or None,
                        "air_date": attrs.get("airdate"),
                        "runtime_minutes": attrs.get("length"),
                        "still_url": thumb.get("original"),
                    }
                )
            if len(entries) < _EPISODE_PAGE_SIZE:
                break
            offset += _EPISODE_PAGE_SIZE
            if offset > 2000:
                break  # matches this codebase's other generous-but-bounded sync caps
        return results
