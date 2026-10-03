# pylint: disable=missing-module-docstring
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

# wiseoldman.net's public API — no account, no API key. Rate-limited per
# IP but generous enough for a manual "sync this one account" click.
_PLAYERS_URL = "https://api.wiseoldman.net/v2/players"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; unnamed-tracking-app/1.0)"})

# Display order/casing for the stats dict this module returns — WOM's own
# skill keys are lowercase ("hitpoints", "runecrafting"); shown with real
# capitalization since that's what actually gets rendered in the UI.
_SKILL_LABELS = [
    ("overall", "Overall"),
    ("attack", "Attack"),
    ("defence", "Defence"),
    ("strength", "Strength"),
    ("hitpoints", "Hitpoints"),
    ("ranged", "Ranged"),
    ("prayer", "Prayer"),
    ("magic", "Magic"),
    ("cooking", "Cooking"),
    ("woodcutting", "Woodcutting"),
    ("fletching", "Fletching"),
    ("fishing", "Fishing"),
    ("firemaking", "Firemaking"),
    ("crafting", "Crafting"),
    ("smithing", "Smithing"),
    ("mining", "Mining"),
    ("herblore", "Herblore"),
    ("agility", "Agility"),
    ("thieving", "Thieving"),
    ("slayer", "Slayer"),
    ("farming", "Farming"),
    ("runecrafting", "Runecrafting"),
    ("hunter", "Hunter"),
    ("construction", "Construction"),
]

# boss/raid kill-count labels — only ones with a real (>0) kill count get
# included in the returned stats, since most of WOM's ~90 boss metrics are
# untracked (-1) for any given account and would otherwise bury the skills
# under a wall of zeroes
_BOSS_LABELS = {
    "abyssal_sire": "Abyssal Sire",
    "alchemical_hydra": "Alchemical Hydra",
    "amoxliatl": "Amoxliatl",
    "araxxor": "Araxxor",
    "artio": "Artio",
    "barrows_chests": "Barrows Chests",
    "bryophyta": "Bryophyta",
    "callisto": "Callisto",
    "calvarion": "Calvar'ion",
    "cerberus": "Cerberus",
    "chambers_of_xeric": "Chambers of Xeric",
    "chambers_of_xeric_challenge_mode": "CoX: Challenge Mode",
    "chaos_elemental": "Chaos Elemental",
    "chaos_fanatic": "Chaos Fanatic",
    "commander_zilyana": "Commander Zilyana",
    "corporeal_beast": "Corporeal Beast",
    "crazy_archaeologist": "Crazy Archaeologist",
    "dagannoth_prime": "Dagannoth Prime",
    "dagannoth_rex": "Dagannoth Rex",
    "dagannoth_supreme": "Dagannoth Supreme",
    "deranged_archaeologist": "Deranged Archaeologist",
    "duke_sucellus": "Duke Sucellus",
    "general_graardor": "General Graardor",
    "giant_mole": "Giant Mole",
    "grotesque_guardians": "Grotesque Guardians",
    "hespori": "Hespori",
    "kalphite_queen": "Kalphite Queen",
    "king_black_dragon": "King Black Dragon",
    "kraken": "Kraken",
    "kreearra": "Kree'Arra",
    "kril_tsutsaroth": "K'ril Tsutsaroth",
    "lunar_chests": "Lunar Chests",
    "mimic": "Mimic",
    "nex": "Nex",
    "nightmare": "Nightmare",
    "phosanis_nightmare": "Phosani's Nightmare",
    "obor": "Obor",
    "phantom_muspah": "Phantom Muspah",
    "sarachnis": "Sarachnis",
    "scorpia": "Scorpia",
    "scurrius": "Scurrius",
    "skotizo": "Skotizo",
    "sol_heredit": "Sol Heredit",
    "spindel": "Spindel",
    "tempoross": "Tempoross",
    "the_gauntlet": "The Gauntlet",
    "the_corrupted_gauntlet": "The Corrupted Gauntlet",
    "the_hueycoatl": "The Hueycoatl",
    "the_leviathan": "The Leviathan",
    "the_royal_titans": "The Royal Titans",
    "the_whisperer": "The Whisperer",
    "theatre_of_blood": "Theatre of Blood",
    "theatre_of_blood_hard_mode": "ToB: Hard Mode",
    "thermonuclear_smoke_devil": "Thermonuclear Smoke Devil",
    "tombs_of_amascut": "Tombs of Amascut",
    "tombs_of_amascut_expert": "ToA: Expert Mode",
    "tzkal_zuk": "TzKal-Zuk",
    "tztok_jad": "TzTok-Jad",
    "vardorvis": "Vardorvis",
    "venenatis": "Venenatis",
    "vetion": "Vet'ion",
    "vorkath": "Vorkath",
    "wintertodt": "Wintertodt",
    "zalcano": "Zalcano",
    "zulrah": "Zulrah",
}


