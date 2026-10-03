"""Real PostgreSQL transactions for shared identity and replay-safe provider state."""

from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.routes.media_provider import provider_state
from src.core.config import settings
from src.database.models.media_provider import MediaPlaybackEvent, MediaProviderLink
from src.database.models.movies import Movie, MovieStatus
from src.database.models.tv_show import TVEpisode, TVSeason, TVShow, TVShowStatus
from src.database.models.user import User
from src.main import app  # noqa: F401 - initialize the complete model graph
from src.plugin_api.media_enrichment import dispatch_enrichment


@pytest.fixture
async def database():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as db:
            user = User(
                id=uuid4(),
                username="media-test-" + uuid4().hex,
                email=uuid4().hex + "@example.test",
                password_hash="unused",
            )
            db.add(user)
            await db.flush()
            yield db, user
        await transaction.rollback()
    await engine.dispose()


def payload(**overrides):
    return {
        "source": "media-provider",
        "source_scope": "server:user",
        "external_id": "film-1",
        "sync_mode": "enrich",
        "media_type": "movie",
        "title": "Existing film",
        "release_year": 2025,
        "provider_ids": {"tmdb": "123"},
        "played": True,
        "inventory_complete": True,
        "playback": {
            "position_ticks": 300000000,
            "runtime_ticks": 600000000,
            "percentage": 50,
            "play_count": 3,
            "last_played_at": 1770000000,
        },
        **overrides,
    }


async def sync(db, user, **overrides):
    return await dispatch_enrichment(
        db, plugin_id="test.enrichment", user_id=user.id, payload=payload(**overrides)
    )


async def native_movie(db, user, **fields):
    movie = Movie(
        id=uuid4(),
        user_id=user.id,
        title="Existing film",
        sort_title="existing film",
        release_date=date(2025, 1, 1),
        status=MovieStatus.WATCHLIST,
        provider_ids={"tmdb": "123"},
        **fields,
    )
    db.add(movie)
    await db.flush()
    return movie


async def test_two_accounts_merge_without_recreating_or_overwriting_local_rating(database):
    db, user = database
    movie = await native_movie(db, user, rating_overall=9, note="Keep me", locked_fields=["title"])
    first = await sync(
        db,
        user,
        title="Remote rename",
        metadata={"rating_overall": 4, "description": "New metadata"},
    )
    second = await sync(db, user, source_scope="another-server:user", external_id="other-id")
    assert first["id"] == second["id"] == str(movie.id)
    assert (
        await db.scalar(select(func.count()).select_from(Movie).where(Movie.user_id == user.id))
        == 1
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MediaProviderLink)
            .where(MediaProviderLink.user_id == user.id)
        )
        == 2
    )
    assert movie.title == "Existing film" and movie.note == "Keep me" and movie.rating_overall == 9
    assert movie.description == "New metadata" and movie.rewatches == 2


async def test_unique_title_year_match_and_ambiguous_review(database):
    db, user = database
    movie = await native_movie(db, user)
    movie.provider_ids = {}
    assert (await sync(db, user))["id"] == str(movie.id)
    twin = await native_movie(db, user)
    twin.provider_ids = {}
    result = await sync(db, user, source_scope="third-account", provider_ids={})
    assert result["conflict"] == "ambiguous_match"
    assert {v["id"] for v in result["candidates"]} == {str(movie.id), str(twin.id)}


async def test_disabling_merging_creates_one_stable_separate_record(database):
    db, user = database
    movie = await native_movie(db, user)
    first = await sync(db, user, auto_merge=False)
    replay = await sync(db, user, auto_merge=False)
    assert first["id"] != str(movie.id) and first["id"] == replay["id"]
    assert replay["replayed"] is True


async def test_metadata_progress_refresh_preserves_local_watch_edit_and_flags_remote_change(
    database,
):
    db, user = database
    first = await sync(db, user)
    movie = await db.get(Movie, UUID(first["id"]))
    movie.status = MovieStatus.DROPPED
    await db.flush()
    result = await sync(db, user, metadata={"description": "A better synopsis"})
    assert "conflict" not in result and movie.status == MovieStatus.DROPPED
    assert movie.description == "A better synopsis"
    conflict = await sync(db, user, played=False, in_progress=True)
    assert conflict["conflict"] == "local_watch_state_changed"
    accepted = await sync(db, user, played=False, in_progress=True, force_watch=True)
    assert accepted["status"] == "IN_PROGRESS"


async def test_history_replay_updates_session_duration_and_rating_only_when_absent(database):
    db, user = database
    event = {
        "external_id": "session:unique",
        "played_at": 1770000000,
        "duration_seconds": 40,
        "provenance": "reported_session",
    }
    first = await sync(db, user, metadata={"rating_overall": 7}, history=[event])
    await sync(
        db, user, metadata={"rating_overall": 2}, history=[{**event, "duration_seconds": 90}]
    )
    movie = await db.get(Movie, UUID(first["id"]))
    assert movie.rating_overall == 7
    events = list(
        (
            await db.scalars(
                select(MediaPlaybackEvent).where(MediaPlaybackEvent.user_id == user.id)
            )
        ).all()
    )
    assert len(events) == 1 and events[0].duration_seconds == 90
    result = await provider_state("movie", movie.id, user, db, offset=0, limit=50)
    assert result["history"][0]["duration_seconds"] == 90
    assert result["sources"][0]["playback"]["percentage"] == 50


