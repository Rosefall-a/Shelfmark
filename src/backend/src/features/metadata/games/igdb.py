# pylint: disable=missing-module-docstring,missing-function-docstring,too-many-locals,too-few-public-methods
from __future__ import annotations

import time
from typing import Any

import requests


class IGDBError(RuntimeError):
    """Raised when IGDB (or the Twitch OAuth token exchange it rides on)
    responds unsuccessfully."""


class IGDBClient:
    """Minimal client for the IGDB v4 API. IGDB auth rides on Twitch's
    developer platform — a client_id/client_secret pair from a registered
    Twitch app, exchanged for a short-lived app access token via the
    client_credentials OAuth flow (no per-user login involved)."""

    TOKEN_URL = "https://id.twitch.tv/oauth2/token"
    BASE_URL = "https://api.igdb.com/v4"

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise IGDBError("IGDB_CLIENT_ID/IGDB_CLIENT_SECRET are not configured on the server.")
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _authenticate(self) -> str:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        try:
            response = self.session.post(
                self.TOKEN_URL,
                params={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise IGDBError(f"Could not reach Twitch's OAuth service: {exc}") from exc

        if response.status_code >= 400:
            raise IGDBError(
                f"Twitch rejected the IGDB client credentials ({response.status_code})."
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise IGDBError("Twitch's token response had no access_token.")
        self._access_token = token
        # renew a little early rather than exactly at expiry
        self._token_expires_at = time.time() + int(payload.get("expires_in", 3600)) - 60
        return token

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        token = self._authenticate()
        safe_query = query.replace('"', "'")
        body = (
            f'search "{safe_query}"; '
            "fields name,summary,first_release_date,url,cover.url,genres.name,"
            "involved_companies.company.name,involved_companies.developer,"
            "involved_companies.publisher,collection.name,franchises.name; "
            f"limit {limit};"
        )
        try:
            response = self.session.post(
                f"{self.BASE_URL}/games",
                headers={
                    "Client-ID": self.client_id,
                    "Authorization": f"Bearer {token}",
                },
                data=body,
                timeout=15,
            )
        except requests.RequestException as exc:
            raise IGDBError(f"Could not reach IGDB: {exc}") from exc

        if response.status_code >= 400:
            raise IGDBError(f"IGDB search failed ({response.status_code}): {response.text[:200]}")

        try:
            games = response.json()
        except ValueError as exc:
            raise IGDBError("IGDB returned invalid JSON.") from exc

        results: list[dict[str, Any]] = []
        for game in games:
            developer = None
            publisher = None
            for involved in game.get("involved_companies", []) or []:
                company = (involved.get("company") or {}).get("name")
                if not company:
                    continue
                if involved.get("developer") and developer is None:
                    developer = company
                if involved.get("publisher") and publisher is None:
                    publisher = company

            cover_url = (game.get("cover") or {}).get("url")
            if cover_url:
                # IGDB returns protocol-relative thumbnail-sized URLs by default
                cover_url = (
                    "https:" + cover_url.replace("t_thumb", "t_cover_big")
                    if cover_url.startswith("//")
                    else cover_url
                )

            release_ts = game.get("first_release_date")
            # IGDB's "collection" (e.g. "Dark Souls Collection") is the
            # closest match to a series grouping; a franchise name is a
            # reasonable fallback when a game has no collection set
            series = (game.get("collection") or {}).get("name")
            if not series:
                franchises = game.get("franchises") or []
                series = franchises[0].get("name") if franchises else None
            results.append(
                {
                    "id": game.get("id"),
                    "name": game.get("name"),
                    "summary": game.get("summary"),
                    "release_date": (
                        time.strftime("%Y-%m-%d", time.gmtime(release_ts)) if release_ts else None
                    ),
                    "developer": developer,
                    "publisher": publisher,
                    "series": series,
                    "genres": [g["name"] for g in game.get("genres", []) if g.get("name")],
                    "cover_url": cover_url,
                    "url": f"https://www.igdb.com/games/{game['id']}" if game.get("id") else None,
                }
            )
        return results