class WiseOldManError(RuntimeError):
    """Raised when wiseoldman.net is unreachable or the username isn't tracked there."""


def _extract_stats(snapshot_data: dict[str, Any]) -> dict[str, Any]:
    """Shared by get_player_stats (latest) and get_player_snapshots
    (history) — both hand this the same `data.{skills,bosses}` shape.
    Returns both the display strings (`stats`, level/KC — what the Stats
    card already showed) and the raw integers (`xp`/`kc`) needed to
    compute an accurate day-to-day gain instead of just diffing levels
    (a single level can be tens of thousands of XP wide)."""
    skills = snapshot_data.get("skills") or {}
    bosses = snapshot_data.get("bosses") or {}
    stats: dict[str, str] = {}
    xp: dict[str, int] = {}
    kc: dict[str, int] = {}
    for key, label in _SKILL_LABELS:
        entry = skills.get(key) or {}
        level = entry.get("level")
        if level is not None:
            stats[label] = str(level)
        experience = entry.get("experience")
        if experience is not None and experience >= 0:
            xp[label] = int(experience)
    for key, label in _BOSS_LABELS.items():
        kills = (bosses.get(key) or {}).get("kills")
        if kills is not None and kills > 0:
            stats[label] = f"{kills} KC"
            kc[label] = int(kills)
    return {"stats": stats, "xp": xp, "kc": kc}


def _parse_iso(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .timestamp()
        )
    except ValueError:
        return None


def get_player_stats(username: str) -> dict[str, Any]:
    """Fetches a RuneScape (OSRS) player's current skill levels and boss
    kill counts. Returns {"stats": {...display strings...}, "xp": {...},
    "kc": {...}, "combat_level": "110"} — only skills/bosses WOM actually
    returned data for are included. Raises if the username isn't tracked
    by WOM yet; the caller's error message tells the user to visit
    wiseoldman.net to register it first, since this app can't do that for
    them.
    """
    name = username.strip()
    if not name:
        raise WiseOldManError("No WiseOldMan username provided.")
    try:
        response = _SESSION.get(f"{_PLAYERS_URL}/{name}", timeout=15)
    except requests.RequestException as exc:
        raise WiseOldManError(f"Could not reach WiseOldMan: {exc}") from exc

    if response.status_code == 404:
        raise WiseOldManError(
            f"WiseOldMan doesn't track '{name}' yet — search for it at wiseoldman.net to register it first."
        )
    if response.status_code >= 400:
        raise WiseOldManError(f"WiseOldMan request failed ({response.status_code}).")

    try:
        payload = response.json()
    except ValueError as exc:
        raise WiseOldManError("WiseOldMan returned invalid JSON.") from exc

    snapshot_data = (payload.get("latestSnapshot") or {}).get("data") or {}
    extracted = _extract_stats(snapshot_data)
    combat_level = payload.get("combatLevel")
    return {**extracted, "combat_level": str(combat_level) if combat_level is not None else None}


def get_player_snapshots(username: str, limit: int = 50) -> list[dict[str, Any]]:
    """Whatever historical snapshots WOM already has recorded for this
    account — only as good as how often *someone* (not necessarily this
    app) has updated it there before. Returns oldest-first:
    [{"recorded_at": <epoch seconds>, "stats": {...}, "xp": {...},
    "kc": {...}}, ...]. Best-effort: an account with no tracked history
    just returns an empty list rather than erroring, since "no history
    yet" isn't a failure."""
    name = username.strip()
    if not name:
        return []
    try:
        response = _SESSION.get(
            f"{_PLAYERS_URL}/{name}/snapshots", params={"limit": limit}, timeout=15
        )
    except requests.RequestException:
        return []
    if response.status_code >= 400:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    if not isinstance(payload, list):
        return []

    results: list[dict[str, Any]] = []
    for entry in payload:
        recorded_at = _parse_iso(entry.get("createdAt"))
        if recorded_at is None:
            continue
        extracted = _extract_stats(entry.get("data") or {})
        if extracted["stats"]:
            results.append({"recorded_at": recorded_at, **extracted})
    results.sort(key=lambda r: r["recorded_at"])
    return results
