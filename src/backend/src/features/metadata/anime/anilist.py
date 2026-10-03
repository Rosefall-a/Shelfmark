# pylint: disable=too-many-lines,missing-module-docstring,missing-function-docstring,too-many-locals
from __future__ import annotations

import re
import time
from typing import Any

import requests

from src.features.metadata.rate_limit import throttle

_URL = "https://graphql.anilist.co"
_TAG_RE = re.compile(r"<[^>]+>")

# AniList's public API rate limit is low and shared across every client
# hitting it, not just this app — a single Related-tab load can already
# mean a dozen+ requests (one per prequel/sequel chain hop, one per
# branch-group reorder lookup), so a 429 is a routine, expected response
# under normal use, not a rare edge case. Retried with backoff (honoring
# `Retry-After` when AniList sends one) instead of surfacing a 502 to the
# user for something that just needed a short wait.
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 10.0
# A small pause between successive requests in a multi-request sequence
# (chain walk, branch-group reordering) so a long chain doesn't burn
# through the rate limit in one burst before any 429 has a chance to
# happen — cheaper than always waiting for the retry backoff.
_PACING_SECONDS = 0.3

# Shared between the search-by-title query and the lookup-by-id query
# below, so a single Media node's fields aren't kept in sync by hand in
# two places.
_MEDIA_FIELDS = """
      id
      idMal
      title {
        romaji
        english
        native
      }
      format
      description(asHtml: false)
      startDate {
        year
        month
        day
      }
      episodes
      duration
      studios(isMain: true) {
        nodes {
          name
        }
      }
      countryOfOrigin
      genres
      coverImage {
        extraLarge
        large
      }
      bannerImage
      averageScore
      siteUrl
"""

_QUERY = f"""
query ($search: String, $perPage: Int) {{
  Page(page: 1, perPage: $perPage) {{
    media(search: $search, type: ANIME) {{
{_MEDIA_FIELDS}
    }}
  }}
}}
"""

# Looks up one exact entry by AniList's own id — used when adding a title
# to the library from somewhere that already carries a real AniList id
# (a relations-graph branch, a chain entry, a recommendation) instead of
# re-searching by title, which can miss or mismatch for a title AniList
# itself would format slightly differently in its search index.
_BY_ID_QUERY = f"""
query ($id: Int) {{
  Media(id: $id, type: ANIME) {{
{_MEDIA_FIELDS}
  }}
}}
"""

# Same lookup, but keyed by MyAnimeList's id (Jikan's own id for the
# entry) — used to recover a missing AniList id for an entry that was
# added while AniList itself was unreachable/rate-limited and only Jikan
# matched, without depending on a fresh title search.
_BY_MAL_ID_QUERY = f"""
query ($idMal: Int) {{
  Media(idMal: $idMal, type: ANIME) {{
{_MEDIA_FIELDS}
  }}
}}
"""


class AniListError(RuntimeError):
    """Raised when AniList responds unsuccessfully."""


def _clean_description(value: str | None) -> str | None:
    if not value:
        return None
    return _TAG_RE.sub("", value).strip() or None


def _format_date(start_date: dict[str, Any] | None) -> str | None:
    if not start_date or not start_date.get("year"):
        return None
    year = start_date["year"]
    month = start_date.get("month") or 1
    day = start_date.get("day") or 1
    return f"{year:04d}-{month:02d}-{day:02d}"


# AniList's MediaFormat enum -> the friendly label Jikan already returns
# directly, so both providers normalize to the same vocabulary.
_FORMAT_LABELS = {
    "TV": "TV",
    "TV_SHORT": "TV Short",
    "MOVIE": "Movie",
    "SPECIAL": "Special",
    "OVA": "OVA",
    "ONA": "ONA",
    "MUSIC": "Music",
}


def _format_label(raw: str | None) -> str | None:
    if not raw:
        return None
    return _FORMAT_LABELS.get(raw, raw.title())


# Up to 50 entries by MyAnimeList id in one request, so filling in a whole
# imported list takes a handful of calls instead of one per title.
_BY_MAL_IDS_QUERY = f"""
query ($ids: [Int], $perPage: Int) {{
  Page(page: 1, perPage: $perPage) {{
    media(idMal_in: $ids, type: ANIME) {{
{_MEDIA_FIELDS}
    }}
  }}
}}
"""
_BY_IDS_QUERY = f"""
query ($ids: [Int], $perPage: Int) {{
  Page(page: 1, perPage: $perPage) {{
    media(id_in: $ids, type: ANIME) {{
{_MEDIA_FIELDS}
    }}
  }}
}}
"""
_TOTALS_QUERY = """
query ($ids: [Int], $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(id_in: $ids, type: ANIME) {
      id
      episodes
      status
      nextAiringEpisode {
        episode
        airingAt
      }
    }
  }
}
"""
_BATCH_SIZE = 50


