# pylint: disable=missing-module-docstring,too-many-locals,too-few-public-methods
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

_BASE_URL = "https://api4.thetvdb.com/v4"


class TVDBError(RuntimeError):
    """Raised when TheTVDB responds unsuccessfully or the API key is missing."""


class TVDBClient:
    """Minimal client for TheTVDB v4 — the only real franchise/relations
    data source for TV shows (TMDB has no collection concept for TV).
    Session-based auth: POST /login exchanges the deployment's API key for
    a bearer token valid one month; this client re-logs-in lazily on the
    first request and once more on a 401, rather than persisting the
    token anywhere."""

    def __init__(self, api_key: str | None, *, session: requests.Session | None = None) -> None:
        if not api_key:
            raise TVDBError("TVDB_API_KEY is not configured on the server.")
        self.api_key = api_key
        self.session = session or requests.Session()
        self._token: str | None = None

    def _login(self) -> None:
        try:
            response = self.session.post(
                f"{_BASE_URL}/login", json={"apikey": self.api_key}, timeout=15
            )
        except requests.RequestException as exc:
            raise TVDBError(f"Could not reach TheTVDB: {exc}") from exc
        if response.status_code >= 400:
            raise TVDBError(f"TheTVDB login failed ({response.status_code}): {response.text[:200]}")
        try:
            self._token = response.json()["data"]["token"]
        except (ValueError, KeyError) as exc:
            raise TVDBError("TheTVDB login returned an unexpected response.") from exc

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._token:
            self._login()
        for attempt in range(2):
            try:
                response = self.session.get(
                    f"{_BASE_URL}{path}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    params=params,
                    timeout=15,
                )
            except requests.RequestException as exc:
                raise TVDBError(f"Could not reach TheTVDB: {exc}") from exc
            if response.status_code == 401 and attempt == 0:
                self._login()
                continue
            if response.status_code >= 400:
                raise TVDBError(
                    f"TheTVDB request failed ({response.status_code}): {response.text[:200]}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise TVDBError("TheTVDB returned invalid JSON.") from exc
        raise TVDBError("TheTVDB request failed after re-authenticating.")

    def _series_base(self, series_id: int) -> dict[str, Any]:
        return self._get(f"/series/{series_id}").get("data") or {}

    def relations(self, title: str, limit: int = 12) -> dict[str, Any]:
        """Search for `title`, then walk its best match's official lists
        (TheTVDB's franchise grouping — e.g. the MCU or Arrowverse) to
        find the other series in the same franchise. Returns an empty
        related list, not an error, when the show isn't on any list —
        most series simply aren't part of a franchise."""
        search = self._get("/search", {"query": title, "type": "series", "limit": 3})
        candidates = search.get("data") or []
        if not candidates:
            return {"listName": None, "related": []}
        best = candidates[0]
        series_id = best.get("tvdb_id")
        if not series_id:
            return {"listName": None, "related": []}

        extended = self._get(f"/series/{series_id}/extended").get("data") or {}
        lists = extended.get("lists") or []
        franchise_list = next((l for l in lists if l.get("isOfficial")), None) or (
            lists[0] if lists else None
        )
        if not franchise_list:
            return {"listName": None, "related": []}

        list_data = self._get(f"/lists/{franchise_list['id']}/extended").get("data") or {}
        entities = list_data.get("entities") or []
        related_ids = [
            e["seriesId"]
            for e in entities
            if e.get("seriesId") and str(e["seriesId"]) != str(series_id)
        ][:limit]

        related: list[dict[str, Any]] = []
        if related_ids:
            with ThreadPoolExecutor(max_workers=min(8, len(related_ids))) as executor:
                for series in executor.map(self._series_base, related_ids):
                    if not series.get("name"):
                        continue
                    related.append(
                        {
                            "id": series.get("id"),
                            "title": series.get("name"),
                            "year": series.get("year"),
                            "poster_url": series.get("image"),
                        }
                    )
        return {"listName": franchise_list.get("name"), "related": related}
