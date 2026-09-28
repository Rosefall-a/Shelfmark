"""The numbers this app must get exactly right: watch time, completed
seasons, rewatches, notification content and deduplication, status labels
in history, preferences validation, and ani.zip parsing.

Database tests build their own user and titles and delete that user (which
cascades to everything it made) when they finish, so they leave nothing
behind and never touch real data. Run inside the backend container:
    docker compose exec -e PYTHONPATH=/app backend python -m pytest /app/tests -q
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from src.api.routes.media_extras import status_change_detail
from src.api.routes.media_stats import _bucket_counts, _score_stats, get_media_stats
from src.core.preferences import DEFAULTS, validate_preference
from src.database.models.anime import Anime, AnimeEpisode, AnimeSeason, AnimeStatus
from src.database.models.movies import Movie, MovieStatus
from src.database.models.notification import Notification
from src.database.models.user import User
from src.database.session import SessionLocal
from src.features.episode_progress import apply_counter, counter_from_flags, materialize_progress
from src.features.metadata.anime.anizip import AniZipClient
from src.features.metadata.tv.search import _looks_like_anime
from src.features.notifications import _episode_row, generate_for_user
from src.features.tv_seasons import check_new_seasons, new_seasons


# ---------------------------------------------------------------- pure logic
def test_status_change_uses_the_names_shown_in_the_app():
    assert (
        status_change_detail(AnimeStatus.WISHLIST, AnimeStatus.IN_PROGRESS)
        == "Plan to Watch → Watching"
    )
    assert (
        status_change_detail(AnimeStatus.IN_PROGRESS, AnimeStatus.WATCHED) == "Watching → Completed"
    )


def test_status_change_between_equivalent_statuses_is_not_recorded():
    # Wishlist and Watchlist are both "Plan to Watch" to the user
    assert status_change_detail(AnimeStatus.WISHLIST, AnimeStatus.WATCHLIST) is None


def test_preferences_reject_unknown_keys_and_bad_values():
    assert validate_preference("calendar_game_releases", True) is True
    with pytest.raises(ValueError):
        validate_preference("no_such_setting", True)
    with pytest.raises(ValueError):
        validate_preference("calendar_game_releases", "yes")
    with pytest.raises(ValueError):
        validate_preference("calendar_week_start", 3)
    with pytest.raises(ValueError):
        validate_preference("notification_retention_days", 45)
    assert validate_preference("notification_retention_days", 0) == 0


def test_every_default_passes_its_own_validation():
    for key, value in DEFAULTS.items():
        assert validate_preference(key, value) == value


class _Item:
    def __init__(self, status, score=None):
        self.status = status
        self.rating_overall = score


def test_status_buckets_group_the_eight_statuses_into_five():
    items = [
        _Item(AnimeStatus.WISHLIST),
        _Item(AnimeStatus.WATCHLIST),
        _Item(AnimeStatus.WATCHED),
        _Item(AnimeStatus.FAVORITE),
    ]
    counts = _bucket_counts(items)
    assert counts["plan"] == 2
    assert counts["completed"] == 2
    assert counts["watching"] == counts["hold"] == counts["dropped"] == 0


def test_score_stats_average_and_distribution():
    from decimal import Decimal

    stats = _score_stats(
        [
            _Item(AnimeStatus.WATCHED, Decimal("8")),
            _Item(AnimeStatus.WATCHED, Decimal("9")),
            _Item(AnimeStatus.WATCHED, None),
        ]
    )
    assert stats["rated"] == 2
    assert stats["average"] == 8.5
    assert stats["distribution"]["8"] == 1 and stats["distribution"]["9"] == 1


class _Show:
    id = uuid.uuid4()
    title = "Test Show"
    poster_url = None


def test_first_episode_is_a_season_start_and_later_ones_are_episodes():
    prefs = dict(DEFAULTS)
    first = _episode_row("anime", _Show(), 1, 1, 1_700_000_000, prefs)
    later = _episode_row("anime", _Show(), 1, 5, 1_700_000_000, prefs)
    assert first and first["kind"] == "season_started"
    assert later and later["kind"] == "episode_aired" and later["body"] == "Episode 5 aired"
    assert later["event_at"] == 1_700_000_000  # the exact time, untouched


def test_tv_later_seasons_name_the_season():
    row = _episode_row("tv", _Show(), 3, 4, 1_700_000_000, dict(DEFAULTS))
    assert row and row["body"] == "Season 3 episode 4 aired"


def test_notification_toggles_switch_each_kind_off():
    prefs = {**DEFAULTS, "notify_episode_aired": False}
    assert _episode_row("anime", _Show(), 1, 5, 1, prefs) is None
    assert _episode_row("anime", _Show(), 1, 1, 1, prefs) is not None
    prefs = {**DEFAULTS, "notify_season_started": False}
    assert _episode_row("anime", _Show(), 1, 1, 1, prefs) is None


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return _FakeResponse(self.payload)


def test_anizip_keeps_only_this_entrys_numbered_episodes_and_parses_air_time():
    payload = {
        "episodeCount": 2,
        "episodes": {
            "1": {
                "title": {"en": "The Journey`s End"},
                "overview": "Intro.\nSource: X",
                "image": "http://img/1.jpg",
                "airDate": "2023-09-29",
                "airDateUtc": "2023-09-29T14:00:00Z",
                "runtime": 26,
            },
            "2": {"title": {"en": "Second"}, "runtime": 0},
            "3": {"title": {"en": "belongs to a later season"}},
            "S1": {"title": {"en": "special"}},
        },
    }
    episodes = AniZipClient(session=_FakeSession(payload)).episodes("1")  # type: ignore[arg-type]
    assert [e["episode_number"] for e in episodes] == [1, 2]
    first = episodes[0]
    assert first["title"] == "The Journey's End"
    assert first["description"] == "Intro."
    assert first["still_url"] == "http://img/1.jpg"
    assert first["air_at"] == int(datetime(2023, 9, 29, 14, 0, tzinfo=timezone.utc).timestamp())
    assert first["runtime_minutes"] == 26
    assert episodes[1]["runtime_minutes"] is None  # a runtime of 0 is "unknown", not zero minutes


# ------------------------------------------------------- database, rolled back
async def _user(db):
    user = User(
        username=f"t_{uuid.uuid4().hex[:10]}",
        email=f"{uuid.uuid4().hex[:10]}@example.test",
        password_hash="x",
    )
    db.add(user)
    await db.flush()
    # a plain attribute: a mapped one expires at commit and can't be re-read
    # here (generating notifications commits)
    user.scratch_id = user.id  # type: ignore[attr-defined]
    return user


async def _cleanup(db, user):
    """Undo everything a test did. Most tests never commit and a rollback is
    enough, but generating notifications commits, so the scratch user (and,
    by cascade, all its titles and notifications) is deleted outright."""
    await db.rollback()
    await db.execute(delete(User).where(User.id == user.scratch_id))
    await db.commit()


def _anime(user, title="Test Anime", status=AnimeStatus.IN_PROGRESS, rewatches=0, runtime=24):
    return Anime(
        user_id=user.scratch_id,
        title=title,
        sort_title=title.lower(),
        status=status,
        rewatches=rewatches,
        episode_runtime_minutes=runtime,
        studios=[],
        countries=[],
        languages=[],
        genres=[],
        tags=[],
        features=[],
        locked_fields=[],
    )


@pytest.mark.asyncio
async def test_only_watched_episodes_count_and_half_a_season_is_not_completed():
    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = _anime(user)
            db.add(show)
            await db.flush()
            done = AnimeSeason(show_id=show.id, season_number=1, episode_count=4)
            half = AnimeSeason(show_id=show.id, season_number=2, episode_count=4)
            db.add_all([done, half])
            await db.flush()
            db.add_all(
                [
                    AnimeEpisode(season_id=done.id, episode_number=n, watched=True)
                    for n in range(1, 5)
                ]
                + [
                    AnimeEpisode(season_id=half.id, episode_number=n, watched=(n <= 2))
                    for n in range(1, 5)
                ]
            )
            await db.flush()

            anime = (await get_media_stats(db, user))["anime"]
            assert anime["episodes_watched"] == 6  # 4 + 2, the unwatched two are not counted
            assert anime["minutes_watched"] == 6 * 24
            assert anime["seasons_completed"] == 1  # the half-watched season is not a finished one
            assert anime["seasons_in_progress"] == 1
            assert anime["episodes_rewatched"] == 0
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_each_rewatch_adds_the_watched_episodes_again_and_nothing_more():
    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = _anime(user, rewatches=2)
            db.add(show)
            await db.flush()
            season = AnimeSeason(show_id=show.id, season_number=1, episode_count=4)
            db.add(season)
            await db.flush()
            # only 3 of 4 watched: a rewatch multiplies what was actually watched
            db.add_all(
                [
                    AnimeEpisode(season_id=season.id, episode_number=n, watched=(n <= 3))
                    for n in range(1, 5)
                ]
            )
            await db.flush()

            anime = (await get_media_stats(db, user))["anime"]
            assert anime["episodes_watched"] == 3
            assert anime["episodes_rewatched"] == 6
            assert anime["minutes_first"] == 3 * 24
            assert anime["minutes_rewatch"] == 6 * 24
            assert anime["minutes_watched"] == 9 * 24
            assert anime["seasons_completed"] == 0
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_an_episode_with_no_runtime_is_reported_not_guessed():
    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = _anime(user, runtime=None)
            db.add(show)
            await db.flush()
            season = AnimeSeason(show_id=show.id, season_number=1, episode_count=2)
            db.add(season)
            await db.flush()
            db.add_all(
                [
                    AnimeEpisode(
                        season_id=season.id, episode_number=1, watched=True, runtime_minutes=20
                    ),
                    AnimeEpisode(
                        season_id=season.id, episode_number=2, watched=True, runtime_minutes=None
                    ),
                ]
            )
            await db.flush()

            anime = (await get_media_stats(db, user))["anime"]
            assert anime["episodes_watched"] == 2
            assert anime["minutes_watched"] == 20  # only the known runtime is added
            assert anime["episodes_without_runtime"] == 1
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_movie_time_is_runtime_once_plus_each_rewatch_and_skips_unwatched():
    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            common = dict(
                user_id=user.scratch_id,
                genres=[],
                studios=[],
                countries=[],
                languages=[],
                tags=[],
                features=[],
                locked_fields=[],
            )
            db.add_all(
                [
                    Movie(
                        title="Seen twice",
                        sort_title="a",
                        status=MovieStatus.WATCHED,
                        runtime_minutes=100,
                        rewatches=1,
                        **common,
                    ),
                    Movie(
                        title="Planned",
                        sort_title="b",
                        status=MovieStatus.WISHLIST,
                        runtime_minutes=200,
                        **common,
                    ),
                ]
            )
            await db.flush()
            movie = (await get_media_stats(db, user))["movie"]
            assert movie["minutes_first"] == 100
            assert movie["minutes_rewatch"] == 100
            assert movie["minutes_watched"] == 200  # the planned movie adds nothing
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_a_notification_uses_the_exact_air_time_and_is_created_once():
    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = _anime(user)
            db.add(show)
            await db.flush()
            season = AnimeSeason(show_id=show.id, season_number=1, episode_count=12)
            db.add(season)
            await db.flush()
            aired_at = int(datetime.now(tz=timezone.utc).timestamp()) - 3 * 3600
            db.add(AnimeEpisode(season_id=season.id, episode_number=5, air_at=aired_at))
            await db.flush()

            await generate_for_user(db, user.scratch_id)
            await generate_for_user(db, user.scratch_id)  # asking again must not notify twice
            rows = (
                (
                    await db.execute(
                        select(Notification).where(Notification.user_id == user.scratch_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].kind == "episode_aired"
            assert rows[0].body == "Episode 5 aired"
            assert rows[0].event_at == aired_at
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_completed_and_dropped_titles_never_notify():
    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            now = int(datetime.now(tz=timezone.utc).timestamp())
            for status in (AnimeStatus.WATCHED, AnimeStatus.DROPPED):
                show = _anime(user, title=f"done {status.value}", status=status)
                db.add(show)
                await db.flush()
                season = AnimeSeason(show_id=show.id, season_number=1)
                db.add(season)
                await db.flush()
                db.add(AnimeEpisode(season_id=season.id, episode_number=3, air_at=now - 600))
            await db.flush()
            await generate_for_user(db, user.scratch_id)
            rows = (
                (
                    await db.execute(
                        select(Notification).where(Notification.user_id == user.scratch_id)
                    )
                )
                .scalars()
                .all()
            )
            assert rows == []
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_progress_counter_counts_as_watched_even_without_flagged_episode_rows():
    """Most history lives in the season progress counter (what the library
    list shows), not in per-episode flags, and it must count."""
    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = _anime(user, status=AnimeStatus.WATCHED, runtime=20)
            db.add(show)
            await db.flush()
            # 10 of 12 by counter, 8 rows on record, none flagged: 2 counted with no row
            season = AnimeSeason(
                show_id=show.id, season_number=1, episode_count=12, episodes_watched=10
            )
            db.add(season)
            await db.flush()
            db.add_all(
                [
                    AnimeEpisode(season_id=season.id, episode_number=n, runtime_minutes=25)
                    for n in range(1, 9)
                ]
            )
            await db.flush()

            anime = (await get_media_stats(db, user))["anime"]
            assert anime["episodes_watched"] == 10
            assert (
                anime["minutes_watched"] == 8 * 25 + 2 * 20
            )  # rows use their own runtime, the rest the show's
            assert anime["seasons_completed"] == 0  # 10 of 12 is not a finished season
            assert anime["seasons_in_progress"] == 1
            assert anime["most_watched"][0]["episodes"] == 10
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_a_counter_covering_every_episode_completes_the_season():
    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = _anime(user, status=AnimeStatus.WATCHED)
            db.add(show)
            await db.flush()
            db.add(
                AnimeSeason(show_id=show.id, season_number=1, episode_count=26, episodes_watched=26)
            )
            await db.flush()
            anime = (await get_media_stats(db, user))["anime"]
            assert anime["seasons_completed"] == 1
            assert anime["episodes_watched"] == 26
            assert anime["minutes_watched"] == 26 * 24  # no rows on record: the show's runtime
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------------- library counter and episode flags
class _Ep:
    def __init__(self, number, watched=False):
        self.episode_number = number
        self.watched = watched


class _Season:
    def __init__(self, counter, episodes):
        self.episodes_watched = counter
        self.episodes = episodes


def test_checking_an_episode_keeps_what_the_counter_already_counted():
    season = _Season(3, [_Ep(n) for n in range(1, 7)])  # 3 watched by counter, no flags yet
    without_row = materialize_progress(season)
    season.episodes[4].watched = True  # the user checks off episode 5
    counter_from_flags(season, without_row)
    assert [e.watched for e in season.episodes] == [True, True, True, False, True, False]
    assert season.episodes_watched == 4  # 3 that were counted + 1 new, not reset to 1


def test_a_synced_season_is_not_re_flagged_from_the_bottom():
    """Counter 5 with episodes 1-4 and 8 flagged is already fully backed by
    flags; the next change must not also flag episode 5."""
    season = _Season(5, [_Ep(n, watched=n in (1, 2, 3, 4, 8)) for n in range(1, 11)])
    without_row = materialize_progress(season)
    assert without_row == 0
    assert [e.episode_number for e in season.episodes if e.watched] == [1, 2, 3, 4, 8]
    season.episodes[8].watched = True
    counter_from_flags(season, without_row)
    assert season.episodes_watched == 6


def test_unchecking_an_episode_lowers_the_counter():
    season = _Season(3, [_Ep(n) for n in range(1, 7)])
    without_row = materialize_progress(season)
    season.episodes[1].watched = False
    counter_from_flags(season, without_row)
    assert season.episodes_watched == 2


def test_progress_with_no_episode_rows_survives_a_flag_change():
    season = _Season(26, [])  # tracked by number only, episode list never synced
    without_row = materialize_progress(season)
    assert without_row == 26
    counter_from_flags(season, without_row)
    assert season.episodes_watched == 26


def test_setting_the_counter_flags_rows_and_lowering_it_clears_the_highest():
    season = _Season(0, [_Ep(n) for n in range(1, 6)])
    season.episodes_watched = 4
    apply_counter(season, 4)
    assert [e.watched for e in season.episodes] == [True, True, True, True, False]
    season.episodes_watched = 2
    apply_counter(season, 2)
    assert [e.watched for e in season.episodes] == [True, True, False, False, False]


def test_anime_is_recognised_in_tv_search_results():
    assert _looks_like_anime({"genres": ["Anime", "Action"]})
    assert _looks_like_anime({"genres": ["Animation"], "countries": ["JP"]})
    assert _looks_like_anime({"genres": ["Animation"], "languages": ["Japanese"]})
    assert not _looks_like_anime({"genres": ["Animation", "Comedy"], "countries": ["US"]})
    assert not _looks_like_anime({"genres": ["Drama"], "countries": ["JP"]})
    assert not _looks_like_anime({})


@pytest.mark.asyncio
async def test_route_level_flow_flags_moves_the_counter_and_the_library_number():
    from src.api.routes.anime import bulk_set_episodes_watched, update_episode, update_season
    from src.api.schemas.anime import EpisodesBulkWatched, EpisodeUpdate, SeasonUpdate

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = _anime(user)
            db.add(show)
            await db.flush()
            season = AnimeSeason(show_id=show.id, season_number=1, episode_count=10)
            db.add(season)
            await db.flush()
            eps = [AnimeEpisode(season_id=season.id, episode_number=n) for n in range(1, 11)]
            db.add_all(eps)
            await db.commit()
            show_id, season_id = show.id, season.id
            ids = [e.id for e in eps]

            # the library "+" button: counter to 4 flags episodes 1 to 4
            await update_season(show_id, season_id, SeasonUpdate(episodes_watched=4), db, user)
            rows = (
                (await db.execute(select(AnimeEpisode).where(AnimeEpisode.season_id == season_id)))
                .scalars()
                .all()
            )
            assert sorted(e.episode_number for e in rows if e.watched) == [1, 2, 3, 4]

            # checking episode 8 on the title page moves the library number to 5
            await update_episode(show_id, season_id, ids[7], EpisodeUpdate(watched=True), db, user)
            s = (
                await db.execute(select(AnimeSeason).where(AnimeSeason.id == season_id))
            ).scalar_one()
            assert s.episodes_watched == 5

            # a range select adds to it too
            await bulk_set_episodes_watched(
                show_id,
                season_id,
                EpisodesBulkWatched(episode_ids=ids[8:10], watched=True),
                db,
                user,
            )
            s = (
                await db.execute(select(AnimeSeason).where(AnimeSeason.id == season_id))
            ).scalar_one()
            assert s.episodes_watched == 7
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_unchecking_episodes_works_including_ones_the_counter_covered():
    """Unchecking must actually clear the flag and lower the library number,
    both for an episode the user flagged and for one that only the old
    progress counter had counted."""
    from src.api.routes.anime import update_episode
    from src.api.schemas.anime import EpisodeUpdate

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = _anime(user)
            db.add(show)
            await db.flush()
            season = AnimeSeason(
                show_id=show.id, season_number=1, episode_count=6, episodes_watched=4
            )
            db.add(season)
            await db.flush()
            eps = [
                AnimeEpisode(season_id=season.id, episode_number=n) for n in range(1, 7)
            ]  # nothing flagged
            db.add_all(eps)
            await db.commit()
            show_id, season_id = show.id, season.id
            ids = [e.id for e in eps]

            # episode 2 was only counted by the counter; unchecking it must stick
            result = await update_episode(
                show_id, season_id, ids[1], EpisodeUpdate(watched=False), db, user
            )
            episodes = {e.episode_number: e.watched for e in result.seasons[0].episodes}
            assert episodes == {1: True, 2: False, 3: True, 4: True, 5: False, 6: False}
            assert result.seasons[0].episodes_watched == 3

            # and a flagged one
            result = await update_episode(
                show_id, season_id, ids[3], EpisodeUpdate(watched=False), db, user
            )
            assert result.seasons[0].episodes_watched == 2
            assert {e.episode_number for e in result.seasons[0].episodes if e.watched} == {1, 3}
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------------------------- TV new-season check
def test_only_seasons_above_every_known_one_count_as_new():
    listed = [{"season_number": n} for n in range(1, 6)]
    assert [s["season_number"] for s in new_seasons({1, 2, 3}, listed)] == [4, 5]
    assert new_seasons({1, 2, 3, 4, 5}, listed) == []
    # a provider numbering an old season differently never adds one
    assert new_seasons({2, 3, 5}, listed) == []


class _FakeTVMaze:
    def __init__(self, seasons):
        self._seasons = seasons

    def seasons(self, _id):
        return self._seasons


@pytest.mark.asyncio
async def test_new_tv_season_is_added_and_announced_once_but_not_on_the_first_check():
    from src.database.models.tv_show import TVSeason, TVShow, TVShowStatus

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            show = TVShow(
                user_id=user.scratch_id,
                title="Season Test",
                sort_title="season test",
                status=TVShowStatus.WATCHED,
                external_id="1",
                creators=[],
                studios=[],
                countries=[],
                languages=[],
                genres=[],
                tags=[],
                features=[],
                locked_fields=[],
            )
            db.add(show)
            await db.flush()
            db.add(TVSeason(show_id=show.id, season_number=1, episode_count=8))
            await db.commit()
            show_id = show.id

            listed = [
                {"season_number": 1, "name": None, "episode_count": 8, "air_date": "2020-01-01"},
                {"season_number": 2, "name": None, "episode_count": 10, "air_date": "2027-03-01"},
            ]
            show = (await db.execute(select(TVShow).where(TVShow.id == show_id))).scalar_one()
            # first check: the season is added, but nothing is announced
            assert await check_new_seasons(db, show, _FakeTVMaze(listed)) == 1  # type: ignore[arg-type]
            notes = (
                (
                    await db.execute(
                        select(Notification).where(Notification.user_id == user.scratch_id)
                    )
                )
                .scalars()
                .all()
            )
            assert notes == []

            # a season 3 appears later: added and announced, with the premiere date
            listed.append(
                {"season_number": 3, "name": None, "episode_count": None, "air_date": "2028-01-01"}
            )
            show = (await db.execute(select(TVShow).where(TVShow.id == show_id))).scalar_one()
            assert await check_new_seasons(db, show, _FakeTVMaze(listed)) == 1  # type: ignore[arg-type]
            assert (
                await check_new_seasons(db, show, _FakeTVMaze(listed)) == 0
            )  # nothing new the third time
            notes = (
                (
                    await db.execute(
                        select(Notification).where(Notification.user_id == user.scratch_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(notes) == 1
            assert notes[0].body == "Season 3 is listed, premiering 2028-01-01"
            seasons = (
                (await db.execute(select(TVSeason).where(TVSeason.show_id == show_id)))
                .scalars()
                .all()
            )
            assert sorted(s.season_number for s in seasons) == [1, 2, 3]
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------------------------------- game statistics
class _G:
    def __init__(self, title, status="PLAYED", seconds=0, price=None, currency="USD", **kw):
        from types import SimpleNamespace

        self.__dict__.update(
            id=uuid.uuid4(),
            title=title,
            status=SimpleNamespace(value=status),
            playtime_seconds=seconds,
            purchase_price=price,
            purchase_price_currency_code=currency,
            last_played_at=None,
            completion_date=None,
            time_to_beat_hours=None,
            source=None,
            developer=None,
            series=None,
            release_date=None,
            age_rating=None,
            features=[],
        )
        self.__dict__.update(kw)


def test_game_stats_are_exact_and_report_what_is_missing():
    from src.features.game_stats import game_stats

    now = datetime(2026, 9, 19, 12, 0)
    day = 86400
    a = _G(
        "A", seconds=2 * 3600, price=20, source="Steam", last_played_at=now.timestamp() - 3 * day
    )
    b = _G(
        "B", seconds=30 * 3600, price=60, source="Steam", last_played_at=now.timestamp() - 90 * day
    )
    c = _G("C", status="BACKLOG", price=10, time_to_beat_hours=12)
    d = _G("D", status="BACKLOG")
    w = _G("W", status="WISHLIST", price=5)
    stats = game_stats([a, b, c, d, w], {a.id: (5, 10), b.id: (10, 10)}, now)

    assert stats["owned"] == 4  # a wishlist entry is not owned
    assert stats["unplayed"] == {"count": 2, "spent": [{"currency": "USD", "amount": 10.0}]}
    assert stats["median_seconds"] == 16 * 3600 and stats["average_seconds"] == 16 * 3600
    assert stats["played_last_30_days"] == 1
    assert [r["title"] for r in stats["recently_played"]] == ["A", "B"]
    buckets = {r["label"]: r["count"] for r in stats["playtime_buckets"]}
    assert (
        buckets["No playtime recorded"] == 2
        and buckets["1 to 5h"] == 1
        and buckets["25 to 50h"] == 1
    )
    # only the backlog game with an estimate adds hours; the other is reported as missing one
    assert stats["backlog"] == {"count": 2, "hours": 12.0, "without_estimate": 1}
    # (20 + 60) dollars over 32 hours; games with no playtime or no price never enter it
    assert stats["cost_per_hour"] == [
        {"currency": "USD", "per_hour": 2.5, "hours": 32.0, "games": 2}
    ]
    assert stats["fully_unlocked"] == 1
    assert [(r["title"], r["unlocked"], r["total"]) for r in stats["closest_to_full"]] == [
        ("A", 5, 10)
    ]
    assert stats["seconds_by_source"] == [{"name": "Steam", "seconds": 32 * 3600}]


def test_game_stats_with_no_games_say_nothing_instead_of_zero_averages():
    from src.features.game_stats import game_stats

    stats = game_stats([], {}, datetime(2026, 9, 19))
    assert stats["average_seconds"] is None and stats["median_seconds"] is None
    assert stats["cost_per_hour"] == [] and stats["backlog"]["hours"] == 0.0


@pytest.mark.asyncio
async def test_overview_lists_games_being_played_and_counts_achievement_days():
    from src.database.models.game import Game, GameStatus

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            db.add(
                Game(
                    user_id=user.scratch_id,
                    folder_location=f"scratch-{uuid.uuid4()}",
                    title="Now Playing",
                    sort_title="now playing",
                    status=GameStatus.PLAYING,
                    playtime_seconds=5400,
                    tags=[],
                    features=[],
                    collections=[],
                )
            )
            await db.flush()
            data = await get_media_stats(db, user)
            row = next(r for r in data["overview"]["in_progress"] if r["kind"] == "game")
            assert row["title"] == "Now Playing" and row["label"] == "1h 30m played"
            assert data["games"]["insights"]["owned"] == 1
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_two_requests_creating_the_favorites_list_together_make_one():
    import asyncio

    from src.api.routes.media_lists import _ensure_favorites_list
    from src.database.models.media_extras import MediaList

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.commit()

            async def one():
                async with SessionLocal() as other:
                    await _ensure_favorites_list(user.scratch_id, other)

            await asyncio.gather(one(), one(), one())
            rows = (
                (await db.execute(select(MediaList).where(MediaList.user_id == user.scratch_id)))
                .scalars()
                .all()
            )
            assert [r.name for r in rows] == ["Favorites"]
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------------------------------------ MAL import
_MAL = b"""<?xml version="1.0" encoding="UTF-8" ?>
<myanimelist>
  <myinfo><user_export_type>1</user_export_type></myinfo>
  <anime>
    <series_animedb_id>1</series_animedb_id><series_title><![CDATA[Cowboy Bebop]]></series_title>
    <series_type>TV</series_type><series_episodes>26</series_episodes>
    <my_watched_episodes>0</my_watched_episodes><my_start_date>0000-00-00</my_start_date>
    <my_finish_date>2020-05-01</my_finish_date><my_score>9</my_score><my_status>Completed</my_status>
    <my_times_watched>2</my_times_watched><my_tags><![CDATA[space, jazz]]></my_tags>
    <my_comments><![CDATA[classic]]></my_comments>
  </anime>
  <anime>
    <series_animedb_id>2</series_animedb_id><series_title><![CDATA[Some Show]]></series_title>
    <series_type>Movie</series_type><series_episodes>1</series_episodes>
    <my_watched_episodes>0</my_watched_episodes><my_score>0</my_score><my_status>Plan to Watch</my_status>
  </anime>
  <anime>
    <series_animedb_id>3</series_animedb_id><series_title><![CDATA[Ongoing]]></series_title>
    <series_episodes>0</series_episodes><my_watched_episodes>5</my_watched_episodes>
    <my_status>Watching</my_status>
  </anime>
