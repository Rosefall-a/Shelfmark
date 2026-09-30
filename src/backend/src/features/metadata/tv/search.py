# pylint: disable=duplicate-code
# These modules intentionally keep domain/provider-specific logic separate; similar
# structures here represent parallel APIs rather than accidental copy/paste.

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Literal

from src.features.metadata.movies.omdb import OMDBClient
from src.features.metadata.movies.tmdb import TMDBClient
from src.features.metadata.tv.tvmaze import TVMazeClient
from src.features.metadata.search_utils import format_provider_error, merge_search_result

# Reuses the TMDB/OMDb clients built for Movies (same API keys, same
# deployment-wide AppIntegrationSettings) rather than duplicating a whole
# second pair of client classes — only the query shape (search_tv vs
# search) and the result field set actually differ.


def _blank_result(provider: str, provider_id: str, title: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "provider_id": provider_id,
        "title": title,
        "description": None,
        "first_air_date": None,
        "episode_runtime_minutes": None,
        "creators": [],
        "studios": [],
        "countries": [],
        "languages": [],
        "genres": [],
        "poster_url": None,
        "backdrop_url": None,
        "tmdb_score": None,
        "seasons": [],
        "url": None,
        # TVmaze's own id for this show — kept separate from `provider_id`
        # (whichever provider matched first, usually TMDB or OMDb since
        # TVmaze runs last) since episode sync and the airing check
        # specifically need TVmaze's id to call back in.
        "tvmaze_id": None,
    }


@dataclass
class ProviderContext:
    tmdb_api_key: str | None
    omdb_api_key: str | None


ProviderRun = Callable[[str, int, ProviderContext], list[dict[str, Any]]]


@dataclass
class ProviderSpec:
    name: str
    kind: Literal["primary"]
    available: Callable[[ProviderContext], bool]
    run: ProviderRun


def _run_tmdb(query: str, limit: int, ctx: ProviderContext) -> list[dict[str, Any]]:
    assert ctx.tmdb_api_key  # guarded by `available`
    client = TMDBClient(api_key=ctx.tmdb_api_key)
    found: list[dict[str, Any]] = []
    for show in client.search_tv(query, limit=limit):
        result = _blank_result("TMDB", str(show.get("id", "")), show.get("title", ""))
        result.update(
            {
                "description": show.get("overview"),
                "first_air_date": show.get("first_air_date") or None,
                "episode_runtime_minutes": show.get("episode_runtime_minutes"),
                "creators": show.get("creators") or [],
                "studios": show.get("studios") or [],
                "countries": show.get("countries") or [],
                "languages": show.get("languages") or [],
                "genres": show.get("genres") or [],
                "poster_url": show.get("poster_url"),
                "backdrop_url": show.get("backdrop_url"),
                "tmdb_score": show.get("vote_average"),
                "seasons": show.get("seasons") or [],
                "url": show.get("url"),
            }
        )
        found.append(result)
    return found


def _run_omdb(query: str, limit: int, ctx: ProviderContext) -> list[dict[str, Any]]:
    assert ctx.omdb_api_key  # guarded by `available`
    client = OMDBClient(api_key=ctx.omdb_api_key)
    found: list[dict[str, Any]] = []
    for show in client.search_tv(query, limit=limit):
        result = _blank_result("OMDb", str(show.get("id", "")), show.get("title", ""))
        result.update(
            {
                "description": show.get("overview"),
                "first_air_date": show.get("first_air_date") or None,
                "episode_runtime_minutes": show.get("episode_runtime_minutes"),
                "creators": show.get("creators") or [],
                "studios": show.get("studios") or [],
                "countries": show.get("countries") or [],
                "languages": show.get("languages") or [],
                "genres": show.get("genres") or [],
                "poster_url": show.get("poster_url"),
                "tmdb_score": show.get("vote_average"),
                "seasons": [],
                "url": show.get("url"),
            }
        )
        found.append(result)
    return found


