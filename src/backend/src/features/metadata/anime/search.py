# pylint: disable=duplicate-code
# These modules intentionally keep domain/provider-specific logic separate; similar
# structures here represent parallel APIs rather than accidental copy/paste.

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Literal

from src.features.metadata.anime.anilist import AniListClient
from src.features.metadata.anime.jikan import JikanClient
from src.features.metadata.search_utils import format_provider_error, merge_search_result

# Unlike Movies/TV (TMDB+OMDb, both need an app-wide API key), both
# AniList and Jikan are public/keyless for read-only search — so there's
# no ProviderContext of credentials to gate on here, both providers
# always run. Redundancy is still the point: AniList is the primary,
# anime-specific source; Jikan (MyAnimeList) is the fallback, so a rate
# limit or an AniList outage doesn't leave the search empty.


def _blank_result(provider: str, provider_id: str, title: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "provider_id": provider_id,
        "title": title,
        "description": None,
        "first_air_date": None,
        "episode_runtime_minutes": None,
        "episode_count": None,
        "studios": [],
        "countries": [],
        "genres": [],
        "poster_url": None,
        "backdrop_url": None,
        "format": None,
        "anilist_score": None,
        "mal_score": None,
        # Jikan's own id for this entry — kept separate from `provider_id`
        # (which is whichever provider matched first, usually AniList)
        # since episode sync specifically needs Jikan's id to call back in.
        "mal_id": None,
        "url": None,
    }


ProviderRun = Callable[[str, int], list[dict[str, Any]]]


@dataclass
class ProviderSpec:
    name: str
    kind: Literal["primary"]
    run: ProviderRun


def _map_anilist_entry(entry: dict[str, Any]) -> dict[str, Any]:
    result = _blank_result("AniList", str(entry.get("id", "")), entry.get("title") or "")
    result.update(
        {
            "description": entry.get("overview"),
            "first_air_date": entry.get("release_date"),
            "episode_runtime_minutes": entry.get("episode_runtime_minutes"),
            "episode_count": entry.get("episode_count"),
            "studios": entry.get("studios") or [],
            "countries": entry.get("countries") or [],
            "genres": entry.get("genres") or [],
            "poster_url": entry.get("poster_url"),
            "backdrop_url": entry.get("backdrop_url"),
            "format": entry.get("format"),
            "anilist_score": entry.get("score"),
            "url": entry.get("url"),
            # AniList exposes each entry's own MyAnimeList id directly,
            # so a show found via AniList alone can still get a real
            # Jikan fallback later (once Jikan is reachable) instead of
            # needing MAL's own search to separately find and match it.
            "mal_id": str(entry["id_mal"]) if entry.get("id_mal") else None,
        }
    )
    return result


def _run_anilist(query: str, limit: int) -> list[dict[str, Any]]:
    client = AniListClient()
    return [_map_anilist_entry(entry) for entry in client.search(query, limit=limit)]


def get_anime_metadata_by_anilist_id(anilist_id: int) -> dict[str, Any] | None:
    """The same normalized shape `search_anime_metadata` returns per
    result, for one already-known AniList id — used when adding a title
    from a relations-graph branch, chain entry, or recommendation, all of
    which already carry AniList's real id and shouldn't depend on a fresh
    title search re-finding (and correctly matching) the same entry."""
    entry = AniListClient().get_by_id(anilist_id)
    return _map_anilist_entry(entry) if entry else None


def _run_jikan(query: str, limit: int) -> list[dict[str, Any]]:
    client = JikanClient()
    found: list[dict[str, Any]] = []
    for entry in client.search(query, limit=limit):
        result = _blank_result("MyAnimeList", str(entry.get("id", "")), entry.get("title") or "")
        result.update(
            {
                "description": entry.get("overview"),
                "first_air_date": entry.get("release_date"),
                "episode_runtime_minutes": entry.get("episode_runtime_minutes"),
                "episode_count": entry.get("episode_count"),
                "studios": entry.get("studios") or [],
                "countries": entry.get("countries") or [],
                "genres": entry.get("genres") or [],
                "mal_id": str(entry.get("id", "")) or None,
                "poster_url": entry.get("poster_url"),
                "format": entry.get("format"),
                "mal_score": entry.get("score"),
                "url": entry.get("url"),
            }
        )
        found.append(result)
    return found


PROVIDERS: list[ProviderSpec] = [
    ProviderSpec("AniList", "primary", _run_anilist),
    ProviderSpec("MyAnimeList", "primary", _run_jikan),
]


def search_anime_metadata(query: str, limit: int = 8) -> dict[str, Any]:
    """Search AniList and Jikan concurrently and return normalized,
    creation-form-ready results. Both providers are keyless, so unlike
    Movies/TV's search there's nothing to gate on — both always run.
    A provider that fails at request time contributes a message to
    `provider_errors` without failing the other provider."""
    results: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    providers_used: list[str] = []

    def _call(spec: ProviderSpec) -> tuple[ProviderSpec, list[dict[str, Any]] | None, str | None]:
        try:
            return spec, spec.run(query, limit), None
        except Exception as exc:  # noqa: BLE001 — one provider's failure shouldn't sink the search
            return spec, None, str(exc)

    with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as executor:
        for spec, outcome, error in executor.map(_call, PROVIDERS):
            if error is not None:
                provider_errors.append(format_provider_error(spec.name, error))
                continue
            if outcome:
                for candidate in outcome:
                    merge_search_result(results, candidate)
            providers_used.append(spec.name)

    return {
        "query": query,
        "providers": providers_used,
        "provider_errors": provider_errors,
        "results": results,
    }
