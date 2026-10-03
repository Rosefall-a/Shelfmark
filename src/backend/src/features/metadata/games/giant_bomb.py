# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

from typing import Any

import requests


class GiantBombError(RuntimeError):
    """Raised when the Giant Bomb API responds unsuccessfully."""


class GiantBombClient:
    """Minimal client for the Giant Bomb API — general game metadata,
    keyed by a free per-user API key (giantbomb.com/api)."""

    BASE_URL = "https://www.giantbomb.com/api"

    def __init__(self, api_key: str, *, session: requests.Session | None = None) -> None:
        if not api_key:
            raise GiantBombError("No Giant Bomb API key provided.")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "unnamed-tracking-app/1.0")

    def _get(self, path: str, **params: Any) -> Any:
        params = {**params, "api_key": self.api_key, "format": "json"}
        try:
            response = self.session.get(f"{self.BASE_URL}/{path}", params=params, timeout=15)
        except requests.RequestException as exc:
            raise GiantBombError(f"Could not reach Giant Bomb: {exc}") from exc

        if response.status_code >= 400:
            raise GiantBombError(f"Giant Bomb request failed ({response.status_code}).")

        try:
            payload = response.json()
        except ValueError as exc:
            raise GiantBombError("Giant Bomb returned invalid JSON.") from exc

        if payload.get("error") and payload.get("error") != "OK":
            raise GiantBombError(f"Giant Bomb rejected the request: {payload['error']}")
        return payload

    def validate(self) -> dict[str, Any]:
        self._get("search/", query="test", resources="game", limit=1)
        return {"validated": True}

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        payload = self._get("search/", query=query, resources="game", limit=limit)
        results = payload.get("results") or []
        if not isinstance(results, list):
            return []

        games: list[dict[str, Any]] = []
        for game in results:
            image = game.get("image") or {}
            games.append(
                {
                    "id": game.get("id"),
                    "name": game.get("name"),
                    "deck": game.get("deck"),
                    "original_release_date": game.get("original_release_date"),
                    "image_url": image.get("medium_url") or image.get("small_url"),
                    "url": game.get("site_detail_url"),
                }
            )
        return games
