"""Game create/update behaviour against the real test database.

Each test makes its own scratch user and deletes it afterwards (which
cascades to every game it made), so nothing is left behind.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import delete, func, select

from src.api.routes import games, movies
from src.api.schemas.game import GameCreate, GameUpdate
from src.api.schemas.movie import MovieUpdate
from src.database.models.game import Game
from src.database.models.movies import Movie, MovieStatus
from src.database.models.user import User
from src.database.session import SessionLocal


@pytest.fixture(autouse=True)
def no_game_folders(monkeypatch):
    monkeypatch.setattr(games, "create_game_folder", lambda *_args: None)


@pytest.fixture
async def scratch_user():
    async with SessionLocal() as db:
        user = User(
            username=f"t_{uuid.uuid4().hex[:10]}",
            email=f"{uuid.uuid4().hex[:10]}@example.test",
            password_hash="x",
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    # a plain object: route handlers only read `.id`, and a mapped instance
    # expires at every commit
    yield SimpleNamespace(id=user_id)
    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


def _create(folder: str, guid: uuid.UUID | None = None, **extra) -> GameCreate:
    return GameCreate(
        title=folder.replace("_", " "), folder_location=folder, playnite_guid=guid, **extra
    )


async def _count_games(user_id) -> int:
    async with SessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(Game).where(Game.user_id == user_id)
        )


async def test_repeated_playnite_create_returns_the_existing_game(scratch_user):
    guid = uuid.uuid4()
    async with SessionLocal() as db:
        first_response = Response()
        first = await games.create_game(
            _create("Two_Worlds_II_HD", guid), first_response, db, scratch_user
        )
        first_id = first.id
    async with SessionLocal() as db:
        again_response = Response()
        again = await games.create_game(
            _create("Two_Worlds_II_HD", guid), again_response, db, scratch_user
        )
        assert again.id == first_id
    assert again_response.status_code == 200
    assert await _count_games(scratch_user.id) == 1


async def test_playnite_create_adopts_a_manual_game_in_the_same_folder(scratch_user):
    async with SessionLocal() as db:
        manual = await games.create_game(_create("NIMBY_Rails"), Response(), db, scratch_user)
        manual_id = manual.id
    guid = uuid.uuid4()
    async with SessionLocal() as db:
        adopted = await games.create_game(
            _create("NIMBY_Rails", guid), Response(), db, scratch_user
        )
        assert adopted.id == manual_id
        assert adopted.playnite_guid == guid
    assert await _count_games(scratch_user.id) == 1


async def test_folder_claimed_by_a_different_playnite_game_is_still_a_conflict(scratch_user):
    async with SessionLocal() as db:
        await games.create_game(_create("Shared", uuid.uuid4()), Response(), db, scratch_user)
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await games.create_game(_create("Shared", uuid.uuid4()), Response(), db, scratch_user)
    assert exc.value.status_code == 409


async def test_manual_create_into_a_taken_folder_is_a_conflict(scratch_user):
    async with SessionLocal() as db:
        await games.create_game(_create("Taken"), Response(), db, scratch_user)
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await games.create_game(_create("Taken"), Response(), db, scratch_user)
    assert exc.value.status_code == 409


async def test_concurrent_playnite_creates_do_not_fail_or_duplicate(scratch_user):
    guid = uuid.uuid4()

    async def create_once():
        async with SessionLocal() as db:
            game = await games.create_game(_create("Race_Game", guid), Response(), db, scratch_user)
            return game.id

    ids = await asyncio.gather(*(create_once() for _ in range(4)))
    assert len(set(ids)) == 1
    assert await _count_games(scratch_user.id) == 1


async def test_update_can_clear_optional_fields_but_not_required_ones(scratch_user):
    async with SessionLocal() as db:
        game = await games.create_game(
            _create(
                "Clearable",
                developer="Someone",
                platform="Switch",
                priority="2",
                sort_title="custom sort",
                created_at=1_600_000_000,
            ),
            Response(),
            db,
            scratch_user,
        )
        game_id = game.id
        assert game.created_at == 1_600_000_000
        assert game.sort_title == "custom sort"

    async with SessionLocal() as db:
        updated = await games.update_game(
            game_id,
            GameUpdate(
                developer=None,
                platform=None,
                priority=None,
                title=None,
                sort_title=None,
                tags=None,
                created_at=1_700_000_000,
            ),
            db,
            scratch_user,
        )
        assert updated.developer is None
        assert updated.platform is None
        assert updated.priority is None
        assert updated.title == "Clearable"  # null for a required field is ignored
        assert updated.sort_title == "clearable"  # a cleared sorting name re-derives
        assert updated.tags == []
        assert updated.created_at == 1_700_000_000


async def test_saving_a_left_off_point_starts_a_movie_and_finishing_clears_it(scratch_user):
    async with SessionLocal() as db:
        movie = Movie(
            user_id=scratch_user.id,
            title="Long Film",
            sort_title="long film",
            status=MovieStatus.WATCHLIST,
            studios=[],
            countries=[],
            languages=[],
            genres=[],
            tags=[],
            features=[],
            locked_fields=[],
        )
        db.add(movie)
        await db.commit()
        movie_id = movie.id

    async with SessionLocal() as db:
        started = await movies.update_movie(
            movie_id, MovieUpdate(progress_minutes=47), db, scratch_user
        )
        assert started.status == MovieStatus.IN_PROGRESS
        assert started.progress_minutes == 47

    async with SessionLocal() as db:
        finished = await movies.update_movie(
            movie_id, MovieUpdate(status=MovieStatus.WATCHED), db, scratch_user
        )
        assert finished.status == MovieStatus.WATCHED
        assert finished.progress_minutes is None


async def test_personal_key_cards_report_a_server_wide_fallback(monkeypatch):
    """#234: a key saved under Server Integrations covers searches for users
    without their own, so the personal cards must say so instead of
    reading "Not configured"."""
    from src.api.routes import settings as settings_routes

    monkeypatch.setattr(settings_routes.settings, "STEAMGRIDDB_API_KEY", "server-key")
    monkeypatch.setattr(settings_routes.settings, "GIANTBOMB_API_KEY", None)
    user = User(id=uuid.uuid4(), username="nobody", email="nobody@example.test")
    async with SessionLocal() as db:
        status = await settings_routes.get_provider_credentials(db, user)

    assert status["SteamGridDB"] == {"status": "not_configured", "server_configured": True}
    assert status["GiantBomb"]["server_configured"] is False
    assert "server-key" not in str(status)