def _map_media_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalizes one `_MEDIA_FIELDS`-shaped node into the search-result
    dict shape — shared by `search()` (a page of these) and `get_by_id()`
    (exactly one), so the two stay in sync automatically."""
    title = entry.get("title") or {}
    cover = entry.get("coverImage") or {}
    studios = [n["name"] for n in (entry.get("studios") or {}).get("nodes", []) if n.get("name")]
    score = entry.get("averageScore")
    return {
        "id": entry.get("id"),
        "id_mal": entry.get("idMal"),
        "title": title.get("english") or title.get("romaji"),
        "title_english": title.get("english"),
        "title_romaji": title.get("romaji"),
        "title_native": title.get("native"),
        "overview": _clean_description(entry.get("description")),
        "release_date": _format_date(entry.get("startDate")),
        "episode_runtime_minutes": entry.get("duration"),
        "episode_count": entry.get("episodes"),
        "studios": studios,
        "countries": [entry["countryOfOrigin"]] if entry.get("countryOfOrigin") else [],
        "genres": entry.get("genres") or [],
        "poster_url": cover.get("extraLarge") or cover.get("large"),
        "backdrop_url": entry.get("bannerImage"),
        "score": (score / 10) if score is not None else None,
        "format": _format_label(entry.get("format")),
        "url": entry.get("siteUrl"),
    }


def _node_to_dict(node: dict[str, Any]) -> dict[str, Any]:
    node_title = node.get("title") or {}
    cover = node.get("coverImage") or {}
    return {
        "id": node.get("id"),
        "title": node_title.get("english") or node_title.get("romaji"),
        "format": _format_label(node.get("format")),
        "poster_url": cover.get("extraLarge") or cover.get("large"),
        "episode_count": node.get("episodes"),
        "year": (node.get("startDate") or {}).get("year"),
    }


# AniList's own RelationType enum -> a short human label for the graph
# edge (e.g. "Sequel", "Side story") rather than the raw SCREAMING_SNAKE
# value.
_RELATION_LABELS = {
    "ADAPTATION": "Adaptation",
    "PREQUEL": "Prequel",
    "SEQUEL": "Sequel",
    "PARENT": "Parent story",
    "SIDE_STORY": "Side story",
    "CHARACTER": "Shared character",
    "SUMMARY": "Summary",
    "ALTERNATIVE": "Alternative",
    "SPIN_OFF": "Spin-off",
    "OTHER": "Related",
    "SOURCE": "Source",
    "COMPILATION": "Compilation",
    "CONTAINS": "Contains",
}

_EPISODES_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    episodes
    nextAiringEpisode {
      episode
    }
    streamingEpisodes {
      title
      thumbnail
    }
  }
}
"""

# Same two fields the full episode fetch uses to work out the aired
# total, without the streamingEpisodes list — cheap enough to poll every
# few minutes across a whole library instead of only once a day.
_AIRED_COUNT_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    episodes
    nextAiringEpisode {
      episode
      airingAt
    }
  }
}
"""

# A streaming-episode title usually looks like "Episode 12 - The Real Folk
# Blues" — split off the leading "Episode N" so the stored title matches
# what Jikan would have given us, instead of keeping the number baked in.
_EPISODE_TITLE_RE = re.compile(r"^Episode\s+\d+\s*-\s*(.+)$", re.IGNORECASE)


def _blank_episode(
    episode_number: int, still_url: str | None = None, title: str | None = None
) -> dict[str, Any]:
    return {
        "episode_number": episode_number,
        "title": title,
        "description": None,
        "air_date": None,
        "runtime_minutes": None,
        "still_url": still_url,
    }


def _parse_streaming_episodes(streaming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for i, entry in enumerate(streaming, start=1):
        raw_title = entry.get("title") or ""
        match = _EPISODE_TITLE_RE.match(raw_title)
        title = match.group(1) if match else (raw_title or None)
        # AniList's streaming partners often supply a thumbnail with no
        # real title, and AniList fills the gap with the literal string
        # "Untitled" rather than leaving it blank — treated as no title at
        # all so a richer one (Jikan, TMDB) still gets a chance to fill it
        # in on merge, instead of this placeholder counting as "already
        # has a title" and blocking every other source.
        if title and title.strip().lower() == "untitled":
            title = None
        results.append(_blank_episode(i, still_url=entry.get("thumbnail"), title=title))
    return results


def _aired_total(media: dict[str, Any]) -> int | None:
    """How many episodes have actually aired so far. A season can have a
    confirmed total episode count (e.g. 14) while still airing weekly
    (e.g. only 12 out) — `nextAiringEpisode`, when present, is what's
    actually aired and takes priority over the confirmed total. Only
    fall back to `episodes` once AniList reports nothing left scheduled,
    meaning the show has genuinely wrapped."""
    next_airing = media.get("nextAiringEpisode")
    if next_airing and next_airing.get("episode"):
        return next_airing["episode"] - 1
    if media.get("episodes"):
        return media["episodes"]
    return None


def _pad_to_aired_total(results: list[dict[str, Any]], aired_total: int | None) -> None:
    """Fill in plain numbered placeholders for every episode number up to
    `aired_total` that streamingEpisodes didn't cover, in place."""
    if not aired_total:
        return
    known = {r["episode_number"] for r in results}
    for n in range(1, aired_total + 1):
        if n not in known:
            results.append(_blank_episode(n))
    results.sort(key=lambda r: r["episode_number"])


