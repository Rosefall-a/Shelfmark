from __future__ import annotations

from typing import Any

import requests


class ScreenScraperError(RuntimeError):
    """Raised when the ScreenScraper API responds unsuccessfully."""


class ScreenScraperClient:
    """Minimal client for the ScreenScraper.fr API — retro box art and
    screenshots. Needs both an app-registered dev account (devid/devpassword,
    shared server-wide) and a personal screenscraper.fr login
    (ssid/sspassword, per user)."""

    BASE_URL = "https://www.screenscraper.fr/api2"

    def __init__(
        self,
        devid: str,
        devpassword: str,
        ssid: str,
        sspassword: str,
        *,
        session: requests.Session | None = None,
    ) -> None:
        if not devid or not devpassword:
            raise ScreenScraperError(
                "ScreenScraper devid/devpassword are not configured on the server."
            )
        if not ssid or not sspassword:
            raise ScreenScraperError("No ScreenScraper account credentials provided.")
        self.devid = devid
        self.devpassword = devpassword
        self.ssid = ssid
        self.sspassword = sspassword
        self.session = session or requests.Session()

    def _auth_params(self) -> dict[str, str]:
        return {
            "devid": self.devid,
            "devpassword": self.devpassword,
            "softname": "unnamed-tracking-app",
            "ssid": self.ssid,
            "sspassword": self.sspassword,
            "output": "json",
        }

    def validate(self) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{self.BASE_URL}/ssuserInfos.php", params=self._auth_params(), timeout=15
            )
        except requests.RequestException as exc:
            raise ScreenScraperError(f"Could not reach ScreenScraper: {exc}") from exc

        if response.status_code in (401, 403):
            raise ScreenScraperError("ScreenScraper rejected the account credentials.")
        if response.status_code >= 400:
            raise ScreenScraperError(f"ScreenScraper request failed ({response.status_code}).")
        return {"validated": True}

    def find_art(self, title: str) -> dict[str, Any] | None:
        if not title.strip():
            return None
        try:
            response = self.session.get(
                f"{self.BASE_URL}/jeuRecherche.php",
                params={**self._auth_params(), "recherche": title},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise ScreenScraperError(f"Could not reach ScreenScraper: {exc}") from exc

        if response.status_code >= 400:
            return None

        try:
            payload = response.json()
        except ValueError:
            return None

        games = ((payload.get("response") or {}).get("jeux")) or []
        if not isinstance(games, list) or not games:
            return None

        medias = games[0].get("medias") or []
        box_art_url = next((m.get("url") for m in medias if m.get("type") == "box-2D"), None)
        screenshot_url = next((m.get("url") for m in medias if m.get("type") == "ss"), None)
        if not box_art_url and not screenshot_url:
            return None
        return {"box_art_url": box_art_url, "screenshot_url": screenshot_url}
