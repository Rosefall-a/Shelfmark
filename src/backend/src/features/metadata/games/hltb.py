# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

import re
from typing import Any

import requests


class HLTBError(RuntimeError):
    """Raised when HowLongToBeat's unofficial search endpoint is unreachable
    or returns something unexpected."""


class HLTBClient:
    """HowLongToBeat has no official API — this hits the same unofficial
    search endpoint the site's own frontend uses. No API key needed, but the
    endpoint path embeds a build-specific token that occasionally changes;
    if searches start failing site-wide, that token likely needs updating."""

    SEARCH_URL = "https://howlongtobeat.com/api/search"

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent", "Mozilla/5.0 (compatible; unnamed-tracking-app/1.0)"
        )
        self.session.headers.setdefault("Content-Type", "application/json")
        self.session.headers.setdefault("Referer", "https://howlongtobeat.com/")

    def search(self, title: str, limit: int = 5) -> list[dict[str, Any]]:
        if not title.strip():
            return []

        terms = re.sub(r"[^\w\s]", " ", title).split()
        body = {
            "searchType": "games",
            "searchTerms": terms,
            "searchPage": 1,
            "size": limit,
            "searchOptions": {
                "games": {
                    "userId": 0,
                    "platform": "",
                    "sortCategory": "popular",
                    "rangeCategory": "main",
                    "rangeTime": {"min": None, "max": None},
                    "gameplay": {"perspective": "", "flow": "", "genre": ""},
                    "modifier": "",
                },
                "users": {"sortCategory": "postcount"},
                "filter": "",
                "sort": 0,
                "randomizer": 0,
            },
        }

        try:
            # short timeout — HLTB's unofficial endpoint should reject almost
            # immediately (fingerprint check, no real work happens server-side);
            # the caller (search.py) also enforces its own hard wall-clock cap
            # in case a stalled connection doesn't respect this at all
            response = self.session.post(self.SEARCH_URL, json=body, timeout=6)
        except requests.RequestException as exc:
            raise HLTBError(f"Could not reach HowLongToBeat: {exc}") from exc

        if response.status_code >= 400:
            raise HLTBError(f"HowLongToBeat search failed ({response.status_code}).")

        try:
            payload = response.json()
        except ValueError as exc:
            raise HLTBError("HowLongToBeat returned invalid JSON.") from exc

        entries = payload.get("data") or []
        results: list[dict[str, Any]] = []
        for entry in entries:
            main_seconds = entry.get("comp_main")
            results.append(
                {
                    "id": entry.get("game_id"),
                    "title": entry.get("game_name"),
                    "time_to_beat_hours": round(main_seconds / 3600, 1) if main_seconds else None,
                }
            )
        return results

    def find_time_to_beat(self, title: str) -> float | None:
        for result in self.search(title, limit=5):
            if result.get("time_to_beat_hours") is not None:
                return result["time_to_beat_hours"]
        return None