_RELATIONS_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME) {
    id
    title {
      romaji
      english
    }
    format
    episodes
    startDate {
      year
    }
    coverImage {
      extraLarge
      large
    }
    relations {
      edges {
        relationType(version: 2)
        node {
          id
          title {
            romaji
            english
          }
          format
          episodes
          startDate {
            year
          }
          coverImage {
            extraLarge
            large
          }
        }
      }
    }
    recommendations(sort: RATING_DESC, perPage: 10) {
      nodes {
        mediaRecommendation {
          id
          title {
            romaji
            english
          }
          format
          episodes
          startDate {
            year
          }
          coverImage {
            extraLarge
            large
          }
        }
      }
    }
  }
}
"""

# Same shape as _RELATIONS_QUERY but looked up by AniList's own id rather
# than a text search — used while walking the prequel/sequel chain, where
# every step after the first already has a real id to follow instead of
# a title to (re-)search for.
_RELATIONS_BY_ID_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title {
      romaji
      english
    }
    format
    episodes
    startDate {
      year
    }
    coverImage {
      extraLarge
      large
    }
    relations {
      edges {
        relationType(version: 2)
        node {
          id
          title {
            romaji
            english
          }
          format
          episodes
          startDate {
            year
          }
          coverImage {
            extraLarge
            large
          }
        }
      }
    }
    recommendations(sort: RATING_DESC, perPage: 10) {
      nodes {
        mediaRecommendation {
          id
          title {
            romaji
            english
          }
          format
          episodes
          startDate {
            year
          }
          coverImage {
            extraLarge
            large
          }
        }
      }
    }
  }
}
"""

# How far the chain walk follows PREQUEL/SEQUEL edges in each direction,
# and how many off-chain relations (adaptation, side story, source
# manga/novel, etc.) get surfaced as branches — generous enough for a
# real franchise's full run without risking a runaway request chain.
_MAX_CHAIN_HOPS = 8
_MAX_BRANCHES = 40
_CHAIN_RELATION_TYPES = {"PREQUEL", "SEQUEL"}

# _expand_branch_chains checks at most this many top-level branches for a
# hidden prequel/sequel of their own — each check is a real extra AniList
# request, so this bounds an uncached relations fetch to a handful of
# extra round trips instead of one per branch on a franchise with a lot
# of them.
_MAX_BRANCH_CHAIN_EXPANSIONS = 4

# Relation types that read as clutter rather than a genuinely related
# title — a shared-character cameo, or a clip-show/recap compilation —
# so they're left out of the graph entirely rather than competing for
# space with the source manga/novel, side stories, and spin-offs that
# actually matter. "Other" is deliberately NOT filtered: AniList uses it
# for real named specials/shorts too (e.g. a movie recap special isn't
# always tagged more specifically), not just noise.
_LOW_VALUE_BRANCH_TYPES = {"CHARACTER"}