def _run_tvmaze(query: str, limit: int, _ctx: ProviderContext) -> list[dict[str, Any]]:
    client = TVMazeClient()
    found: list[dict[str, Any]] = []
    for show in client.search(query, limit=limit):
        result = _blank_result("TVmaze", str(show.get("id", "")), show.get("title", ""))
        result.update(
            {
                "description": show.get("overview"),
                "first_air_date": show.get("first_air_date"),
                "episode_runtime_minutes": show.get("episode_runtime_minutes"),
                "studios": show.get("studios") or [],
                "countries": show.get("countries") or [],
                "genres": show.get("genres") or [],
                "poster_url": show.get("poster_url"),
                "tmdb_score": show.get("score"),
                "url": show.get("url"),
                "tvmaze_id": str(show.get("id", "")) or None,
            }
        )
        found.append(result)
    return found


PROVIDERS: dict[str, ProviderSpec] = {
    "TMDB": ProviderSpec("TMDB", "primary", lambda ctx: bool(ctx.tmdb_api_key), _run_tmdb),
    "OMDb": ProviderSpec("OMDb", "primary", lambda ctx: bool(ctx.omdb_api_key), _run_omdb),
    # Keyless — always available, so TV search still returns real results
    # even before TMDB/OMDb are configured.
    "TVmaze": ProviderSpec("TVmaze", "primary", lambda ctx: True, _run_tvmaze),
}

DEFAULT_PROVIDER_ORDER = ["TMDB", "OMDb", "TVmaze"]


def _looks_like_anime(result: dict[str, Any]) -> bool:
    """A TV search result that is Japanese animation: genre "Anime"
    (TVmaze), or genre "Animation" from Japan or in Japanese (TMDB)."""
    genres = {str(g).lower() for g in result.get("genres") or []}
    if "anime" in genres:
        return True
    if "animation" not in genres:
        return False
    countries = {str(c).lower() for c in result.get("countries") or []}
    languages = {str(l).lower() for l in result.get("languages") or []}
    return bool({"jp", "japan"} & countries or {"ja", "japanese"} & languages)


def search_tv_metadata(
    query: str,
    limit: int = 8,
    tmdb_api_key: str | None = None,
    omdb_api_key: str | None = None,
) -> dict[str, Any]:
    """Search TMDB and OMDb concurrently for TV shows and return
    normalized, creation-form-ready results, mirroring
    `search_movie_metadata`'s orchestration exactly (per-provider error
    isolation, title-match merging). TMDB results additionally carry a
    `seasons` list pulled straight from its `/tv/{id}` response, so a new
    show can bulk-create its seasons instead of the user typing them in."""
    ctx = ProviderContext(tmdb_api_key=tmdb_api_key, omdb_api_key=omdb_api_key)
    specs = [PROVIDERS[name] for name in DEFAULT_PROVIDER_ORDER if PROVIDERS[name].available(ctx)]

    results: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    providers_used: list[str] = []

    def _call(spec: ProviderSpec) -> tuple[ProviderSpec, list[dict[str, Any]] | None, str | None]:
        try:
            return spec, spec.run(query, limit, ctx), None
        except Exception as exc:  # noqa: BLE001 — one provider's failure shouldn't sink the search
            return spec, None, str(exc)

    if specs:
        with ThreadPoolExecutor(max_workers=len(specs)) as executor:
            for spec, outcome, error in executor.map(_call, specs):
                if error is not None:
                    provider_errors.append(format_provider_error(spec.name, error))
                    continue
                if outcome:
                    for candidate in outcome:
                        merge_search_result(results, candidate)
                providers_used.append(spec.name)

    # anime belongs in the Anime library (AniList, its own episode numbering
    # and airing data); TMDB and TVmaze also list it as TV, which put the
    # same title in the wrong place. Hidden here, with a note saying so.
    kept = [r for r in results if not _looks_like_anime(r)]
    hidden = len(results) - len(kept)
    if hidden:
        provider_errors.append(
            f"{hidden} anime title{'s' if hidden != 1 else ''} hidden from these results. "
            "Add anime from the Anime page."
        )

    return {
        "query": query,
        "providers": providers_used,
        "provider_errors": provider_errors,
        "results": kept,
    }
