# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring,too-many-locals
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from src.core.config import settings


class SteamGridDBError(RuntimeError):
    """Raised when the SteamGridDB API responds unsuccessfully."""


@dataclass(slots=True)
class SteamGridDBImage:
    id: int
    type: str
    url: str
    thumb: str | None = None
    width: int | None = None
    height: int | None = None
    score: float | None = None

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "SteamGridDBImage":
        return cls(
            id=int(payload.get("id", 0)),
            type=str(payload.get("type", "unknown")),
            url=str(payload.get("url") or payload.get("image") or ""),
            thumb=str(payload.get("thumb") or payload.get("thumb_url") or payload.get("url") or ""),
            width=int(payload["width"]) if payload.get("width") is not None else None,
            height=int(payload["height"]) if payload.get("height") is not None else None,
            score=float(payload["score"]) if payload.get("score") is not None else None,
        )


class SteamGridDBClient:
    """Minimal client for the SteamGridDB v2 API.

    The API requires a bearer token. Search by a game's name and then fetch the
    available artwork for that game ID.
    """

    BASE_URL = "https://www.steamgriddb.com/api/v2"

    def __init__(
        self, api_key: str | None = None, *, session: requests.Session | None = None
    ) -> None:
        self.api_key = api_key or settings.STEAMGRIDDB_API_KEY
        if not self.api_key:
            raise SteamGridDBError(
                "STEAMGRIDDB_API_KEY is not set. Add it to your environment or .env file."
            )

        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "unnamed-tracking-app/1.0",
                "Accept": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, f"{self.BASE_URL}{path}", timeout=20, **kwargs)

        if response.status_code == 401:
            raise SteamGridDBError("SteamGridDB rejected the API key.")

        if response.status_code == 404:
            raise SteamGridDBError(f"SteamGridDB resource not found: {path}")

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"message": response.text}
            raise SteamGridDBError(
                f"SteamGridDB request failed ({response.status_code}): {payload}"
            )

        try:
            payload = response.json()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise SteamGridDBError(f"SteamGridDB returned invalid JSON for {path}") from exc

        if not isinstance(payload, dict):
            raise SteamGridDBError(
                f"SteamGridDB returned an unexpected result for {path}: {payload!r}"
            )

        return payload

    def search_games(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not query or not query.strip():
            return []

        payload = self._request(
            "GET", f"/search/autocomplete/{query.strip()}", params={"limit": limit}
        )
        results = payload.get("data") or payload.get("results") or []
        if not isinstance(results, list):
            return []
        return results

    def get_game_by_name(self, query: str) -> dict[str, Any] | None:
        results = self.search_games(query, limit=1)
        if not results:
            return None
        return results[0]

    def get_game_by_steam_appid(self, steam_app_id: int) -> dict[str, Any] | None:
        """Look up the exact SteamGridDB game linked to a Steam app ID.

        Far more reliable than name search — a name match for e.g. "Baldur's
        Gate 3" can just as easily return a fan toolkit or a DLC bundle that
        happens to rank first; the ID is unambiguous.
        """
        payload = self._request("GET", f"/games/steam/{steam_app_id}")
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    def get_game_images(
        self,
        game_id: int | str,
        image_type: str = "grids",
        dimensions: str | None = None,
        limit: int = 10,
    ) -> list[SteamGridDBImage]:
        params: dict[str, Any] = {"limit": limit}
        if dimensions:
            params["dimensions"] = dimensions

        image_type_aliases = {"grids": "grid", "heroes": "hero", "logos": "logo", "icons": "icon"}
        normalized_type = image_type_aliases.get(image_type, image_type)
        endpoint_types = {"grid": "grids", "hero": "heroes", "logo": "logos", "icon": "icons"}
        endpoint = endpoint_types.get(normalized_type)
        if endpoint is None:
            raise ValueError(f"Unsupported SteamGridDB image type: {image_type}")

        payload = self._request("GET", f"/{endpoint}/game/{game_id}", params=params)
        data = payload.get("data") or payload.get("results") or []

        if not isinstance(data, list):
            return []

        images: list[SteamGridDBImage] = []
        for item in data:
            returned_type = str(item.get("type") or "").rstrip("s")
            requested_type = image_type.rstrip("s")
            if requested_type and returned_type and returned_type != requested_type:
                continue
            images.append(SteamGridDBImage.from_api_payload(item))

        return images

    def fetch_images_for_game(
        self, query: str, image_type: str = "grids", **kwargs: Any
    ) -> list[SteamGridDBImage]:
        result = self.get_game_by_name(query)
        if result is None:
            raise SteamGridDBError(f"No SteamGridDB match found for: {query!r}")

        game_id = result.get("id") or result.get("game_id")
        if game_id is None:
            raise SteamGridDBError(f"SteamGridDB result for {query!r} had no game ID.")

        return self.get_game_images(int(game_id), image_type=image_type, **kwargs)


client: SteamGridDBClient | None = None
