# pylint: disable=missing-module-docstring,missing-function-docstring,too-few-public-methods
from __future__ import annotations

from typing import Any

import requests

# GOG's own storefront runs on these — no API key, no auth, same endpoints
# gog.com's search box and game pages call client-side. Separate from the
# refresh-token flow below, which is for pulling a signed-in account's
# owned-games library (deferred — no library sync built for GOG yet), not
# for searching the catalog by title.
_CATALOG_URL = "https://catalog.gog.com/v1/catalog"
_PRODUCT_URL = "https://api.gog.com/products"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; unnamed-tracking-app/1.0)"})


class GOGMetadataError(RuntimeError):
    """Raised when GOG's public catalog/product API is unreachable or returns something unexpected."""


def search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    try:
        response = _SESSION.get(
            _CATALOG_URL,
            params={"query": f"like:{query}", "limit": str(limit), "order": "desc:trending"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise GOGMetadataError(f"Could not reach GOG: {exc}") from exc
    if response.status_code >= 400:
        raise GOGMetadataError(f"GOG catalog search failed ({response.status_code}).")
    try:
        products = response.json().get("products") or []
    except ValueError as exc:
        raise GOGMetadataError("GOG returned invalid JSON.") from exc
    return products[:limit]


def get_description(product_id: str) -> str | None:
    """A short "lead" description — a separate call because the catalog
    search response doesn't include one. Best-effort: a failure here just
    means no description, not a search failure."""
    try:
        response = _SESSION.get(
            f"{_PRODUCT_URL}/{product_id}", params={"expand": "description"}, timeout=10
        )
        if response.status_code >= 400:
            return None
        return (response.json().get("description") or {}).get("lead")
    except (requests.RequestException, ValueError):
        return None


class GOGError(RuntimeError):
    """Raised when GOG's unofficial token endpoint rejects the refresh token."""


class GOGClient:
    """GOG has no public metadata API for third parties. This uses the same
    unofficial token-refresh endpoint community tools (e.g. GOGDB, Heroic
    Games Launcher) rely on to confirm a GOG account token still works —
    it does not pull library/game data yet (deferred, see Settings plan)."""

    TOKEN_URL = "https://auth.gog.com/token"
    # Public GOG Galaxy client id — not a secret, the same constant every
    # unofficial GOG client uses (community-documented).
    CLIENT_ID = "46899977096215655"
    CLIENT_SECRET = "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ecfeaa4b0eb14f6a0f6f"

    def __init__(self, refresh_token: str, *, session: requests.Session | None = None) -> None:
        if not refresh_token:
            raise GOGError("No GOG refresh token provided.")
        self.refresh_token = refresh_token
        self.session = session or requests.Session()

    def validate(self) -> dict[str, Any]:
        try:
            response = self.session.get(
                self.TOKEN_URL,
                params={
                    "client_id": self.CLIENT_ID,
                    "client_secret": self.CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise GOGError(f"Could not reach GOG: {exc}") from exc

        if response.status_code >= 400:
            raise GOGError("GOG rejected the refresh token: it may be expired or invalid.")

        try:
            payload = response.json()
        except ValueError as exc:
            raise GOGError("GOG returned an invalid token response.") from exc

        if not payload.get("access_token"):
            raise GOGError("GOG's response had no access_token.")
        return {"validated": True}