</myanimelist>"""


def test_mal_export_is_read_exactly_and_completed_means_fully_watched():
    from src.features.imports.mal import parse_mal_export

    bebop, movie, ongoing = parse_mal_export(_MAL)
    assert (bebop.title, bebop.episodes, bebop.watched, bebop.assumed_complete) == (
        "Cowboy Bebop",
        26,
        26,
        True,
    )
    assert bebop.score == 9 and bebop.rewatches == 2 and bebop.tags == ["space", "jazz"]
    assert bebop.started is None and str(bebop.finished) == "2020-05-01" and bebop.format == "TV"
    assert movie.score is None and movie.status == AnimeStatus.WATCHLIST and movie.format == "Movie"
    # an unknown length stays unknown, and the watched count is the file's own
    assert ongoing.episodes is None and ongoing.watched == 5 and not ongoing.assumed_complete


def test_mal_import_refuses_other_files_and_entity_tricks():
    from src.features.imports.mal import MalImportError, parse_mal_export

    for bad in (b"not xml", b"<other/>", b'<!DOCTYPE x [<!ENTITY a "b">]><myanimelist/>'):
        with pytest.raises(MalImportError):
            parse_mal_export(bad)


def _upload():
    import io

    from fastapi import UploadFile

    return UploadFile(file=io.BytesIO(_MAL), filename="animelist.xml")


@pytest.mark.asyncio
async def test_mal_import_keeps_existing_titles_unless_chosen_and_is_safe_twice():
    from src.api.routes.media_io import export_media_csv, import_mal, preview_mal

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            # already on the site, with its own data: a score and progress MAL disagrees with
            mine = _anime(user, title="Cowboy Bebop", status=AnimeStatus.IN_PROGRESS)
            mine.rating_overall = 6
            mine.note = "my own note"
            db.add(mine)
            await db.flush()
            db.add(
                AnimeSeason(show_id=mine.id, season_number=1, episode_count=26, episodes_watched=5)
            )
            await db.flush()

            preview = await preview_mal(_upload(), db, user)
            assert preview["total"] == 3 and preview["new_count"] == 2
            [entry] = preview["existing"]
            fields = {d["field"]: (d["site"], d["mal"]) for d in entry["differences"]}
            assert fields["Status"] == ("In Progress", "Watched")
            assert fields["Episodes watched"] == ("5", "26") and fields["Score"] == ("6.0", "9.0")

            # keeping it (the default) changes nothing on that title
            first = await import_mal(_upload(), "[]", False, db, user)
            assert (first.created, first.updated, first.kept, first.assumed_complete) == (
                2,
                0,
                1,
                0,
            )
            await db.refresh(mine)
            assert mine.status == AnimeStatus.IN_PROGRESS and float(mine.rating_overall) == 6.0
            again = await import_mal(_upload(), "[]", False, db, user)
            assert (again.created, again.kept) == (0, 3)

            # choosing MAL's data applies only what MAL states and keeps the rest
            chosen = await import_mal(_upload(), '["1"]', False, db, user)
            assert (chosen.created, chosen.updated, chosen.assumed_complete) == (0, 1, 1)
            await db.refresh(mine, ["seasons"])
            assert mine.status == AnimeStatus.WATCHED and float(mine.rating_overall) == 9.0
            assert mine.note == "classic" and mine.rewatches == 2 and mine.external_id == "1"
            season = (
                (await db.execute(select(AnimeSeason).where(AnimeSeason.show_id == mine.id)))
                .scalars()
                .one()
            )
            assert season.episodes_watched == 26

            csv_text = (await export_media_csv(db, user)).body.decode()
            assert "anime,Cowboy Bebop,WATCHED,9.0" in csv_text
        finally:
            if user is not None:
                await _cleanup(db, user)


class _FakeAniList:
    def get_by_mal_ids(self, ids):
        meta = {
            "id": 1,
            "id_mal": 1,
            "poster_url": "http://p/1.jpg",
            "genres": ["Sci-Fi"],
            "studios": ["Sunrise"],
            "overview": "text",
            "episode_count": 26,
            "release_date": "1998-04-03",
            "score": 8.6,
            "format": "TV",
            "episode_runtime_minutes": 24,
            "countries": ["JP"],
            "backdrop_url": None,
        }
        return {1: meta}, 1


@pytest.mark.asyncio
async def test_details_fill_only_blank_fields_and_report_what_was_not_found():
    from src.features.imports.mal_apply import fill_details

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            have = Anime(
                user_id=user.scratch_id,
                title="A",
                sort_title="a",
                external_id="1",
                status=AnimeStatus.WATCHED,
                description="mine",
                studios=[],
                countries=[],
                languages=[],
                genres=[],
                tags=[],
                features=[],
                locked_fields=[],
                seasons=[AnimeSeason(season_number=1, episode_count=None)],
            )
            other = Anime(
                user_id=user.scratch_id,
                title="B",
                sort_title="b",
                external_id="2",
                status=AnimeStatus.WATCHED,
                studios=[],
                countries=[],
                languages=[],
                genres=[],
                tags=[],
                features=[],
                locked_fields=[],
                seasons=[AnimeSeason(season_number=1)],
            )
            result = await fill_details([have, other], _FakeAniList())  # type: ignore[arg-type]
            assert result == {"filled": 1, "not_found": 0, "lookup_failed": 1}
            assert (
                have.poster_url == "http://p/1.jpg"
                and have.genres == ["Sci-Fi"]
                and have.anilist_id == "1"
            )
            assert have.description == "mine"  # what was already there is never replaced
            assert have.seasons[0].episode_count == 26 and str(have.first_air_date) == "1998-04-03"
            assert other.poster_url is None
        finally:
            if user is not None:
                await _cleanup(db, user)


# ----------------------------------------------------- restoring an own export
@pytest.mark.asyncio
async def test_a_library_export_restores_movies_shows_and_anime_with_progress_and_is_safe_twice():
    import json

    from src.api.routes.export_import import export_library
    from src.database.models.tv_show import TVShow, TVShowStatus
    from src.features.imports.restore import restore_media

    async with SessionLocal() as db:
        source = target = None
        try:
            source = await _user(db)
            target = await _user(db)
            show = _anime(source, title="Restore Me")
            db.add(show)
            db.add(
                Movie(
                    user_id=source.scratch_id,
                    title="Film",
                    sort_title="film",
                    status=MovieStatus.WATCHED,
                    studios=[],
                    countries=[],
                    languages=[],
                    genres=["Drama"],
                    tags=[],
                    features=[],
                    director=[],
                    writer=[],
                    locked_fields=[],
                    rewatches=1,
                )
            )
            db.add(
                TVShow(
                    user_id=source.scratch_id,
                    title="Series",
                    sort_title="series",
                    status=TVShowStatus.WATCHED,
                    creators=[],
                    studios=[],
                    countries=[],
                    languages=[],
                    genres=[],
                    tags=[],
                    features=[],
                    locked_fields=[],
                )
            )
            await db.flush()
            season = AnimeSeason(
                show_id=show.id, season_number=1, episode_count=3, episodes_watched=2
            )
            db.add(season)
            await db.flush()
            db.add_all(
                [
                    AnimeEpisode(
                        season_id=season.id, episode_number=n, title=f"Ep {n}", watched=(n <= 2)
                    )
                    for n in (1, 2, 3)
                ]
            )
            await db.flush()

            exported = json.loads((await export_library(db, source)).model_dump_json())
            first = await restore_media(db, target.scratch_id, exported)
            assert first["created"] == {"movies": 1, "tv_shows": 1, "anime": 1}, first
            again = await restore_media(db, target.scratch_id, exported)
            assert again["created"] == {"movies": 0, "tv_shows": 0, "anime": 0}
            assert again["skipped"] == {"movies": 1, "tv_shows": 1, "anime": 1}

            restored = (
                (await db.execute(select(Anime).where(Anime.user_id == target.scratch_id)))
                .scalars()
                .one()
            )
            assert restored.id != show.id and restored.status == AnimeStatus.IN_PROGRESS
            seasons = (
                (await db.execute(select(AnimeSeason).where(AnimeSeason.show_id == restored.id)))
                .scalars()
                .all()
            )
            assert [(s.episode_count, s.episodes_watched) for s in seasons] == [(3, 2)]
            eps = (
                (
                    await db.execute(
                        select(AnimeEpisode).where(AnimeEpisode.season_id == seasons[0].id)
                    )
                )
                .scalars()
                .all()
            )
            assert sorted((e.episode_number, e.watched) for e in eps) == [
                (1, True),
                (2, True),
                (3, False),
            ]
            movie = (
                (await db.execute(select(Movie).where(Movie.user_id == target.scratch_id)))
                .scalars()
                .one()
            )
            assert movie.rewatches == 1 and movie.genres == ["Drama"]
        finally:
            for u in (source, target):
                if u is not None:
                    await _cleanup(db, u)


@pytest.mark.asyncio
async def test_one_bad_entry_is_reported_and_the_rest_still_restore():
    from src.features.imports.restore import restore_media

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            payload = {
                "movies": [
                    {"title": "Good", "sort_title": "good", "status": "WATCHED"},
                    {"title": "Bad", "sort_title": "bad", "status": "NOT_A_STATUS"},
                    {"sort_title": "no title"},
                ]
            }
            result = await restore_media(db, user.scratch_id, payload)
            assert result["created"]["movies"] == 1 and result["skipped"]["movies"] == 1
            assert any("Bad" in e for e in result["errors"]) and any(
                "no title" in e for e in result["errors"]
            )
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------------------------ pinning and ordering lists
@pytest.mark.asyncio
async def test_lists_can_be_pinned_and_put_in_the_users_own_order():
    from src.api.routes.media_lists import (
        create_media_list,
        list_media_lists,
        order_media_lists,
        update_media_list,
    )
    from src.api.schemas.media_extras import MediaListCreate, MediaListsOrder, MediaListUpdate

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.commit()
            a = await create_media_list(MediaListCreate(name="Alpha"), db, user)
            b = await create_media_list(MediaListCreate(name="Beta"), db, user)
            c = await create_media_list(MediaListCreate(name="Gamma"), db, user)
            names = [x["name"] for x in await list_media_lists(db, user)]
            assert names == ["Favorites", "Alpha", "Beta", "Gamma"]  # new lists go last

            await order_media_lists(MediaListsOrder(list_ids=[c["id"], a["id"], b["id"]]), db, user)
            assert [x["name"] for x in await list_media_lists(db, user)] == [
                "Gamma",
                "Alpha",
                "Beta",
                "Favorites",
            ]

            pinned = await update_media_list(b["id"], MediaListUpdate(pinned=True), db, user)
            assert pinned["pinned"] is True
            ordered = await list_media_lists(db, user)
            assert [x["name"] for x in ordered][0] == "Beta" and ordered[0]["pinned"]
            # an unpin, and a null pin, both leave the list valid
            assert (await update_media_list(b["id"], MediaListUpdate(pinned=False), db, user))[
                "pinned"
            ] is False
            assert (await update_media_list(b["id"], MediaListUpdate(pinned=None), db, user))[
                "pinned"
            ] is False
        finally:
            if user is not None:
                await _cleanup(db, user)


# ---------------------------------------------------------- title language
def test_the_preferred_title_spelling_is_used_with_sensible_fallbacks():
    from types import SimpleNamespace

    from src.core.titles import apply_alt_titles, display_title

    show = SimpleNamespace(
        title="Canon",
        title_english="Attack on Titan",
        title_romaji="Shingeki no Kyojin",
        title_native="進撃の巨人",
    )
    assert display_title(show, "english") == "Attack on Titan"
    assert display_title(show, "romaji") == "Shingeki no Kyojin"
    assert display_title(show, "native") == "進撃の巨人"
    only_romaji = SimpleNamespace(
        title="Canon", title_english=None, title_romaji="Romaji", title_native=None
    )
    assert display_title(only_romaji, "english") == "Romaji"  # next best, never blank
    assert (
        display_title(SimpleNamespace(title="Canon"), "native") == "Canon"
    )  # a movie has no alternates

    empty = SimpleNamespace(title="X", title_english="kept", title_romaji=None, title_native=None)
    assert apply_alt_titles(
        empty, {"title_english": "other", "title_romaji": "R", "title_native": "N"}
    )
    assert (empty.title_english, empty.title_romaji, empty.title_native) == (
        "kept",
        "R",
        "N",
    )  # only blanks are filled
    assert not apply_alt_titles(empty, {"title_romaji": "again"})


@pytest.mark.asyncio
async def test_the_title_language_preference_changes_titles_in_stats_and_lists():
    from src.api.routes.media_lists import create_media_list, get_media_list
    from src.api.schemas.media_extras import MediaListCreate, SmartRule
    from src.core.preferences import save_preferences

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.commit()
            show = _anime(user, title="Canon Title", status=AnimeStatus.IN_PROGRESS)
            show.title_english, show.title_romaji, show.title_native = (
                "English Name",
                "Romaji Name",
                "日本語",
            )
            db.add(show)
            await db.flush()
            db.add(
                AnimeSeason(show_id=show.id, season_number=1, episode_count=12, episodes_watched=3)
            )
            await db.commit()
            smart = await create_media_list(
                MediaListCreate(name="All", smart_rule=SmartRule(media_types=["anime"])), db, user
            )

            for language, expected in (
                ("english", "English Name"),
                ("romaji", "Romaji Name"),
                ("native", "日本語"),
            ):
                await save_preferences(db, user.scratch_id, {"title_language": language})
                await db.commit()
                stats = await get_media_stats(db, user)
                assert [r["title"] for r in stats["overview"]["in_progress"]] == [expected]
                detail = await get_media_list(smart["id"], db, user)
                assert [i["title"] for i in detail["items"]] == [expected]
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------------------- Letterboxd and IMDb imports
def _letterboxd_zip() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(
            "watched.csv",
            "Date,Name,Year,Letterboxd URI\n2020-01-01,Alien,1979,x\n2020-01-02,Heat,1995,x\n",
        )
        z.writestr(
            "ratings.csv", "Date,Name,Year,Letterboxd URI,Rating\n2020-01-01,Alien,1979,x,4.5\n"
        )
        z.writestr(
            "diary.csv",
            "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n"
            "2021-02-02,Heat,1995,x,,Yes,,2021-02-01\n2022-03-03,Heat,1995,x,3,Yes,,2022-03-01\n",
        )
        z.writestr("watchlist.csv", "Date,Name,Year,Letterboxd URI\n2020-05-05,Ran,1985,x\n")
        z.writestr("likes/films.csv", "Date,Name,Year,Letterboxd URI\n2020-06-06,Alien,1979,x\n")
        z.writestr("lists/mine.csv", "Date,Name,Year,Letterboxd URI\n2020-06-06,Ignored,2000,x\n")
    return buffer.getvalue()


def test_letterboxd_export_is_read_exactly():
    from src.features.imports.lists import parse_letterboxd

    by_name = {t.title: t for t in parse_letterboxd(_letterboxd_zip(), "export.zip")}
    assert set(by_name) == {"Alien", "Heat", "Ran"}  # custom lists are not treated as films watched
    alien, heat, ran = by_name["Alien"], by_name["Heat"], by_name["Ran"]
    assert (alien.status, float(alien.rating), alien.favorite) == (
        "WATCHED",
        9.0,
        True,
    )  # 4.5 stars, 10 scale
    assert (
        heat.rewatches == 2 and float(heat.rating) == 6.0 and str(heat.watched_on) == "2022-03-01"
    )
    assert (ran.status, ran.rating, ran.year) == ("WATCHLIST", None, 1985)


_IMDB = (
    b"Const,Your Rating,Date Rated,Title,Original Title,URL,Title Type,IMDb Rating,Runtime (mins),Year,Genres,Num Votes,Release Date,Directors\n"
    b'tt0078748,9,2020-01-01,Alien,Alien,u,movie,8.5,117,1979,"Horror, Sci-Fi",1,1979-05-25,x\n'
    b'tt0903747,10,2020-02-02,Breaking Bad,Breaking Bad,u,tvSeries,9.5,49,2008,"Crime, Drama",1,2008-01-20,x\n'
    b"tt1234567,7,2020-03-03,An Episode,An Episode,u,tvEpisode,7,45,2010,Drama,1,2010-01-01,x\n"
    b"tt7654321,,2020-04-04,Later,Later,u,movie,7,90,2021,Drama,1,2021-01-01,x\n"
)


def test_imdb_export_maps_types_and_reports_what_it_skipped():
    from src.features.imports.lists import parse_imdb

    items, skipped = parse_imdb(_IMDB)
    assert skipped == 1  # the single episode is not a title
    by_name = {i.title: i for i in items}
    assert (by_name["Alien"].kind, float(by_name["Alien"].rating), by_name["Alien"].runtime) == (
        "movie",
        9.0,
        117,
    )
    assert by_name["Alien"].genres == ["Horror", "Sci-Fi"] and by_name["Alien"].year == 1979
    assert by_name["Breaking Bad"].kind == "tv" and by_name["Later"].status == "WATCHLIST"


class _FakeTMDB:
    def search(self, title, limit=8, year=None):
        return [
            {
                "overview": "text",
                "release_date": "1979-05-25",
                "runtime_minutes": 117,
                "studios": ["Fox"],
                "genres": ["Sci-Fi"],
                "poster_url": "http://p/alien.jpg",
                "vote_average": 8.1,
            }
        ]

    def search_tv(self, title, limit=8, year=None):
        return [
            {
                "overview": "tv text",
                "first_air_date": "2008-01-20",
                "creators": ["Vince"],
                "genres": ["Crime"],
                "poster_url": "http://p/bb.jpg",
                "vote_average": 9.0,
                "seasons": [
                    {
                        "season_number": 1,
                        "name": "S1",
                        "episode_count": 7,
                        "air_date": "2008-01-20",
                        "poster_url": None,
                    },
                    {
                        "season_number": 2,
                        "name": "S2",
                        "episode_count": 13,
                        "air_date": "2009-03-08",
                        "poster_url": None,
                    },
                ],
            }
        ]


@pytest.mark.asyncio
async def test_list_import_keeps_existing_titles_fills_blanks_and_builds_seasons():
    import io

    from fastapi import UploadFile

    from src.api.routes.media_io import import_list, preview_list
    from src.database.models.tv_show import TVShow
    from src.features.imports.list_apply import fill_details as fill
    from src.features.imports.list_apply import match_titles
    from src.features.imports.lists import parse_imdb

    def upload():
        return UploadFile(file=io.BytesIO(_IMDB), filename="ratings.csv")

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            mine = Movie(
                user_id=user.scratch_id,
                title="Alien",
                sort_title="alien",
                status=MovieStatus.WATCHLIST,
                release_date=datetime(1979, 5, 25).date(),
                description="mine",
                studios=[],
                countries=[],
                languages=[],
                genres=[],
                tags=[],
                features=[],
                locked_fields=[],
            )
            db.add(mine)
            await db.flush()

            preview = await preview_list(upload(), "imdb", db, user)
            assert (preview["total"], preview["new_count"], preview["skipped_other"]) == (3, 2, 1)
            [entry] = preview["existing"]
            fields = {d["field"]: (d["site"], d["mal"]) for d in entry["differences"]}
            assert fields["Status"] == ("Watchlist", "Watched") and fields["Score"] == (None, "9.0")

            kept = await import_list(upload(), "imdb", "[]", False, db, user)
            assert (kept.created, kept.updated, kept.kept) == (2, 0, 1)
            await db.refresh(mine)
            assert mine.status == MovieStatus.WATCHLIST and mine.rating_overall is None
            again = await import_list(upload(), "imdb", "[]", False, db, user)
            assert (again.created, again.kept) == (0, 3)

            chosen = await import_list(upload(), "imdb", '["movie:alien:1979"]', False, db, user)
            assert chosen.updated == 1
            await db.refresh(mine)
            assert mine.status == MovieStatus.WATCHED and float(mine.rating_overall) == 9.0

            # metadata: blank fields only, and a series gets its seasons, all watched
            items, _ = parse_imdb(_IMDB)
            matches = await match_titles(db, user.scratch_id, items)
            rows = [(m.imported, m.existing, True) for m in matches if m.existing is not None]
            result = await fill(_FakeTMDB(), rows)
            assert result["not_found"] == 0 and result["seasons_assumed_watched"] == 1
            assert (
                mine.description == "mine"
                and mine.poster_url == "http://p/alien.jpg"
                and mine.runtime_minutes == 117
            )
            show = next(r for _, r, _ in rows if isinstance(r, TVShow))
            assert [
                (s.season_number, s.episode_count, s.episodes_watched) for s in show.seasons
            ] == [(1, 7, 7), (2, 13, 13)]
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------------------------------ calendar entries
@pytest.mark.asyncio
async def test_manual_calendar_entries_are_private_validated_and_in_the_feed():
    from datetime import date

    from fastapi import HTTPException

    from src.api.routes.calendar_events import (
        EventCreate,
        EventUpdate,
        create_event,
        delete_event,
        list_events,
        update_event,
    )
    from src.api.routes.calendar_feed import _build_ics
    from src.database.models.calendar_event import CalendarEvent

    async with SessionLocal() as db:
        owner = other = None
        try:
            owner = await _user(db)
            other = await _user(db)
            await db.commit()
            made = await create_event(
                EventCreate(
                    title="Dune watch party",
                    event_date=date(2026, 12, 18),
                    event_time="19:30",
                    note="bring snacks, tea",
                ),
                db,
                owner,
            )
            assert made["event_time"] == "19:30" and made["media_id"] is None
            await create_event(
                EventCreate(title="All day", event_date=date(2026, 12, 19)), db, owner
            )

            days = await list_events(date(2026, 12, 19), None, db, owner)
            assert [e["title"] for e in days] == ["All day"]
            assert await list_events(None, None, db, other) == []  # nobody else sees them

            # a bad time is refused at the edge, a half-linked title is refused by the route
            with pytest.raises((TypeError, ValueError)):
                EventCreate(title="x", event_date=date(2026, 1, 1), event_time="25:99")
            with pytest.raises(HTTPException) as bad:
                await create_event(
                    EventCreate(title="x", event_date=date(2026, 1, 1), media_type="anime"),
                    db,
                    owner,
                )
            assert bad.value.status_code == 400

            moved = await update_event(
                made["id"], EventUpdate(event_date=date(2026, 12, 20), event_time=None), db, owner
            )
            assert moved["event_date"] == "2026-12-20" and moved["event_time"] is None
            with pytest.raises(HTTPException) as foreign:
                await update_event(made["id"], EventUpdate(title="mine now"), db, other)
            assert foreign.value.status_code == 404

            rows = list(
                (
                    await db.execute(
                        select(CalendarEvent).where(CalendarEvent.user_id == owner.scratch_id)
                    )
                )
                .scalars()
                .all()
            )
            ics = _build_ics([], rows)
            assert "SUMMARY:Dune watch party" in ics and "DESCRIPTION:bring snacks\\, tea" in ics
            assert "DTSTART;VALUE=DATE:20261219" in ics  # the all-day one

            await delete_event(made["id"], db, owner)
            assert [e["title"] for e in await list_events(None, None, db, owner)] == ["All day"]
        finally:
            for u in (owner, other):
                if u is not None:
                    await _cleanup(db, u)


def test_a_bare_carriage_return_in_a_title_cannot_start_a_new_calendar_line():
    from src.api.routes.calendar_feed import _ics_escape

    assert "\r" not in _ics_escape("Movie\rEND:VEVENT")


# -------------------------------------------------- choosing what notifies
def test_notification_scope_preferences_only_accept_known_choices():
    assert validate_preference("notify_statuses", ["hold", "watching", "watching"]) == [
        "watching",
        "hold",
    ]
    assert validate_preference("notify_statuses", []) == []  # nothing at all is allowed
    assert validate_preference("notify_media_types", ["movie", "anime"]) == ["anime", "movie"]
    for bad in (["dropped"], "watching", None, ["tv", 3]):
        with pytest.raises(ValueError):
            validate_preference(
                "notify_statuses" if bad != ["tv", 3] else "notify_media_types", bad
            )
    assert DEFAULTS["notify_statuses"] == [
        "watching",
        "plan",
        "hold",
    ]  # what it did before the switches existed


@pytest.mark.asyncio
async def test_only_watching_titles_notify_when_that_is_all_that_is_switched_on():
    from src.core.preferences import save_preferences

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            aired_at = int(datetime.now(tz=timezone.utc).timestamp()) - 3600
            for title, status in (
                ("Watching One", AnimeStatus.IN_PROGRESS),
                ("Planned One", AnimeStatus.WATCHLIST),
                ("Held One", AnimeStatus.BACKLOG),
            ):
                show = _anime(user, title=title, status=status)
                db.add(show)
                await db.flush()
                season = AnimeSeason(show_id=show.id, season_number=1, episode_count=12)
                db.add(season)
                await db.flush()
                db.add(AnimeEpisode(season_id=season.id, episode_number=5, air_at=aired_at))
            await db.commit()

            async def titles():
                await generate_for_user(db, user.scratch_id)
                rows = (
                    (
                        await db.execute(
                            select(Notification).where(Notification.user_id == user.scratch_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                return sorted(r.title for r in rows)

            await save_preferences(db, user.scratch_id, {"notify_statuses": ["watching"]})
            assert await titles() == ["Watching One"]

            # switching a type off stops that kind, even for a watching title
            await db.execute(delete(Notification).where(Notification.user_id == user.scratch_id))
            await save_preferences(db, user.scratch_id, {"notify_media_types": ["tv", "movie"]})
            assert await titles() == []

            # nothing selected means nothing is generated
            await save_preferences(
                db,
                user.scratch_id,
                {"notify_media_types": ["anime", "tv", "movie"], "notify_statuses": []},
            )
            assert await titles() == []
        finally:
            if user is not None:
                await _cleanup(db, user)


@pytest.mark.asyncio
async def test_a_movie_only_notifies_when_movies_and_its_status_are_switched_on():
    from datetime import date, timedelta

    from src.core.preferences import save_preferences

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            db.add(
                Movie(
                    user_id=user.scratch_id,
                    title="Out Now",
                    sort_title="out now",
                    status=MovieStatus.WATCHLIST,
                    release_date=date.today() - timedelta(days=1),
                    studios=[],
                    countries=[],
                    languages=[],
                    genres=[],
                    tags=[],
                    features=[],
                    locked_fields=[],
                )
            )
            await db.commit()

            async def count():
                await db.execute(
                    delete(Notification).where(Notification.user_id == user.scratch_id)
                )
                await generate_for_user(db, user.scratch_id)
                return len(
                    (
                        await db.execute(
                            select(Notification).where(Notification.user_id == user.scratch_id)
                        )
                    )
                    .scalars()
                    .all()
                )

            assert await count() == 1
            await save_preferences(
                db, user.scratch_id, {"notify_statuses": ["watching", "hold"]}
            )  # plan is off
            assert await count() == 0
            await save_preferences(
                db,
                user.scratch_id,
                {"notify_statuses": ["plan"], "notify_media_types": ["anime", "tv"]},
            )
            assert await count() == 0  # movies are off
        finally:
            if user is not None:
                await _cleanup(db, user)


# -------------------------------------------- episode totals and the refresh job
def _eps(n, titled=True):
    return [{"episode_number": i, "title": f"Ep {i}" if titled else None} for i in range(1, n + 1)]


class _Zip:
    def __init__(self, count, kitsu="111", titled=True):
        self.count, self.kitsu, self.titled = count, kitsu, titled

    def lookup(self, _id):
        return {
            "episodes": _eps(self.count, self.titled),
            "episode_count": self.count,
            "kitsu_id": self.kitsu,
            "mal_id": None,
        }


class _Kitsu:
    called_with: list = []

    def episodes(self, kitsu_id):
        _Kitsu.called_with.append(kitsu_id)
        return _eps(25)  # another entry's list: season 1 attached to season 2


class _AniListTotals:
    def __init__(self, total):
        self.total = total

    def final_totals(self, ids):
        return {ids[0]: {"total": self.total, "status": "FINISHED" if self.total else "RELEASING"}}

    def episodes(self, _id):
        return []


class _Jikan:
    def episodes(self, _id):
        return []


@pytest.mark.asyncio
async def test_another_entrys_episodes_can_no_longer_inflate_a_finished_season(monkeypatch):
    from src.features.metadata.anime import episode_sync

    _Kitsu.called_with = []
    monkeypatch.setattr(episode_sync, "AniZipClient", lambda: _Zip(12, kitsu="222"))
    monkeypatch.setattr(episode_sync, "AniListClient", lambda: _AniListTotals(12))
    monkeypatch.setattr(episode_sync, "JikanClient", lambda: _Jikan())
    monkeypatch.setattr(episode_sync, "KitsuClient", lambda: _Kitsu())

    # complete from ani.zip alone: the slower providers are not even asked
    fetch = await episode_sync.fetch_episodes_with_fallback("25777", "20958", "8671")
    assert [e["episode_number"] for e in fetch.episodes] == list(range(1, 13))
    assert fetch.final_total == 12 and fetch.kitsu_id == "222" and _Kitsu.called_with == []

    # ani.zip is short (its titles are missing): the others are asked, but the stored
    # Kitsu id (a title-search guess) is not used, only the one ani.zip vouches for
    monkeypatch.setattr(episode_sync, "AniZipClient", lambda: _Zip(12, kitsu="222", titled=False))
    fetch = await episode_sync.fetch_episodes_with_fallback("25777", "20958", "8671")
    assert _Kitsu.called_with == ["222"]
    # even then, nothing numbered past the entry's own total survives
    assert max(e["episode_number"] for e in fetch.episodes) == 12

    # without any exact id, a stored Kitsu id is never trusted for an entry with an AniList id
    _Kitsu.called_with = []
    monkeypatch.setattr(episode_sync, "AniZipClient", lambda: _Zip(12, kitsu=None, titled=False))
    await episode_sync.fetch_episodes_with_fallback("25777", "20958", "8671")
    assert _Kitsu.called_with == []


def test_a_season_inflated_by_a_wrong_match_is_repaired_without_touching_watched_rows():
    from types import SimpleNamespace

    from src.features.metadata.refresh import _trim_beyond_total

    def ep(n, watched=False):
        return SimpleNamespace(episode_number=n, watched=watched, rating=None)

    rows = [ep(n) for n in range(1, 26)]
    rows[19].watched = True  # the user ticked episode 20 while the list was wrong
    season = SimpleNamespace(episodes=rows, episode_count=25, episodes_watched=12)
    removed = _trim_beyond_total(season, 12)
    assert removed == 12  # 13..25 minus the watched 20 that is kept
    assert season.episode_count == 20  # a kept row is never hidden by the total
    assert season.episodes_watched == 12

    clean = SimpleNamespace(
        episodes=[ep(n) for n in range(1, 26)], episode_count=25, episodes_watched=30
    )
    _trim_beyond_total(clean, 12)
    assert len(clean.episodes) == 12 and clean.episode_count == 12 and clean.episodes_watched == 12


def test_the_refresh_only_touches_titles_that_need_it():
    from types import SimpleNamespace

    from src.features.metadata.refresh_job import _anime_needs

    def season(count, titled=True):
        rows = [
            SimpleNamespace(episode_number=n, title="t" if titled else None)
            for n in range(1, count + 1)
        ]
        return SimpleNamespace(episodes=rows, episode_count=count)

    done = SimpleNamespace(is_airing=False)
    finished = {"total": 12, "status": "FINISHED"}
    assert not _anime_needs(done, season(12), finished)  # complete: skipped
    assert _anime_needs(done, season(25), finished)  # a total that disagrees with AniList
    assert _anime_needs(done, season(12, titled=False), finished)  # untitled rows
    assert _anime_needs(done, SimpleNamespace(episodes=[], episode_count=None), finished)
    assert _anime_needs(done, season(12), {"total": None, "status": "RELEASING"})  # still airing
    assert _anime_needs(SimpleNamespace(is_airing=None), season(12), None)  # never checked


def test_only_one_refresh_runs_at_a_time():
    from src.features.metadata import refresh_job

    refresh_job._progress = refresh_job.Progress()
    assert refresh_job._begin("needed") is True
    assert refresh_job._begin("all") is False  # already running: no second run
    assert refresh_job.snapshot()["running"] is True and refresh_job.snapshot()["mode"] == "needed"
    refresh_job._progress = refresh_job.Progress()


# ------------------------------------------------------------ cleanup jobs
def test_a_job_only_runs_when_switched_on_and_due():
    from src.features.jobs import is_due

    now = 1_000_000
    day = 24 * 60  # intervals are in minutes
    assert not is_due(False, None, day, now)  # off means off, even if it has never run
    assert is_due(True, None, day, now)  # switched on and never run: due
    assert not is_due(True, now - 3600, day, now)  # ran an hour ago
    assert is_due(True, now - 24 * 3600, day, now)  # exactly one interval later
    assert not is_due(True, now - 5 * 3600, 360, now)
    assert is_due(True, now - 6 * 3600, 360, now)
    assert not is_due(True, now - 20 * 60, 30, now)  # the airing check, every 30 minutes
    assert is_due(True, now - 30 * 60, 30, now)


@pytest.mark.asyncio
async def test_the_airing_check_starts_on_and_the_refresh_off_and_intervals_stay_in_range():
    from fastapi import HTTPException

    from src.api.routes.jobs import JobUpdate, list_jobs, update_job
    from src.database.models.job_setting import JobSetting

    async with SessionLocal() as db:
        # the live schedules are put back afterwards
        saved = [
            (r.job_id, r.enabled, r.interval_minutes, r.last_run_at, r.last_result)
            for r in (await db.execute(select(JobSetting))).scalars()
        ]
        try:
            await db.execute(delete(JobSetting))
            await db.commit()

            airing, refresh = await list_jobs(db)
            assert (
                airing["id"] == "airing_check" and airing["enabled"] is True
            )  # new episodes appear by themselves
            assert airing["interval_minutes"] == 30 and airing["last_run_at"] is None
            assert (
                refresh["id"] == "media_refresh" and refresh["enabled"] is False
            )  # the heavy one is asked for
            assert refresh["interval_minutes"] == 1440

            faster = await update_job("airing_check", JobUpdate(interval_minutes=10), db)
            assert faster["interval_minutes"] == 10 and faster["enabled"] is True
            turned_on = await update_job(
                "media_refresh", JobUpdate(enabled=True, interval_minutes=720), db
            )
            assert turned_on["enabled"] is True and turned_on["interval_minutes"] == 720
            with pytest.raises(HTTPException) as too_often:
                await update_job("airing_check", JobUpdate(interval_minutes=1), db)
            assert too_often.value.status_code == 400
            with pytest.raises(HTTPException) as too_rare:
                await update_job("airing_check", JobUpdate(interval_minutes=25 * 60), db)
            assert too_rare.value.status_code == 400
            with pytest.raises(HTTPException) as missing:
                await update_job("nope", JobUpdate(enabled=True), db)
            assert missing.value.status_code == 404
        finally:
            await db.execute(delete(JobSetting))
            for job_id, enabled, minutes, last_run_at, last_result in saved:
                db.add(
                    JobSetting(
                        job_id=job_id,
                        enabled=enabled,
                        interval_minutes=minutes,
                        last_run_at=last_run_at,
                        last_result=last_result,
                    )
                )
            await db.commit()


@pytest.mark.asyncio
async def test_a_finished_run_is_recorded_with_the_job():
    from src.database.models.job_setting import JobSetting
    from src.features.jobs import record_run

    async with SessionLocal() as db:
        previous = await db.get(JobSetting, "media_refresh")
        kept = (
            None
            if previous is None
            else (
                previous.enabled,
                previous.interval_minutes,
                previous.last_run_at,
                previous.last_result,
            )
        )
        try:
            await db.execute(delete(JobSetting).where(JobSetting.job_id == "media_refresh"))
            await db.commit()
            await record_run(
                "media_refresh",
                {"checked": 4, "counts_fixed": 1, "unreachable": ["a title"], "error": None},
            )
            row = await db.get(JobSetting, "media_refresh")
            assert row is not None and row.last_run_at is not None
            # simple numbers and text are kept, lists are left out
            assert row.last_result == {"checked": 4, "counts_fixed": 1, "error": None}
        finally:
            await db.execute(delete(JobSetting).where(JobSetting.job_id == "media_refresh"))
            if kept is not None:
                db.add(
                    JobSetting(
                        job_id="media_refresh",
                        enabled=kept[0],
                        interval_minutes=kept[1],
                        last_run_at=kept[2],
                        last_result=kept[3],
                    )
                )
            await db.commit()


# ------------------------------------ anime names in the calendar and notifications
@pytest.mark.asyncio
async def test_calendar_entries_and_notifications_use_the_chosen_anime_name():
    from src.api.routes.media_extras import build_calendar_entries
    from src.api.routes.notifications import _display_titles
    from src.core.preferences import save_preferences

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            show = _anime(user, title="Canon Title", status=AnimeStatus.IN_PROGRESS)
            show.title_english, show.title_romaji, show.title_native = (
                "ERASED",
                "Boku dake ga Inai Machi",
                "僕だけがいない街",
            )
            show.next_episode_air_at = int(datetime.now(tz=timezone.utc).timestamp()) + 3 * 86400
            show.next_episode_number = 4
            db.add(show)
            await db.flush()
            db.add(AnimeSeason(show_id=show.id, season_number=1, episode_count=12))
            note = Notification(
                user_id=user.scratch_id,
                kind="episode_aired",
                media_type="anime",
                media_id=show.id,
                title="stored at the time",
                body="Episode 3 aired",
                event_at=1,
                dedupe_key="t1",
            )
            db.add(note)
            await db.commit()

            for language, expected in (
                ("english", "ERASED"),
                ("romaji", "Boku dake ga Inai Machi"),
                ("native", "僕だけがいない街"),
            ):
                await save_preferences(db, user.scratch_id, {"title_language": language})
                await db.commit()
                entries = await build_calendar_entries(db, user.scratch_id, 30)
                assert {e["title"] for e in entries if e["media_type"] == "anime"} == {expected}
                assert (await _display_titles(db, user.scratch_id, [note]))[note.id] == expected
        finally:
            if user is not None:
                await _cleanup(db, user)


# -------------------------------------------------- airing shows and the episode limit
def test_the_episode_limit_is_what_can_exist_right_now():
    from src.features.metadata.anime.episode_sync import episode_limit

    assert episode_limit(None) is None
    assert episode_limit({"total": 12, "status": "FINISHED"}) == 12
    # airing with a plan: the plan, even though fewer have aired
    assert episode_limit({"total": None, "planned": 26, "next": 13, "status": "RELEASING"}) == 26
    # airing with no plan (One Piece): only what has aired, the episode before the next one
    assert (
        episode_limit({"total": None, "planned": None, "next": 1180, "status": "RELEASING"}) == 1179
    )
    # a premiere that has not aired, or nothing known: no limit rather than a wrong one
    assert episode_limit({"total": None, "planned": None, "next": 1, "status": "RELEASING"}) is None
    assert (
        episode_limit({"total": None, "planned": None, "next": None, "status": "RELEASING"}) is None
    )
    assert (
        episode_limit({"total": None, "planned": None, "next": 5, "status": "NOT_YET_RELEASED"})
        is None
    )


@pytest.mark.asyncio
async def test_an_airing_show_is_not_padded_with_episodes_that_have_not_aired(monkeypatch):
    from src.features.metadata.anime import episode_sync

    class _Long:
        def lookup(self, _id):
            return {"episodes": _eps(1402), "episode_count": 1402, "kitsu_id": None, "mal_id": None}

    class _Airing:
        def final_totals(self, ids):
            return {ids[0]: {"total": None, "planned": None, "next": 1180, "status": "RELEASING"}}

        def episodes(self, _id):
            return []

    monkeypatch.setattr(episode_sync, "AniZipClient", lambda: _Long())
    monkeypatch.setattr(episode_sync, "AniListClient", lambda: _Airing())
    monkeypatch.setattr(episode_sync, "JikanClient", lambda: _Jikan())
    fetch = await episode_sync.fetch_episodes_with_fallback("13", "21")
    assert fetch.limit == 1179 and fetch.final_total is None
    assert max(e["episode_number"] for e in fetch.episodes) == 1179


# ------------------------------------------ calendar projections stop at the season's end
def test_calendar_projects_no_episode_past_the_season_total():
    from types import SimpleNamespace

    from src.api.routes.media_extras import _calendar_entries_for_show

    now = int(datetime.now(tz=timezone.utc).timestamp())

    def show(next_number, count):
        return SimpleNamespace(
            id=uuid.uuid4(),
            title="S",
            poster_url=None,
            next_episode_number=next_number,
            next_episode_air_at=now + 86400,
            airing_interval_days=7,
            seasons=[SimpleNamespace(episode_count=count)],
        )

    window = now + 365 * 86400
    def numbers(s):
        return [
            e["next_episode_number"] for e in _calendar_entries_for_show(s, "anime", window)
        ]
    assert numbers(show(24, 24)) == [24]  # the next episode is the last one
    assert numbers(show(11, 13)) == [11, 12, 13]
    # a count below the next episode is a lagging snapshot, not a ceiling
    assert max(numbers(show(14, 12))) > 14


# --------------------------- imported progress becomes flags once the rows exist
def test_new_episode_rows_are_flagged_for_progress_that_was_imported_by_number():
    from types import SimpleNamespace

    def row(n, watched=False):
        return SimpleNamespace(episode_number=n, watched=watched)

    # a MAL import: 12 watched, no episode rows yet; the refresh then creates 13
    season = SimpleNamespace(episodes=[], episodes_watched=12)
    created = [row(n) for n in range(1, 14)]
    left = materialize_progress(season, created)
    assert left == 0
    assert [r.episode_number for r in created if r.watched] == list(range(1, 13))
    # nothing more to cover the second time
    assert materialize_progress(season, created) == 0
    assert sum(r.watched for r in created) == 12
    # progress beyond the rows that exist stays in the counter
    short = SimpleNamespace(episodes=[], episodes_watched=5)
    assert materialize_progress(short, [row(1), row(2)]) == 3


# ------------------------------------------- the airing check only asks about shows that are due
def test_a_show_is_only_asked_about_when_a_new_episode_could_exist():
    from src.features.metadata.refresh import (
        RECHECK_SCHEDULED_SECONDS,
        RECHECK_UNKNOWN_SECONDS,
        airing_due,
    )

    now = 1_000_000.0
    soon = int(now) + 3 * 86400
    assert airing_due(None, None, None, now)  # never checked
    assert airing_due(True, int(now) - 60, now - 60, now)  # its episode should have aired
    assert not airing_due(True, soon, now - 3600, now)  # next one is days away: leave it
    assert airing_due(True, soon, None, now)  # unless it has not been looked at since a restart
    assert airing_due(
        True, soon, now - RECHECK_SCHEDULED_SECONDS, now
    )  # a daily look for a moved schedule
    assert not airing_due(True, None, now - 3600, now)  # airing, no date announced
    assert airing_due(True, None, now - RECHECK_UNKNOWN_SECONDS, now)


# ------------------------------------- the calendar only lists airing shows you chose
@pytest.mark.asyncio
async def test_the_calendar_lists_airing_shows_only_for_the_chosen_statuses():
    from src.api.routes.media_extras import build_calendar_entries
    from src.core.preferences import save_preferences

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            soon = int(datetime.now(tz=timezone.utc).timestamp()) + 2 * 86400
            for title, status in (
                ("Watching one", AnimeStatus.IN_PROGRESS),
                ("Held one", AnimeStatus.BACKLOG),
                ("Dropped one", AnimeStatus.DROPPED),
            ):
                show = _anime(user, title=title, status=status)
                show.next_episode_air_at, show.next_episode_number = soon, 3
                db.add(show)
            await db.commit()

            async def titles():
                entries = await build_calendar_entries(db, user.scratch_id, 30)
                return {e["title"] for e in entries if e["kind"] == "episode"}

            # the default follows watching, plan to watch and on hold
            assert await titles() == {"Watching one", "Held one"}
            await save_preferences(db, user.scratch_id, {"calendar_airing_statuses": ["watching"]})
            await db.commit()
            assert await titles() == {"Watching one"}
            await save_preferences(db, user.scratch_id, {"calendar_airing_statuses": []})
            await db.commit()
            assert await titles() == set()
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------- deleting a rewatch takes it out of History too
@pytest.mark.asyncio
async def test_deleting_a_rewatch_lowers_the_history_count_for_that_day():
    from types import SimpleNamespace

    from src.api.routes.media_extras import create_rewatch, delete_rewatch
    from src.api.schemas.media_extras import RewatchCreate
    from src.database.models.media_extras import ActivityEventType, ActivityLog

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            show = _anime(user, title="Rewatched", status=AnimeStatus.WATCHED)
            db.add(show)
            await db.flush()
            show_id = show.id
            await db.commit()
            me = SimpleNamespace(id=user.scratch_id)  # type: ignore[attr-defined]

            day = datetime.now(tz=timezone.utc).date()
            made = [
                await create_rewatch(
                    RewatchCreate(media_type="anime", media_id=show_id, finished_on=day), db, me
                )
                for _ in range(3)
            ]

            async def history():
                row = await db.scalar(
                    select(ActivityLog).where(
                        ActivityLog.media_id == show_id,
                        ActivityLog.event_type == ActivityEventType.REWATCHED,
                    )
                )
                return None if row is None else row.count

            assert await history() == 3
            await delete_rewatch(made[0].id, db, me)
            assert await history() == 2
            await delete_rewatch(made[1].id, db, me)
            await delete_rewatch(made[2].id, db, me)
            assert await history() is None  # nothing left to show for that day
        finally:
            if user is not None:
                await _cleanup(db, user)


# ------------------------------------------ game release dates on the calendar
@pytest.mark.asyncio
async def test_every_games_release_date_reaches_the_calendar_and_the_setting_controls_it():
    from datetime import date, timedelta
    from types import SimpleNamespace

    from src.api.routes.media_extras import build_calendar_entries, get_calendar_games
    from src.core.preferences import save_preferences
    from src.database.models.game import Game, GameStatus

    async with SessionLocal() as db:
        user = None
        try:
            user = await _user(db)
            await db.flush()
            today = date.today()
            for title, when, status in (
                ("Old release", today - timedelta(days=400), GameStatus.PLAYED),
                ("Soon release", today + timedelta(days=10), GameStatus.PLAYED),
            ):
                db.add(
                    Game(
                        user_id=user.scratch_id,
                        folder_location=f"scratch-{uuid.uuid4()}",
                        title=title,
                        sort_title=title.lower(),
                        status=status,
                        release_date=when,
                        tags=[],
                        features=[],
                        collections=[],
                    )
                )
            await db.commit()
            me = SimpleNamespace(id=user.scratch_id)  # type: ignore[attr-defined]

            past = await get_calendar_games(36500, db, me)
            assert [e["title"] for e in past if e["kind"] == "game_released"] == ["Old release"]
            ahead = await build_calendar_entries(db, user.scratch_id, 30, game_releases=True)
            # a future date comes with the rest of the calendar, whatever the game's status
            assert [e["title"] for e in ahead if e["media_type"] == "game"] == ["Soon release"]

            await save_preferences(db, user.scratch_id, {"calendar_game_releases": False})
            await db.commit()
            assert not [
                e for e in await get_calendar_games(36500, db, me) if e["kind"] == "game_released"
            ]
            await save_preferences(
                db, user.scratch_id, {"calendar_game_releases": True, "calendar_hide_games": True}
            )
            await db.commit()
            assert await get_calendar_games(36500, db, me) == []
        finally:
            if user is not None:
                await _cleanup(db, user)
