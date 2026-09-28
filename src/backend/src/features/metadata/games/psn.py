# pylint: disable=line-too-long,missing-module-docstring
from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

# PlayStation Network has no official public API for third-party apps. This
# mirrors the same reverse-engineered "npsso" OAuth flow used by Playnite's
# PlayStation plugin and the community PSNAWP/psn-api projects: the user logs
# into playstation.com, copies the `npsso` cookie value, and we exchange it
# for a short-lived access token. Unsupported by Sony — can break without
# notice if they change the flow.
_AUTH_URL = "https://ca.account.sony.com/api/authz/v3/oauth/authorize"
_TOKEN_URL = "https://ca.account.sony.com/api/authz/v3/oauth/token"
_PROFILE_URL = "https://us-prof.np.community.playstation.net/userProfile/v1/users/me/profile2"
# Public OAuth client credentials for the PS App — not a secret tied to any
# individual account, the same constant every unofficial PSN client uses.
_CLIENT_ID = "09515159-7237-4370-9b40-3806e67c0891"
_CLIENT_SECRET = "ucPjka5tntB2KqsP"
_REDIRECT_URI = "com.scee.psxandroid.scecompcall://redirect"
_SCOPE = "psn:mobile.v2.core psn:clientapp"


class PSNError(RuntimeError):
    """Raised when Sony's PSN API rejects the npsso token or is unreachable."""


def _extract_npsso(raw: str) -> str:
    """The most common way people get their npsso is hitting Sony's own
    `https://ca.account.sony.com/api/v1/ssocookie` while logged in, which
    returns `{"npsso":"...","expires_in":...}` — pasting that whole blob
    (instead of just the value) is an easy, common mistake. Also strips
    stray surrounding quotes from copying just the value with them
    included. A plain token passes through unchanged."""
    value = raw.strip()
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("npsso"), str):
            value = parsed["npsso"].strip()
    return value.strip("'\"").strip()


class PSNClient:
    """Validates a PSN npsso token by performing the OAuth exchange and one
    lightweight authenticated read. Phase 1 only confirms the token works —
    it does not persist the resulting access/refresh tokens or import any
    library/trophy data (see the Settings plan's PSN Phase 1 boundary)."""

    def __init__(self, npsso_token: str, *, session: requests.Session | None = None) -> None:
        self.npsso_token = _extract_npsso(npsso_token)
        if not self.npsso_token:
            raise PSNError("No npsso token provided.")
        self.session = session or requests.Session()

    def _get_auth_code(self) -> str:
        try:
            response = self.session.get(
                _AUTH_URL,
                params={
                    "access_type": "offline",
                    "client_id": _CLIENT_ID,
                    "scope": _SCOPE,
                    "response_type": "code",
                    "redirect_uri": _REDIRECT_URI,
                },
                cookies={"npsso": self.npsso_token},
                allow_redirects=False,
                timeout=15,
            )
        except requests.RequestException as exc:
            raise PSNError(f"Could not reach PlayStation Network: {exc}") from exc

        if response.status_code == 401:
            raise PSNError("PlayStation rejected the npsso token: it may be expired or invalid.")

        location = response.headers.get("Location")
        if response.status_code not in (302, 303) or not location:
            raise PSNError(
                "PlayStation did not return an authorization redirect: token may be invalid."
            )

        code = parse_qs(urlparse(location).query).get("code")
        if not code:
            raise PSNError("PlayStation's redirect had no authorization code.")
        return code[0]

    def _get_access_token(self, auth_code: str) -> str:
        try:
            response = self.session.post(
                _TOKEN_URL,
                auth=(_CLIENT_ID, _CLIENT_SECRET),
                data={
                    "code": auth_code,
                    "redirect_uri": _REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "token_format": "jwt",
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise PSNError(f"Could not reach PlayStation Network: {exc}") from exc

        if response.status_code >= 400:
            raise PSNError(f"PlayStation rejected the token exchange ({response.status_code}).")

        try:
            payload = response.json()
        except ValueError as exc:
            raise PSNError("PlayStation returned an invalid token response.") from exc

        access_token = payload.get("access_token")
        if not access_token:
            raise PSNError("PlayStation's token response had no access_token.")
        return str(access_token)

    def validate(self) -> dict[str, Any]:
        """Exchange the npsso token for an access token and confirm it
        actually works with one profile read. Raises PSNError on any failure."""
        access_token = self._authenticate()

        try:
            response = self.session.get(
                _PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "onlineId,avatarUrls"},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise PSNError(f"Could not verify the PlayStation account: {exc}") from exc

        if response.status_code >= 400:
            raise PSNError(f"PlayStation profile check failed ({response.status_code}).")

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        profile = payload.get("profile") or {}
        online_id = profile.get("onlineId")
        avatar_urls = profile.get("avatarUrls") or []
        avatar_url = avatar_urls[0].get("avatarUrl") if avatar_urls else None
        return {"validated": True, "profile_name": online_id, "avatar_url": avatar_url}

    def _authenticate(self) -> str:
        auth_code = self._get_auth_code()
        return self._get_access_token(auth_code)

    def get_owned_titles(self) -> list[dict[str, Any]]:
        """The account's trophy-tracked game library — PSN has no separate
        "owned games" list independent of trophies, every title with any
        trophy activity shows up here regardless of platinum/completion."""
        access_token = self._authenticate()
        titles: list[dict[str, Any]] = []
        offset = 0
        limit = 200
        while True:
            try:
                response = self.session.get(
                    "https://m.np.playstation.com/api/gamelist/v2/users/me/titles",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"limit": limit, "offset": offset},
                    timeout=20,
                )
            except requests.RequestException as exc:
                raise PSNError(f"Could not reach PlayStation Network: {exc}") from exc
            if response.status_code >= 400:
                raise PSNError(f"PlayStation library request failed ({response.status_code}).")
            try:
                payload = response.json()
            except ValueError as exc:
                raise PSNError("PlayStation returned invalid JSON.") from exc
            page = payload.get("trophyTitles", [])
            titles.extend(page)
            total = payload.get("totalItemCount", len(titles))
            offset += limit
            if offset >= total or not page:
                break
        return titles

    def get_trophies_for_title(
        self, np_communication_id: str, np_service_name: str = "trophy"
    ) -> list[dict[str, Any]]:
        """Trophy definitions + this account's earned status for one title,
        combined in a single response (`comparedUser`/self shorthand). PS5
        titles use `np_service_name="trophy2"` — callers should retry with
        that if this returns nothing for a title reported by
        `get_owned_titles` as a PS5 title."""
        access_token = self._authenticate()
        try:
            response = self.session.get(
                f"https://m.np.playstation.com/api/trophy/v1/users/me/npCommunicationIds/{np_communication_id}/trophyGroups/all/trophies",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"npServiceName": np_service_name},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise PSNError(f"Could not reach PlayStation Network: {exc}") from exc
        if response.status_code >= 400:
            raise PSNError(f"PlayStation trophy request failed ({response.status_code}).")
        try:
            payload = response.json()
        except ValueError as exc:
            raise PSNError("PlayStation returned invalid JSON.") from exc
        return payload.get("trophies", [])
