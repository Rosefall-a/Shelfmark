# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

from typing import Any

import requests

_BASE_URL = "https://api.themoviedb.org/3"
_POSTER_BASE = "https://image.tmdb.org/t/p/w500"
_BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"
_STILL_BASE = "https://image.tmdb.org/t/p/w300"


class TMDBError(RuntimeError):
    """Raised when TMDB responds unsuccessfully or the API key is missing."""


class TMDBClient:
    """Minimal client for TMDB v3. One deployment-wide API key (see
    database/models/app_integration_settings.py), no per-user auth."""

    def __init__(self, api_key: str | None, *, session: requests.Session | None = None) -> None:
        if not api_key:
            raise TMDBError("TMDB_API_KEY is not configured on the server.")
        self.api_key = api_key
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{_BASE_URL}{path}",
                params={**params, "api_key": self.api_key},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise TMDBError(f"Could not reach TMDB: {exc}") from exc
        if response.status_code >= 400:
            raise TMDBError(f"TMDB request failed ({response.status_code}): {response.text[:200]}")
        try:
            return response.json()
        except ValueError as exc:
            raise TMDBError("TMDB returned invalid JSON.") from exc

    def _details(self, movie_id: int) -> dict[str, Any]:
        return self._get(f"/movie/{movie_id}", {"append_to_response": "credits"})

    def search(self, query: str, limit: int = 8, year: int | None = None) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        payload = self._get(
            "/search/movie", {"query": query, **({"year": str(year)} if year else {})}
        )
        candidates = payload.get("results") or []

        results: list[dict[str, Any]] = []
        for candidate in candidates[:limit]:
            movie_id = candidate.get("id")
            if movie_id is None:
                continue
            try:
                details = self._details(movie_id)
            except TMDBError:
                details = candidate

            crew = (details.get("credits") or {}).get("crew") or []
            director = next((c["name"] for c in crew if c.get("job") == "Director"), None)
            writer = next(
                (c["name"] for c in crew if c.get("job") in ("Writer", "Screenplay")), None
            )
            poster_path = details.get("poster_path") or candidate.get("poster_path")
            backdrop_path = details.get("backdrop_path") or candidate.get("backdrop_path")

            results.append(
                {
                    "id": movie_id,
                    "title": details.get("title") or candidate.get("title"),
                    "overview": details.get("overview") or candidate.get("overview"),
                    "release_date": details.get("release_date") or candidate.get("release_date"),
                    "runtime_minutes": details.get("runtime"),
                    "director": director,
                    "writer": writer,
                    "studios": [
                        c["name"] for c in details.get("production_companies", []) if c.get("name")
                    ],
                    "countries": [
                        c["name"] for c in details.get("production_countries", []) if c.get("name")
                    ],
                    "languages": [
                        lang["english_name"]
                        for lang in details.get("spoken_languages", [])
                        if lang.get("english_name")
                    ],
                    "genres": [g["name"] for g in details.get("genres", []) if g.get("name")],
                    "poster_url": f"{_POSTER_BASE}{poster_path}" if poster_path else None,
                    "backdrop_url": f"{_BACKDROP_BASE}{backdrop_path}" if backdrop_path else None,
                    "vote_average": details.get("vote_average") or candidate.get("vote_average"),
                    "url": f"https://www.themoviedb.org/movie/{movie_id}",
                }
            )
        return results

    def _tv_details(self, tv_id: int) -> dict[str, Any]:
        return self._get(f"/tv/{tv_id}", {})

    def search_tv(
        self, query: str, limit: int = 8, year: int | None = None
    ) -> list[dict[str, Any]]:
        """Like `search`, but for TV shows. Also returns each show's full
        season list (TMDB's `/tv/{id}` details response includes every
        season's number/name/episode_count/air_date in one call) so a new
        show can have its seasons bulk-created instead of typed by hand."""
        if not query.strip():
            return []
        payload = self._get(
            "/search/tv", {"query": query, **({"first_air_date_year": str(year)} if year else {})}
        )
        candidates = payload.get("results") or []

        results: list[dict[str, Any]] = []
        for candidate in candidates[:limit]:
            tv_id = candidate.get("id")
            if tv_id is None:
                continue
            try:
                details = self._tv_details(tv_id)
            except TMDBError:
                details = candidate

            creators = [c["name"] for c in details.get("created_by", []) if c.get("name")]
            episode_run_times = details.get("episode_run_time") or []
            poster_path = details.get("poster_path") or candidate.get("poster_path")
            backdrop_path = details.get("backdrop_path") or candidate.get("backdrop_path")
            seasons = [
                {
                    "season_number": s.get("season_number"),
                    "name": s.get("name"),
                    "episode_count": s.get("episode_count"),
                    "air_date": s.get("air_date") or None,
                    "poster_url": f"{_POSTER_BASE}{s['poster_path']}"
                    if s.get("poster_path")
                    else None,
                }
                for s in details.get("seasons", [])
                if s.get("season_number") is not None and s.get("season_number") > 0
            ]

            results.append(
                {
                    "id": tv_id,
                    "title": details.get("name") or candidate.get("name"),
                    "overview": details.get("overview") or candidate.get("overview"),
                    "first_air_date": details.get("first_air_date")
                    or candidate.get("first_air_date"),
                    "episode_runtime_minutes": episode_run_times[0] if episode_run_times else None,
                    "creators": creators,
                    "studios": [
                        c["name"] for c in details.get("production_companies", []) if c.get("name")
                    ],
                    "countries": [
                        c["name"] for c in details.get("production_countries", []) if c.get("name")
                    ]
                    or (details.get("origin_country") or []),
                    "languages": [
                        lang["english_name"]
                        for lang in details.get("spoken_languages", [])
                        if lang.get("english_name")
                    ],
                    "genres": [g["name"] for g in details.get("genres", []) if g.get("name")],
                    "poster_url": f"{_POSTER_BASE}{poster_path}" if poster_path else None,
                    "backdrop_url": f"{_BACKDROP_BASE}{backdrop_path}" if backdrop_path else None,
                    "vote_average": details.get("vote_average") or candidate.get("vote_average"),
                    "seasons": seasons,
                    "url": f"https://www.themoviedb.org/tv/{tv_id}",
                }
            )
        return results

    def find_movie_id(self, title: str) -> int | None:
        """Best-match movie id for a title — the first step for both
        relations (collection) and recommendations, since neither is
        stored locally and both need TMDB's own numeric id to query."""
        payload = self._get("/search/movie", {"query": title})
        candidates = payload.get("results") or []
        return candidates[0]["id"] if candidates else None

    def find_tv_id(self, title: str) -> int | None:
        payload = self._get("/search/tv", {"query": title})
        candidates = payload.get("results") or []
        return candidates[0]["id"] if candidates else None

    def tv_season_episodes(self, tv_id: int, season_number: int) -> list[dict[str, Any]]:
        """Real per-episode data for one TMDB season."""
        payload = self._get(f"/tv/{tv_id}/season/{season_number}", {})
        episodes = payload.get("episodes") or []
        return [
            {
                "episode_number": ep.get("episode_number"),
                "title": ep.get("name"),
                "description": ep.get("overview") or None,
                "air_date": ep.get("air_date") or None,
                "runtime_minutes": ep.get("runtime"),
                "still_url": f"{_STILL_BASE}{ep['still_path']}" if ep.get("still_path") else None,
            }
            for ep in episodes
            if ep.get("episode_number") is not None
        ]

    def tv_all_episodes(self, tv_id: int) -> list[dict[str, Any]]:
        """Every episode across every TMDB season, renumbered into one
        continuous run (1, 2, 3, ...) — used as a third episode source
        for anime. Anime this app tracks as a single flat season often
        maps to *many* TMDB seasons (arcs) for very long shows like One
        Piece, so a flat renumbering is what actually lines up with this
        app's own single-season episode numbering, rather than trusting
        TMDB's own per-arc episode numbers."""
        details = self._tv_details(tv_id)
        season_numbers = sorted(
            s["season_number"]
            for s in details.get("seasons", [])
            if s.get("season_number") is not None and s["season_number"] > 0
        )
        all_episodes: list[dict[str, Any]] = []
        for season_number in season_numbers:
            try:
                all_episodes.extend(self.tv_season_episodes(tv_id, season_number))
            except TMDBError:
                continue
        for i, episode in enumerate(all_episodes, start=1):
            episode["episode_number"] = i
        return all_episodes

    def movie_relations(self, title: str) -> dict[str, Any]:
        """A movie's real "relations" on TMDB is the collection it
        belongs to (e.g. every Mad Max film) — the only franchise concept
        TMDB actually has. Most movies aren't in one; that's a normal,
        empty result, not an error."""
        movie_id = self.find_movie_id(title)
        if movie_id is None:
            return {"collection_name": None, "related": []}
        details = self._details(movie_id)
        collection = details.get("belongs_to_collection")
        if not collection:
            return {"collection_name": None, "related": []}
        collection_data = self._get(f"/collection/{collection['id']}", {})
        parts = collection_data.get("parts") or []
        related = [
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "year": (p.get("release_date") or "")[:4] or None,
                "poster_url": f"{_POSTER_BASE}{p['poster_path']}" if p.get("poster_path") else None,
            }
            for p in parts
            if p.get("id") != movie_id
        ]
        return {"collection_name": collection.get("name"), "related": related}

    def movie_recommendations(self, title: str, limit: int = 10) -> list[dict[str, Any]]:
        movie_id = self.find_movie_id(title)
        if movie_id is None:
            return []
        payload = self._get(f"/movie/{movie_id}/recommendations", {})
        results = payload.get("results") or []
        return [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "year": (r.get("release_date") or "")[:4] or None,
                "poster_url": f"{_POSTER_BASE}{r['poster_path']}" if r.get("poster_path") else None,
            }
            for r in results[:limit]
        ]

    def tv_recommendations(self, title: str, limit: int = 10) -> list[dict[str, Any]]:
        tv_id = self.find_tv_id(title)
        if tv_id is None:
            return []
        payload = self._get(f"/tv/{tv_id}/recommendations", {})
        results = payload.get("results") or []
        return [
            {
                "id": r.get("id"),
                "title": r.get("name"),
                "year": (r.get("first_air_date") or "")[:4] or None,
                "poster_url": f"{_POSTER_BASE}{r['poster_path']}" if r.get("poster_path") else None,
            }
            for r in results[:limit]
        ]