# A movie/OVA/special is reached from the franchise root, not the other
# way round: opening the page of "Gurren Lagann The Movie" used to build
# the graph around that one movie, so it only ever showed its own parent
# and sequel instead of the whole franchise. Entries of these formats
# hop up to their parent TV series first, and the graph is built from
# there with the entry you opened marked as current.
_SHORT_FORMATS = {"MOVIE", "OVA", "ONA", "SPECIAL", "MUSIC"}
_ROOT_FORMATS = {"TV", "TV_SHORT"}
_ROOT_RELATION_TYPES = ("PARENT", "ALTERNATIVE", "SIDE_STORY", "SPIN_OFF")

# Bumped whenever the shape/coverage of the cached payload changes, so
# results cached by an older layout are refetched instead of served stale.
RELATIONS_CACHE_VERSION = 2


def _topological_order(ids: set[int], prequel_of: dict[int, int]) -> list[int] | None:
    """Orders `ids` earliest-prequel-first using each id's prequel
    pointer (only ones pointing within `ids` matter). Returns None if
    the pointers don't fully resolve every id — a partial/cyclic result
    isn't trustworthy enough to reorder anything."""
    if not prequel_of:
        return None
    order: list[int] = []
    remaining = set(ids)
    guard = 0
    while remaining and guard <= len(ids):
        guard += 1
        ready = sorted(i for i in remaining if prequel_of.get(i) not in remaining)
        if not ready:
            break
        order.extend(ready)
        remaining.difference_update(ready)
    return None if remaining else order


def _collect_branches(
    nodes: dict[int, dict[str, Any]], anchor_id: int, chain_ids: list[int]
) -> list[dict[str, Any]]:
    """Every relation attached to the anchor entry itself — not every
    entry in the chain — that isn't itself another chain link:
    adaptation, side story, source manga/novel, etc., up to
    `_MAX_BRANCHES` total. Scoped to just the anchor rather than the
    whole chain on purpose: a real prequel/sequel chain can run deep
    (a long-running show easily has 5+ entries), and giving every one
    of them its own branch subtree leaves nowhere collision-free to put
    them — they'd all have to share the same horizontal band the chain
    row itself occupies, and a wide subtree hanging off an early entry
    can reach into a later entry's own position. Low-value relation
    types (shared character, compilation, ...) are skipped so they
    don't clutter the graph with rarely-useful nodes."""
    branches: list[dict[str, Any]] = []
    seen = set(chain_ids)
    edges = (nodes[anchor_id].get("relations") or {}).get("edges") or []
    for edge in edges:
        if len(branches) >= _MAX_BRANCHES:
            break
        node = edge.get("node")
        if not node:
            continue
        rtype = edge.get("relationType")
        target_id = node["id"]
        if rtype in _CHAIN_RELATION_TYPES and target_id in nodes:
            continue  # already represented as a chain link
        if rtype in _LOW_VALUE_BRANCH_TYPES:
            continue
        if target_id in seen:
            continue
        seen.add(target_id)
        branches.append(
            {
                "anchor_id": anchor_id,
                "anchor_kind": "show",
                "relation_label": _RELATION_LABELS.get(rtype, "Related"),
                **_node_to_dict(node),
            }
        )
    return branches


