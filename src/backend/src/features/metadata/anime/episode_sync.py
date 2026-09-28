# pylint: disable=missing-class-docstring,too-many-locals
"""Fetching a show's episode list from whichever provider has it, shared
between the on-demand route (api/routes/anime.py) and the weekly
background refresh (features/metadata/refresh.py) — one place for the
Jikan + AniList + Kitsu + TMDB merge instead of duplicating it."""

from __future__ import annotations

import asyncio
from typing import Any, NamedTuple

from src.features.metadata.anime.anilist import AniListClient, AniListError
from src.features.metadata.anime.anizip import AniZipClient, AniZipError
from src.features.metadata.anime.jikan import JikanClient, JikanError
from src.features.metadata.anime.kitsu import KitsuClient, KitsuError
from src.features.metadata.movies.tmdb import TMDBClient, TMDBError


def _merge_episode_sources(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combines any number of providers' episode lists by episode number
    instead of picking one: no single provider is complete. Merged per field:
    the first source passed wins a field it has a value for, later sources
    only fill in whatever is still blank."""
    by_number: dict[int, dict[str, Any]] = {}
    for source in sources:
        for entry in source:
            existing = by_number.get(entry["episode_number"])
            if existing is None:
                by_number[entry["episode_number"]] = dict(entry)
                continue
            for key, value in entry.items():
                if value is not None and not existing.get(key):
                    existing[key] = value
    return sorted(by_number.values(), key=lambda e: e["episode_number"])


class EpisodeFetch(NamedTuple):
    episodes: list[dict[str, Any]]
    errors: list[str]
    # the entry's own episode count, only once it has finished airing
    final_total: int | None
    # the highest episode number that can exist: the final total, or for a
    # show still airing its announced total or what has aired so far
    limit: int | None
    # the exact Kitsu id ani.zip gives for this entry, if it knows one
    kitsu_id: str | None


def episode_limit(info: dict[str, Any] | None) -> int | None:
    """The highest episode number an AniList entry can have right now. A
    finished one has its final total. One still airing has what it announced,
    or failing that what has aired (the episode before the next one), because
    a provider listing a thousand more is listing episodes that do not exist
    yet. Unknown gives no limit."""
    if not info:
        return None
    if info.get("total"):
        return int(info["total"])
    if info.get("status") == "RELEASING":
        if info.get("planned"):
            return int(info["planned"])
        upcoming = info.get("next")
        if upcoming and upcoming > 1:
            return int(upcoming) - 1
    return None


def _is_complete(episodes: list[dict[str, Any]], final_total: int | None) -> bool:
    """Whether one provider's list already covers everything: every episode
    titled, and (for a finished show) every number up to its total."""
    if not episodes or any(not e.get("title") for e in episodes):
        return False
    if final_total is None:
        return True
    return {e["episode_number"] for e in episodes} >= set(range(1, final_total + 1))


async def fetch_episodes_with_fallback(
    external_id: str | None,
    anilist_id: str | None,
    kitsu_id: str | None = None,
    *,
    final_total: int | None = None,
    limit: int | None = None,
    total_known: bool = False,
) -> EpisodeFetch:
    """The episode list of one anime entry.

    ani.zip is asked first: it has titles, screenshots, synopses and air times
    for the exact AniList entry in one request, and usually needs nothing
    else. Jikan, AniList and Kitsu are only asked when it left gaps, because
    they are slower and Jikan is often down.

    Two rules keep a wrong provider match from inflating a season: a Kitsu
    list is used only when ani.zip vouches for that exact Kitsu id (a stored
    id found by title search is not trusted), and once AniList says the entry
    has finished airing with N episodes, nothing numbered above N is kept.
    Pass `final_total` and `limit` with `total_known=True` when the caller
    already has them (the bulk refresh looks them up for every show in a few
    requests).

    Returns errors instead of raising, so a caller with no HTTP request behind
    it (the background refresh) can log them."""
    errors: list[str] = []
    anizip: dict[str, Any] = {"episodes": [], "kitsu_id": None}
    if anilist_id:
        try:
            anizip = await asyncio.to_thread(AniZipClient().lookup, anilist_id)
        except AniZipError as exc:
            errors.append(f"ani.zip: {exc}")
        if not total_known:
            try:
                totals = await asyncio.to_thread(AniListClient().final_totals, [int(anilist_id)])
                info = totals.get(int(anilist_id))
                final_total = (info or {}).get("total")
                limit = episode_limit(info)
            except (AniListError, ValueError) as exc:
                errors.append(f"AniList: {exc}")
    anizip_episodes: list[dict[str, Any]] = anizip["episodes"]
    mapped_kitsu: str | None = anizip.get("kitsu_id")

    jikan_episodes: list[dict[str, Any]] = []
    anilist_episodes: list[dict[str, Any]] = []
    kitsu_episodes: list[dict[str, Any]] = []
    if not _is_complete(anizip_episodes, final_total):
        if external_id:
            try:
                jikan_episodes = await asyncio.to_thread(JikanClient().episodes, external_id)
            except JikanError as exc:
                errors.append(f"Jikan: {exc}")
        if anilist_id:
            try:
                anilist_episodes = await asyncio.to_thread(AniListClient().episodes, anilist_id)
            except AniListError as exc:
                errors.append(f"AniList: {exc}")
        trusted_kitsu = mapped_kitsu or (kitsu_id if not anilist_id else None)
        if trusted_kitsu:
            try:
                kitsu_episodes = await asyncio.to_thread(KitsuClient().episodes, trusted_kitsu)
            except KitsuError as exc:
                errors.append(f"Kitsu: {exc}")
    merged = _merge_episode_sources(
        anizip_episodes, jikan_episodes, anilist_episodes, kitsu_episodes
    )
    cap = limit or final_total
    if cap:
        merged = [e for e in merged if e["episode_number"] <= cap]
    return EpisodeFetch(merged, errors, final_total, cap, mapped_kitsu)


async def fetch_airing_status(
    anilist_id: str | None,
) -> tuple[int | None, bool, int | None, int | None, list[str]]:
    """`(aired_count, is_airing, next_episode_air_at, next_episode_number,
    errors)` — the cheap AniList query, no episode list at all. Used by
    the frequent airing-check loop; MyAnimeList/Jikan has no equivalent
    lightweight endpoint, so this only covers the AniList side (fine —
    it's specifically the ongoing-show case this exists for, and AniList
    tracks nextAiringEpisode where Jikan doesn't expose anything
    comparable)."""
    if not anilist_id:
        return None, False, None, None, []
    try:
        count, is_airing, air_at, next_number = await asyncio.to_thread(
            AniListClient().airing_status, anilist_id
        )
        return count, is_airing, air_at, next_number, []
    except AniListError as exc:
        return None, False, None, None, [f"AniList: {exc}"]


def pad_to_known_total(all_episodes: list[dict[str, Any]], episode_count: int | None) -> int | None:
    """Neither provider reliably lists every episode for a very
    long-running show — pad the rest as plain numbered placeholders up to
    `episode_count` (when known) so the checklist still covers the whole
    run. In place. Returns the total to store on the season (unchanged if
    already known, otherwise the highest episode number actually seen)."""
    known_numbers = {entry["episode_number"] for entry in all_episodes}
    if episode_count:
        for n in range(1, episode_count + 1):
            if n not in known_numbers:
                all_episodes.append({"episode_number": n})
        all_episodes.sort(key=lambda e: e["episode_number"])
        return episode_count
    if all_episodes:
        return max(known_numbers)
    return episode_count


_BACKFILLABLE_EPISODE_FIELDS = (
    "title",
    "description",
    "air_date",
    "runtime_minutes",
    "still_url",
)


def needs_tmdb_backfill(all_episodes: list[dict[str, Any]]) -> bool:
    """Whether any entry is still missing a field TMDB could fill —
    checked per field rather than just "no title yet", since an entry can
    already have a real title (from Jikan, which never returns an
    episode image at all) while still missing everything else."""
    return any(
        entry.get(field) is None for entry in all_episodes for field in _BACKFILLABLE_EPISODE_FIELDS
    )


async def backfill_from_tmdb(
    all_episodes: list[dict[str, Any]], show_title: str, tmdb_api_key: str
) -> None:
    """Fills in whichever of title/description/air_date/runtime/still_url
    is still blank on each entry — most long-running anime is also
    indexed as an ordinary TV show on TMDB, often with a still image even
    when Jikan+AniList together don't have one. Checked per field, not
    "does this entry have a title yet" — an entry can already have a real
    title (from Jikan, which never returns episode images at all) and
    still be missing everything else TMDB could fill in; the old
    title-only gate skipped those entirely, so an episode that resolved
    via Jikan could never get a thumbnail even once a TMDB key was
    configured. Never overwrites a field that already has a value.
    Silently gives up on any TMDB failure; the fields it can't fill just
    stay as they are, no worse off than before this ran."""
    try:
        client = TMDBClient(tmdb_api_key)
        tv_id = await asyncio.to_thread(client.find_tv_id, show_title)
        if tv_id is None:
            return
        tmdb_episodes = await asyncio.to_thread(client.tv_all_episodes, tv_id)
    except TMDBError:
        return
    by_number = {e["episode_number"]: e for e in tmdb_episodes}
    for entry in all_episodes:
        match = by_number.get(entry["episode_number"])
        if not match:
            continue
        for field in _BACKFILLABLE_EPISODE_FIELDS:
            if entry.get(field) is None and match.get(field) is not None:
                entry[field] = match[field]