async def test_owned_target_and_provider_state_cannot_cross_user_boundary(database):
    db, user = database
    first = await sync(db, user)
    foreign = User(
        id=uuid4(),
        username=uuid4().hex,
        email=uuid4().hex + "@test.invalid",
        password_hash="unused",
    )
    db.add(foreign)
    await db.flush()
    with pytest.raises(LookupError, match="owned target"):
        await sync(db, foreign, target_id=first["id"])
    with pytest.raises(HTTPException) as error:
        await provider_state("movie", UUID(first["id"]), foreign, db, offset=0, limit=50)
    assert error.value.status_code == 404


async def test_episode_number_merge_retains_existing_episode_identity_and_progress(database):
    db, user = database
    show = TVShow(
        id=uuid4(),
        user_id=user.id,
        title="Existing show",
        sort_title="existing show",
        provider_ids={"tvdb": "42"},
        status=TVShowStatus.IN_PROGRESS,
    )
    season = TVSeason(
        id=uuid4(),
        season_number=0,
        status=TVShowStatus.IN_PROGRESS,
        episode_count=1,
        episodes_watched=0,
    )
    episode = TVEpisode(id=uuid4(), episode_number=1, title="Special", watched=False)
    season.episodes = [episode]
    show.seasons = [season]
    db.add(show)
    await db.flush()
    episode_id = episode.id
    result = await sync(
        db,
        user,
        media_type="tv_show",
        title="Existing show",
        provider_ids={"tvdb": "42"},
        episodes=[
            {
                "external_id": "special",
                "season": 0,
                "number": 1,
                "title": "Special renamed",
                "watched": True,
            }
        ],
        episode_progress={"special": {"position_ticks": 5, "play_count": 2}},
    )
    assert result["id"] == str(show.id) and result["status"] == "IN_PROGRESS"
    assert season.episodes[0].id == episode_id and season.episodes[0].watched
    state = await provider_state("tv", show.id, user, db, offset=0, limit=50)
    assert state["sources"][0]["episode_progress"]["special"]["season"] == 0
    completed = await sync(
        db,
        user,
        media_type="tv_show",
        title="Existing show",
        provider_ids={"tvdb": "42"},
        episodes=[
            {
                "external_id": "special",
                "season": 0,
                "number": 2,
                "title": "Special moved",
                "watched": True,
            }
        ],
        episode_progress={"special": {"position_ticks": 0, "play_count": 2}},
    )
    assert completed["status"] == "WATCHED"
    assert len(season.episodes) == 1 and season.episodes[0].id == episode_id
    assert season.episodes[0].episode_number == 2


async def test_collection_ids_cannot_merge_different_films(database):
    db, user = database
    movie = await native_movie(db, user)
    movie.provider_ids = {"tmdbcollection": "shared-collection"}
    result = await sync(
        db,
        user,
        title="Different sequel",
        release_year=2026,
        provider_ids={"tmdbcollection": "shared-collection"},
    )
    assert result["id"] != str(movie.id)


async def test_cross_account_updates_do_not_appear_as_local_watch_conflicts(database):
    db, user = database
    first = await sync(db, user, played=False, in_progress=False)
    await sync(db, user, source_scope="second-user", played=True)
    result = await sync(db, user, played=True, in_progress=True)
    assert "conflict" not in result and result["id"] == first["id"]
    movie = await db.get(Movie, UUID(first["id"]))
    assert movie.status == MovieStatus.IN_PROGRESS


async def test_remote_unavailability_preserves_local_watch_and_metadata(database):
    db, user = database
    first = await sync(db, user)
    movie = await db.get(Movie, UUID(first["id"]))
    movie.status = MovieStatus.DROPPED
    movie.note = "Retain my record"
    await db.flush()
    unavailable = await sync(
        db, user, availability_only=True, available=False, title="Discard this rename"
    )
    assert unavailable["id"] == first["id"]
    assert movie.title == "Existing film" and movie.note == "Retain my record"
    assert movie.status == MovieStatus.DROPPED
    state = await provider_state("movie", movie.id, user, db, offset=0, limit=50)
    assert not state["sources"][0]["available"]


async def test_plugin_purge_removes_owned_source_state_but_retains_native_record(database):
    from src.api.routes.plugins import _purge_plugin_database

    db, user = database
    result = await sync(
        db,
        user,
        history=[
            {"external_id": "session", "played_at": 1770000000, "provenance": "reported_session"}
        ],
    )
    await _purge_plugin_database(db, "test.enrichment")
    await db.flush()
    assert await db.get(Movie, UUID(result["id"])) is not None
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MediaProviderLink)
            .where(MediaProviderLink.user_id == user.id)
        )
        == 0
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MediaPlaybackEvent)
            .where(MediaPlaybackEvent.user_id == user.id)
        )
        == 0
    )