class AniListClient:
    """Minimal client for AniList's public GraphQL API. No authentication
    required for read-only search queries — OAuth is only needed to
    mutate a user's own AniList list, which this app never does."""

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def _post_graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Every AniList call funnels through here so the 429 retry/backoff
        (and error normalization) only has to be written once. Retries up
        to `_MAX_RETRIES` times, sleeping `Retry-After` when AniList sends
        one, otherwise an increasing backoff — after that, raises a
        friendly rate-limit message instead of AniList's raw 429 body.
        Throttled process-wide (not just within this client instance) so
        the several background loops that each walk the anime library
        (episode refresh, airing check, metadata heal) don't independently
        burst AniList at the same moment and all collide on the same 429s
        — see rate_limit.py."""
        for attempt in range(_MAX_RETRIES + 1):
            throttle("anilist", _PACING_SECONDS)
            try:
                response = self.session.post(
                    _URL, json={"query": query, "variables": variables}, timeout=15
                )
            except requests.RequestException as exc:
                raise AniListError(f"Could not reach AniList: {exc}") from exc
            if response.status_code == 429:
                if attempt >= _MAX_RETRIES:
                    break
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.replace(".", "", 1).isdigit()
                    else _BASE_BACKOFF_SECONDS * (2**attempt)
                )
                time.sleep(min(delay, _MAX_BACKOFF_SECONDS))
                continue
            if response.status_code >= 400:
                raise AniListError(
                    f"AniList request failed ({response.status_code}): {response.text[:200]}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise AniListError("AniList returned invalid JSON.") from exc
            if "errors" in payload:
                messages = "; ".join(e.get("message", "unknown error") for e in payload["errors"])
                raise AniListError(f"AniList returned an error: {messages}")
            return payload
        raise AniListError(
            "AniList is rate-limiting requests right now — wait a bit and try again."
        )

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        payload = self._post_graphql(_QUERY, {"search": query, "perPage": limit})
        media = (payload.get("data") or {}).get("Page", {}).get("media") or []
        return [_map_media_entry(entry) for entry in media[:limit]]

    def get_by_id(self, anilist_id: int) -> dict[str, Any] | None:
        """The same result shape `search()` returns, for exactly one
        already-known AniList id — used when adding a title that a
        relations-graph branch, chain entry, or recommendation already
        carries a real id for, so the add doesn't depend on a fresh
        title search finding (and correctly matching) the same entry."""
        payload = self._post_graphql(_BY_ID_QUERY, {"id": anilist_id})
        media = (payload.get("data") or {}).get("Media")
        if not media:
            return None
        return _map_media_entry(media)

    def get_by_mal_id(self, mal_id: int) -> dict[str, Any] | None:
        """Same result shape as `get_by_id`, keyed by MyAnimeList's id
        instead — recovers a missing AniList id for an entry that was
        matched via Jikan only (e.g. added while AniList was rate-limited)."""
        payload = self._post_graphql(_BY_MAL_ID_QUERY, {"idMal": mal_id})
        media = (payload.get("data") or {}).get("Media")
        if not media:
            return None
        return _map_media_entry(media)

    def _batched(
        self, query: str, ids: list[int], key: str
    ) -> tuple[dict[int, dict[str, Any]], int]:
        found: dict[int, dict[str, Any]] = {}
        failed = 0
        for start in range(0, len(ids), _BATCH_SIZE):
            chunk = ids[start : start + _BATCH_SIZE]
            try:
                payload = self._post_graphql(query, {"ids": chunk, "perPage": _BATCH_SIZE})
            except AniListError:
                failed += len(chunk)
                continue
            for media in ((payload.get("data") or {}).get("Page") or {}).get("media") or []:
                mapped = _map_media_entry(media)
                if mapped.get(key):
                    found[int(mapped[key])] = mapped
        return found, failed

    def get_by_mal_ids(self, mal_ids: list[int]) -> tuple[dict[int, dict[str, Any]], int]:
        """Entries for many MyAnimeList ids at once, keyed by MAL id, in the
        same shape as `get_by_id`. Ids AniList does not know are simply
        absent. Also returns how many ids sat in a batch that failed (rate
        limit or outage), so a caller can say so instead of pretending they
        were looked up."""
        return self._batched(_BY_MAL_IDS_QUERY, mal_ids, "id_mal")

    def final_totals(self, anilist_ids: list[int]) -> dict[int, dict[str, Any]]:
        """For many AniList ids at once: {id: {"total", "planned", "next", "status"}}.
        `total` is the entry's own episode count and only when it has finished
        airing (an airing or cancelled entry's count is a plan, not a fact),
        so it can safely be used to trim episodes some provider attached from
        another entry. `planned` is the count an airing entry announces and
        `next` the number of its next episode and `air_at` when it airs;
        `episodes` is the raw count AniList holds. A batch that fails is
        simply absent from the result."""
        out: dict[int, dict[str, Any]] = {}
        for start in range(0, len(anilist_ids), _BATCH_SIZE):
            chunk = anilist_ids[start : start + _BATCH_SIZE]
            try:
                payload = self._post_graphql(_TOTALS_QUERY, {"ids": chunk, "perPage": _BATCH_SIZE})
            except AniListError:
                continue
            for media in ((payload.get("data") or {}).get("Page") or {}).get("media") or []:
                episodes = media.get("episodes")
                finished = (
                    media.get("status") == "FINISHED" and isinstance(episodes, int) and episodes > 0
                )
                next_airing = media.get("nextAiringEpisode") or {}
                upcoming = next_airing.get("episode")
                out[int(media["id"])] = {
                    "total": episodes if finished else None,
                    # what an airing entry says it will have, when it says
                    "planned": episodes
                    if isinstance(episodes, int) and episodes > 0 and not finished
                    else None,
                    "next": upcoming if isinstance(upcoming, int) else None,
                    "air_at": next_airing.get("airingAt"),
                    "episodes": episodes if isinstance(episodes, int) else None,
                    "status": media.get("status"),
                }
        return out

    def get_by_ids(self, anilist_ids: list[int]) -> tuple[dict[int, dict[str, Any]], int]:
        """Same as `get_by_mal_ids`, keyed by AniList's own id."""
        return self._batched(_BY_IDS_QUERY, anilist_ids, "id")

    def episodes(self, anilist_id: str) -> list[dict[str, Any]]:
        """Episode data via AniList's `streamingEpisodes` — thumbnail +
        title only, no air date or synopsis (AniList doesn't track those
        per-episode). Thinner than Jikan's data, but it's a real fallback
        for when Jikan is unreachable, rather than showing nothing.

        `streamingEpisodes` alone is badly incomplete for long-running
        shows (e.g. only the first ~69 of 1000+ One Piece episodes) — for
        an ongoing show AniList's own `episodes` total is null too (there
        is no fixed total yet), so `nextAiringEpisode.episode - 1` is used
        as the real aired-so-far count when present, and the remainder is
        padded as plain numbered placeholders so the full aired run is at
        least trackable even without rich metadata for every episode."""
        try:
            anilist_id_int = int(anilist_id)
        except (TypeError, ValueError) as exc:
            raise AniListError(f"Invalid AniList id: {anilist_id!r}") from exc
        payload = self._post_graphql(_EPISODES_QUERY, {"id": anilist_id_int})

        media = (payload.get("data") or {}).get("Media")
        if not media:
            return []

        results = _parse_streaming_episodes(media.get("streamingEpisodes") or [])
        _pad_to_aired_total(results, _aired_total(media))
        return results

    def airing_status(self, anilist_id: str) -> tuple[int | None, bool, int | None, int | None]:
        """`(aired_episode_count, is_airing, next_episode_air_at,
        next_episode_number)` — the same fields `episodes()` uses to
        compute a total, without the `streamingEpisodes` list, so this is
        cheap enough to poll every few minutes across a whole library to
        catch a newly-aired episode quickly, instead of running the full
        (thumbnail-fetching, TMDB-backfilling) sync on that cadence.
        `is_airing` is just whether AniList still has a
        `nextAiringEpisode` scheduled; the air-at timestamp is what
        drives a countdown display and the calendar view."""
        try:
            anilist_id_int = int(anilist_id)
        except (TypeError, ValueError) as exc:
            raise AniListError(f"Invalid AniList id: {anilist_id!r}") from exc
        payload = self._post_graphql(_AIRED_COUNT_QUERY, {"id": anilist_id_int})

        media = (payload.get("data") or {}).get("Media")
        if not media:
            return None, False, None, None
        next_airing = media.get("nextAiringEpisode")
        is_airing = bool(next_airing and next_airing.get("episode"))
        air_at = next_airing.get("airingAt") if next_airing else None
        next_number = next_airing.get("episode") if next_airing else None
        return _aired_total(media), is_airing, air_at, next_number

    def _fetch_relations_node(
        self, *, media_id: int | None = None, search: str | None = None
    ) -> dict[str, Any] | None:
        """One request's worth of a single Media node: its own id/title
        plus its direct relations edges and recommendations — the unit
        the chain walk in `relations_chain_and_branches` is built from."""
        variables: dict[str, Any]
        if media_id is not None:
            query, variables = _RELATIONS_BY_ID_QUERY, {"id": media_id}
        else:
            query, variables = _RELATIONS_QUERY, {"search": search}
        payload = self._post_graphql(query, variables)
        return (payload.get("data") or {}).get("Media")

    def _walk_chain(
        self, nodes: dict[int, dict[str, Any]], chain_ids: list[int], anchor_id: int
    ) -> None:
        """Extends `chain_ids`/`nodes` in place, following PREQUEL edges
        backward and SEQUEL edges forward from the anchor, up to
        `_MAX_CHAIN_HOPS` each way, guarded against cycles."""

        def _walk_one_direction(relation_type: str, prepend: bool) -> None:
            current_id = anchor_id
            for _ in range(_MAX_CHAIN_HOPS):
                edges = (nodes[current_id].get("relations") or {}).get("edges") or []
                edge = next((e for e in edges if e.get("relationType") == relation_type), None)
                if not edge or not edge.get("node"):
                    break
                next_id = edge["node"]["id"]
                if next_id in nodes:
                    break  # cycle guard — a franchise's edges can loop back
                time.sleep(_PACING_SECONDS)
                try:
                    next_node = self._fetch_relations_node(media_id=next_id)
                except AniListError:
                    break  # a flaky/missing hop ends the walk, not the whole tab
                if not next_node:
                    break
                nodes[next_id] = next_node
                if prepend:
                    chain_ids.insert(0, next_id)
                else:
                    chain_ids.append(next_id)
                current_id = next_id

        _walk_one_direction("PREQUEL", prepend=True)
        _walk_one_direction("SEQUEL", prepend=False)

    def relations_chain_and_branches(
        self, title: str, anilist_id: str | None = None
    ) -> dict[str, Any]:
        """The full prequel/sequel chain this entry belongs to — walked
        via PREQUEL/SEQUEL edges in both directions, not just the anchor's
        own direct relations — plus every other relation type (adaptation,
        side story, source manga/novel, etc.)
        attached to whichever chain entry it's actually connected to.
        A season otherwise only ever lists its immediate neighbor, which
        reads as missing entries for any franchise 3+ seasons deep."""
        opened = self._fetch_relations_node(
            media_id=int(anilist_id) if anilist_id else None,
            search=None if anilist_id else title,
        )
        if not opened:
            return {
                "chain": [],
                "branches": [],
                "recommendations": [],
                "version": RELATIONS_CACHE_VERSION,
            }
        current_id = opened["id"]
        anchor = self._find_franchise_root(opened) or opened

        nodes: dict[int, dict[str, Any]] = {anchor["id"]: anchor}
        chain_ids: list[int] = [anchor["id"]]
        self._walk_chain(nodes, chain_ids, anchor["id"])

        chain = []
        for node_id in chain_ids:
            entry = _node_to_dict(nodes[node_id])
            entry["is_current"] = node_id == current_id
            chain.append(entry)

        recommendations = []
        for rec in (anchor.get("recommendations") or {}).get("nodes") or []:
            node = rec.get("mediaRecommendation")
            if not node:
                continue
            recommendations.append(_node_to_dict(node))

        branches = self._order_related_branches(_collect_branches(nodes, anchor["id"], chain_ids))
        seen_ids = set(chain_ids) | {b["id"] for b in branches}
        branches.extend(self._expand_branch_chains(branches, seen_ids))
        for b in branches:
            b["is_current"] = b["id"] == current_id
        if current_id not in seen_ids and opened["id"] != anchor["id"]:
            # reached the root but the entry itself sits deeper than the
            # graph looks (a sequel of a sequel of a movie): still show it
            branches.append(
                {
                    "anchor_id": anchor["id"],
                    "anchor_kind": "show",
                    "relation_label": "Related",
                    "is_current": True,
                    **_node_to_dict(opened),
                }
            )

        return {
            "chain": chain,
            "branches": branches,
            "recommendations": recommendations,
            "version": RELATIONS_CACHE_VERSION,
        }

    def _find_franchise_root(self, opened: dict[str, Any]) -> dict[str, Any] | None:
        """For a movie/OVA/special, the parent TV series it hangs off (one
        hop, which is all AniList's PARENT/ALTERNATIVE links need), fetched
        with its own relations. None when the entry is already a series,
        has no such link, or the parent can't be fetched."""
        if (opened.get("format") or "").upper() not in _SHORT_FORMATS:
            return None
        edges = (opened.get("relations") or {}).get("edges") or []
        for wanted in _ROOT_RELATION_TYPES:
            for edge in edges:
                node = edge.get("node")
                if edge.get("relationType") != wanted or not node:
                    continue
                if (node.get("format") or "").upper() not in _ROOT_FORMATS:
                    continue
                time.sleep(_PACING_SECONDS)
                try:
                    return self._fetch_relations_node(media_id=node["id"])
                except AniListError:
                    return None
        return None

    def _expand_branch_chains(
        self, branches: list[dict[str, Any]], seen_ids: set[int]
    ) -> list[dict[str, Any]]:
        """A top-level branch can have its own prequel/sequel that's
        invisible from the anchor's own relations — e.g. Bleach's "BURN
        THE WITCH" ONA has its own prequel special ("BURN THE WITCH
        #0.8") that's only a relation of the ONA itself, one hop past
        what `_collect_branches` ever looks at (the anchor's direct
        relations only). One extra fetch per still-top-level branch,
        pulling in any PREQUEL/SEQUEL neighbor not already known and
        nesting it under that branch (`anchor_kind: "branch"`) — the
        same nested-branch shape `_order_related_branches` already
        produces for a duology it detects. Single hop only (not a full
        walk), restricted to short-form formats that actually tend to
        have their own mini-chain (OVA/ONA/Special/One Shot — a movie or
        source manga essentially never does), and capped to a handful of
        extra fetches total — this is a real AniList request per branch
        checked, and a franchise with a dozen+ branches would otherwise
        turn one relations fetch into a dozen+ more, which is a bad
        trade for a detail few branches actually have."""
        candidates = [
            b
            for b in branches
            if b["anchor_kind"] == "show"
            and (b.get("format") or "").lower() in {"ova", "ona", "special", "one shot"}
        ]
        extra: list[dict[str, Any]] = []
        checked = 0
        for branch in candidates:
            if checked >= _MAX_BRANCH_CHAIN_EXPANSIONS:
                break
            checked += 1
            time.sleep(_PACING_SECONDS)
            try:
                node = self._fetch_relations_node(media_id=branch["id"])
            except AniListError:
                continue
            if not node:
                continue
            for edge in (node.get("relations") or {}).get("edges") or []:
                rtype = edge.get("relationType")
                target = edge.get("node")
                if rtype not in _CHAIN_RELATION_TYPES or not target:
                    continue
                target_id = target["id"]
                if target_id in seen_ids:
                    continue
                seen_ids.add(target_id)
                extra.append(
                    {
                        "anchor_id": branch["id"],
                        "anchor_kind": "branch",
                        "relation_label": _RELATION_LABELS.get(rtype, "Related"),
                        **_node_to_dict(target),
                    }
                )
        return extra

    def _fetch_group_prequel_pointers(
        self, group: list[dict[str, Any]], ids: set[int]
    ) -> dict[int, int]:
        """Fetches each group member's own relations and returns
        {member_id: its_prequel_id} restricted to prequels that are
        themselves in the group (an outside prequel isn't useful for
        ordering the group)."""
        prequel_of: dict[int, int] = {}
        for b in group:
            time.sleep(_PACING_SECONDS)
            try:
                node = self._fetch_relations_node(media_id=b["id"])
            except AniListError:
                continue  # one flaky/missing member shouldn't sink the whole tab
            if not node:
                continue
            for edge in (node.get("relations") or {}).get("edges") or []:
                if edge.get("relationType") != "PREQUEL":
                    continue
                target = (edge.get("node") or {}).get("id")
                if isinstance(target, int) and target in ids:
                    prequel_of[b["id"]] = target
        return prequel_of

    def _order_related_branches(self, branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """A branch group sharing the same anchor and relation label —
        e.g. a two-part movie duology, both tagged ALTERNATIVE to the
        parent show rather than SEQUEL/PREQUEL to it — can still be
        chronologically ordered via their own mutual PREQUEL edges.
        Fetches each 2+-member group once to find that order; every
        member after the first is then reparented onto its immediate
        predecessor (anchor_kind "branch") instead of the show, and
        labeled "Sequel" — a real edge between the siblings themselves,
        matching how the source actually relates them, rather than two
        independent spokes off the show that just happen to sit in the
        right order."""
        groups: dict[tuple[int, str], list[int]] = {}
        for i, b in enumerate(branches):
            groups.setdefault((b["anchor_id"], b["relation_label"]), []).append(i)

        for positions in groups.values():
            # A real duology/trilogy is 2-4 members; a large group sharing
            # a label (e.g. two dozen movies/specials all loosely tagged
            # "Sequel" to the main show, which AniList uses as a catch-all
            # far more often than a genuine narrative chain) is a shared
            # bucket, not a chain — reparenting all of them nose-to-tail
            # would turn 24 independent branches into one 24-deep nested
            # chain the graph has no legible way to draw, and the ids
            # inside it were never meant to represent "watch this right
            # after that" the way a real duology's mutual PREQUEL edges do.
            if not 2 <= len(positions) <= 4:
                continue
            group = [branches[i] for i in positions]
            ids = {b["id"] for b in group}
            prequel_of = self._fetch_group_prequel_pointers(group, ids)
            order = _topological_order(ids, prequel_of)
            if order is None:
                continue  # couldn't fully resolve — leave original order
            by_id = {b["id"]: b for b in group}
            for slot, branch_id in zip(sorted(positions), order, strict=True):
                branches[slot] = by_id[branch_id]
            for prev_id, branch_id in zip(order, order[1:], strict=True):
                child = by_id[branch_id]
                child["anchor_id"] = prev_id
                child["anchor_kind"] = "branch"
                child["relation_label"] = "Sequel"
        return branches
