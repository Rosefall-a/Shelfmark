"""Apply a normalized AniList public-list import to a user's library."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.anime import Anime, AnimeSeason
from src.features.metadata.anime.anilist_import import AniListImportClient


def _derive_sort_title(title: str) -> str:
    lowered = title.strip().lower()
    for article in ("a ", "an ", "the "):
        if lowered.startswith(article):
            return lowered[len(article) :]
    return lowered


async def import_anilist_library(
    db: AsyncSession, user_id: UUID, username: str, update_existing: bool = False
) -> dict[str, Any]:
    """Fetch and apply one public AniList list. The caller owns the session."""
    entries = await __import__("asyncio").to_thread(
        AniListImportClient().fetch_user_anime, username
    )
    created = updated = skipped = 0
    errors: list[str] = []
    for entry in entries:
        try:
            show = await db.scalar(
                select(Anime).where(
                    Anime.user_id == user_id,
                    Anime.anilist_id == entry["anilist_id"],
                    Anime.deleted_at.is_(None),
                )
            )
            if show is not None and not update_existing:
                skipped += 1
                continue

            def parsed(key: str):
                value = entry[key]
                return date.fromisoformat(value) if value else None

            if show is None:
                show = Anime(
                    user_id=user_id,
                    title=entry["title"],
                    sort_title=_derive_sort_title(entry["title"]),
                    description=entry["description"],
                    first_air_date=parsed("first_air_date"),
                    episode_runtime_minutes=entry["episode_runtime_minutes"],
                    studios=entry["studios"],
                    countries=entry["countries"],
                    languages=[],
                    genres=entry["genres"],
                    tags=[],
                    features=[],
                    format=entry["format"],
                    anilist_score=entry["anilist_score"],
                    anilist_id=entry["anilist_id"],
                    poster_url=entry["poster_url"],
                    backdrop_url=entry["backdrop_url"],
                    status=entry["status"],
                    priority=entry["priority"],
                    rewatches=entry["repeat"],
                    note=entry["note"],
                    start_date=parsed("start_date"),
                    end_date=parsed("end_date"),
                    rating_overall=entry["rating_overall"],
                )
                db.add(show)
                await db.flush()
                db.add(
                    AnimeSeason(
                        show_id=show.id,
                        season_number=1,
                        episode_count=entry["episode_count"],
                        episodes_watched=entry["progress"],
                        status=entry["status"],
                    )
                )
                created += 1
            else:
                show.sort_title = _derive_sort_title(entry["title"])
                for field in (
                    "title",
                    "description",
                    "first_air_date",
                    "episode_runtime_minutes",
                    "studios",
                    "countries",
                    "genres",
                    "format",
                    "anilist_score",
                    "poster_url",
                    "backdrop_url",
                    "status",
                    "priority",
                    "rewatches",
                    "note",
                    "start_date",
                    "end_date",
                    "rating_overall",
                ):
                    setattr(
                        show,
                        field,
                        parsed(field)
                        if field in {"first_air_date", "start_date", "end_date"}
                        else entry[field],
                    )
                season = show.seasons[0] if show.seasons else None
                if season is None:
                    season = AnimeSeason(show_id=show.id, season_number=1)
                    db.add(season)
                season.episode_count = entry["episode_count"]
                season.episodes_watched = entry["progress"]
                season.status = entry["status"]
                updated += 1
            await db.commit()
        except Exception as exc:
            await db.rollback()
            skipped += 1
            errors.append(f"{entry.get('title', 'Unknown title')}: {exc}")
    return {
        "fetched": len(entries),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:20],
    }
