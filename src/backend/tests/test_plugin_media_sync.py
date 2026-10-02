"""Public media sync behavior against the existing SQLAlchemy domain models."""

import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.database.models.movies import MovieStatus
from src.main import app  # noqa: F401 - register the complete model graph
from src.plugin_api.media_sync import MediaSyncInput, dispatch_media_sync, media_identity


class Db:
    def __init__(self):
        self.rows = {}
        self.added = []

    async def execute(self, statement, params=None):
        return None

    async def scalar(self, statement):
        parameters = statement.compile().params
        identity = parameters.get("id_1")
        table = statement.column_descriptions[0]["entity"].__tablename__
        return self.rows.get((table, identity))

    def add(self, media):
        self.rows[(media.__tablename__, media.id)] = media
        self.added.append(media)

    async def flush(self):
        pass

    async def commit(self):
        pass


def sync(db, user, payload):
    return asyncio.run(
        dispatch_media_sync(db, plugin_id="test.provider", user_id=user, payload=payload)
    )


def data(kind="movie", **extra):
    return {
        "source": "provider",
        "source_scope": "https://server:user",
        "external_id": "remote-1",
        "media_type": kind,
        "title": "Title",
        **extra,
    }


def test_identity_is_user_and_provider_scoped_and_survives_title_change():
    user = uuid4()
    first = media_identity("test.provider", user, MediaSyncInput(**data()))
    assert first == media_identity("test.provider", user, MediaSyncInput(**data(title="Renamed")))
    assert first != media_identity("test.provider", uuid4(), MediaSyncInput(**data()))
    assert first != media_identity("other.provider", user, MediaSyncInput(**data()))


def test_movie_watched_reversal_partial_progress_and_local_conflict():
    db, user = Db(), uuid4()
    first = sync(db, user, data(played=True))
    assert first["status"] == "WATCHED"
    second = sync(db, user, data(expected_revision=first["revision"], in_progress=True))
    assert second["id"] == first["id"] and second["status"] == "IN_PROGRESS"
    third = sync(db, user, data(expected_revision=second["revision"], title="Renamed"))
    assert third["status"] == "WATCHLIST" and len(db.added) == 1
    db.added[0].status = MovieStatus.DROPPED
    assert (
        sync(db, user, data(expected_revision=third["revision"], played=True))["conflict"]
        == "local_watch_state_changed"
    )
    assert db.added[0].status == MovieStatus.DROPPED


@pytest.mark.parametrize("kind", ["tv_show", "anime"])
def test_episode_flags_partial_show_completion_and_removal(kind):
    db, user = Db(), uuid4()
    first = sync(db, user, data(kind, played=True))
    assert first["status"] == "WATCHLIST"
    episode = {"external_id": "episode-1", "season": 1, "number": 1, "watched": True}
    second = sync(db, user, data(kind, expected_revision=first["revision"], episodes=[episode]))
    assert second["status"] == "IN_PROGRESS"
    third = sync(
        db,
        user,
        data(
            kind,
            expected_revision=second["revision"],
            episodes=[{**episode, "external_id": "episode-2", "number": 2, "watched": False}],
            inventory_complete=True,
        ),
    )
    assert third["status"] == "IN_PROGRESS"
    season = db.added[0].seasons[0]
    assert season.episodes_watched == 1 and season.episode_count == 2
    fourth = sync(
        db,
        user,
        data(
            kind,
            expected_revision=third["revision"],
            episodes=[{**episode, "external_id": "episode-2", "number": 2}],
            inventory_complete=True,
        ),
    )
    assert fourth["status"] == "WATCHED" and season.status.value == "WATCHED"
    assert all(e.watched for e in season.episodes)
    fifth = sync(
        db,
        user,
        data(
            kind,
            expected_revision=fourth["revision"],
            episodes=[{**episode, "removed": True}],
            inventory_complete=True,
        ),
    )
    assert fifth["status"] == "WATCHED" and season.episode_count == 1
    season.episodes[0].watched = False
    assert (
        sync(db, user, data(kind, expected_revision=fifth["revision"], inventory_complete=True))[
            "conflict"
        ]
        == "local_watch_state_changed"
    )


def test_remapping_never_duplicates_or_drops_local_media():
    db, user = Db(), uuid4()
    sync(db, user, data())
    assert sync(db, user, data("anime"))["conflict"] == "category_changed"
    assert len(db.added) == 1


def test_input_bounds_and_invalid_media_type():
    for payload in (
        data(media_type="game"),
        data(title=""),
        data(episodes=[{"watched": True}]),
        data(episodes=[{}] * 101),
    ):
        with pytest.raises(ValidationError):
            MediaSyncInput.model_validate(payload)


def test_episode_renumbering_retains_identity_and_watched_semantics():
    db, user = Db(), uuid4()
    episode = {"external_id": "episode", "season": 1, "number": 1, "watched": True}
    first = sync(db, user, data("tv_show", episodes=[episode]))
    original_id = db.added[0].seasons[0].episodes[0].id
    result = sync(
        db,
        user,
        data(
            "tv_show",
            expected_revision=first["revision"],
            episodes=[{**episode, "season": 2, "number": 3, "watched": False}],
            inventory_complete=True,
        ),
    )
    assert result["status"] == "WATCHLIST"
    moved = db.added[0].seasons[1].episodes[0]
    assert moved.id == original_id and moved.episode_number == 3 and not moved.watched
    assert not db.added[0].seasons[0].episodes
