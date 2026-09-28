"""
Steam Storefront API client.

The Steam Storefront API is unofficial/undocumented but widely used.
No API key is required. Docs (community-maintained):
https://wiki.teamfortress.com/wiki/User:RJackson/StorefrontAPI

Endpoints used here:
- App details:  https://store.steampowered.com/api/appdetails
- App list:     https://api.steampowered.com/ISteamApps/GetAppList/v2/
- Featured:     https://store.steampowered.com/api/featuredcategories
- Search:       https://store.steampowered.com/api/storesearch
"""
# pylint: disable=missing-function-docstring,unused-argument

import re
import time

import requests

# a Steam Web API key is always exactly 32 hex characters — distinct enough
# from a profile URL/vanity name/SteamID64 to tell the two apart
# automatically, so the two credential fields don't need to be entered in
# any particular order
_API_KEY_PATTERN = re.compile(r"^[0-9A-Fa-f]{32}$")


def looks_like_api_key(value: str) -> bool:
    return bool(_API_KEY_PATTERN.fullmatch(value.strip()))


BASE_URL = "https://store.steampowered.com/api"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; SteamDataFetcher/1.0)"})

# official Steam Web API — needs a per-user API key + SteamID64
# (developer.steamcommunity.com/apikey), separate from the unauthenticated
# Storefront endpoints above
_WEB_API_BASE = "https://api.steampowered.com"


class SteamLibraryError(RuntimeError):
    """Raised when the Steam Web API rejects a library-sync call."""


def resolve_steam_id(identifier: str, api_key: str) -> str:
    """Every Steam Web API library call needs a numeric SteamID64 — the API
    key alone only identifies the calling app, not whose library to fetch.
    Takes just the plain profile ID: either your vanity name (the part
    after steamcommunity.com/id/) or the raw 17-digit SteamID64 itself —
    not the full profile link."""
    vanity = identifier.strip()
    if vanity.isdigit() and len(vanity) == 17:
        return vanity
    if not vanity:
        raise SteamLibraryError("Enter your Steam profile ID or SteamID64.")
    try:
        resp = SESSION.get(
            f"{_WEB_API_BASE}/ISteamUser/ResolveVanityURL/v1/",
            params={"key": api_key, "vanityurl": vanity},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise SteamLibraryError(f"Could not reach Steam: {exc}") from exc
    if resp.status_code >= 400:
        raise SteamLibraryError(f"Steam rejected the profile lookup ({resp.status_code}).")
    try:
        payload = resp.json().get("response", {})
    except ValueError as exc:
        raise SteamLibraryError("Steam returned invalid JSON.") from exc
    if payload.get("success") != 1 or not payload.get("steamid"):
        raise SteamLibraryError("Could not resolve that Steam profile URL/vanity name/ID.")
    return str(payload["steamid"])


def get_owned_games(steam_id: str, api_key: str) -> list[dict]:
    """The caller's owned-games library — requires their Community profile
    to have game details set to public, or this returns an empty list with
    no error (Steam's API silently omits games rather than rejecting)."""
    try:
        resp = SESSION.get(
            f"{_WEB_API_BASE}/IPlayerService/GetOwnedGames/v1/",
            params={
                "key": api_key,
                "steamid": steam_id,
                "include_appinfo": "1",
                "include_played_free_games": "1",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise SteamLibraryError(f"Could not reach Steam: {exc}") from exc
    if resp.status_code == 403:
        raise SteamLibraryError("Steam rejected the API key.")
    if resp.status_code >= 400:
        raise SteamLibraryError(f"Steam library request failed ({resp.status_code}).")
    try:
        return resp.json().get("response", {}).get("games", [])
    except ValueError as exc:
        raise SteamLibraryError("Steam returned invalid JSON.") from exc


def get_player_summary(steam_id: str, api_key: str) -> dict:
    """The account's public persona name + avatar, shown in Settings so a
    connected Steam account reads as "who", not just a green dot. Best-effort
    — a private profile can return an empty player list rather than erroring."""
    try:
        resp = SESSION.get(
            f"{_WEB_API_BASE}/ISteamUser/GetPlayerSummaries/v2/",
            params={"key": api_key, "steamids": steam_id},
            timeout=15,
        )
    except requests.RequestException:
        return {}
    if resp.status_code >= 400:
        return {}
    try:
        players = resp.json().get("response", {}).get("players", [])
    except ValueError:
        return {}
    return players[0] if players else {}


def get_schema_for_game(api_key: str, app_id: int) -> dict[str, dict]:
    """Achievement definitions (display name/description/icons) for one
    app, keyed by their internal `apiname` — `GetPlayerAchievements` below
    only returns which ones are unlocked, not what they mean."""
    try:
        resp = SESSION.get(
            f"{_WEB_API_BASE}/ISteamUserStats/GetSchemaForGame/v2/",
            params={"key": api_key, "appid": str(app_id)},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise SteamLibraryError(f"Could not reach Steam: {exc}") from exc
    if resp.status_code >= 400:
        raise SteamLibraryError(f"Steam schema request failed ({resp.status_code}).")
    try:
        achievements = (
            resp.json().get("game", {}).get("availableGameStats", {}).get("achievements", [])
        )
    except ValueError as exc:
        raise SteamLibraryError("Steam returned invalid JSON.") from exc
    return {entry["name"]: entry for entry in achievements if entry.get("name")}


def get_player_achievements(steam_id: str, api_key: str, app_id: int) -> list[dict]:
    """Which achievements this player has unlocked for one app. Many games
    have no achievement schema at all — that's a normal empty result, not
    an error."""
    try:
        resp = SESSION.get(
            f"{_WEB_API_BASE}/ISteamUserStats/GetPlayerAchievements/v1/",
            params={"key": api_key, "steamid": steam_id, "appid": str(app_id)},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise SteamLibraryError(f"Could not reach Steam: {exc}") from exc
    if resp.status_code >= 400:
        return []
    try:
        payload = resp.json().get("playerstats", {})
    except ValueError:
        return []
    if not payload.get("success"):
        return []
    return payload.get("achievements", [])


def get_app_details(app_id: int, country: str = "us", currency: str = "USD") -> dict | None:
    """
    Fetch full details for a single app (game/DLC/etc) by its Steam AppID.
    Returns the 'data' dict on success, or None if the app has no store page.
    """
    params: dict[str, str | int] = {"appids": app_id, "cc": country, "l": "en"}
    resp = SESSION.get(f"{BASE_URL}/appdetails", params=params, timeout=10)
    resp.raise_for_status()
    payload = resp.json()

    app_data = payload.get(str(app_id))
    if not app_data or not app_data.get("success"):
        return None
    return app_data["data"]


def get_app_details_bulk(app_ids: list[int], delay: float = 1.0) -> dict[int, dict]:
    """
    Fetch details for multiple AppIDs one at a time (the endpoint only
    reliably supports a single appid per request). `delay` avoids
    rate-limiting/soft bans from Steam.
    """
    results = {}
    for app_id in app_ids:
        data = get_app_details(app_id)
        if data:
            results[app_id] = data
        time.sleep(delay)
    return results


def search_store(term: str, country: str = "us") -> list[dict]:
    """Search the Steam store by keyword."""
    params = {"term": term, "cc": country, "l": "en"}
    resp = SESSION.get(f"{BASE_URL}/storesearch", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json().get("items", [])
