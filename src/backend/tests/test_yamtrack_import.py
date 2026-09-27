from src.database.models.anime import AnimeStatus
from src.database.models.movies import MovieStatus
from src.database.models.tv_show import TVShowStatus
from src.features.imports.yamtrack import build_yamtrack_item, parse_yamtrack


def test_yamtrack_groups_parent_season_and_episode_rows():
    raw = b"""media_id,source,media_type,title,image,season_number,episode_number,score,status,notes,start_date,end_date,progress
246,tmdb,tv,Avatar: The Last Airbender,,1,,8,Completed,,2026-04-01,2026-05-01,61
246,tmdb,season,Avatar: The Last Airbender,,1,,8,Completed,,2026-04-01,,20
246,tmdb,season,Avatar: The Last Airbender,,2,,8,Completed,,2026-05-01,,20
246,tmdb,episode,Avatar: The Last Airbender,,1,1,,Completed,,2026-04-01,2026-04-01,1
246,tmdb,episode,Avatar: The Last Airbender,,1,2,,Completed,,2026-04-02,2026-04-02,2
246,tmdb,episode,Avatar: The Last Airbender,,2,1,,Watching,,2026-05-01,,1
"""
    groups = parse_yamtrack(raw)
    assert len(groups) == 1
    assert groups[0].media_id == "246"
    assert set(groups[0].seasons) == {1, 2}
    assert len(groups[0].seasons[1]["episodes"]) == 2

    show = build_yamtrack_item(groups[0])
    assert show.external_id == "246"
    assert show.source == "tmdb"
    assert show.status is TVShowStatus.WATCHED
    assert len(show.seasons) == 2
    assert show.seasons[0].episodes_watched == 20
    assert [e.watched for e in show.seasons[0].episodes] == [True, True]


def test_yamtrack_keeps_same_id_separate_when_provider_differs():
    raw = b"""media_id,source,media_type,title,image,season_number,episode_number,score,status,notes,start_date,end_date,progress
42,tmdb,tv,Same Title,,,,,Completed,,,,
42,imdb,tv,Same Title,,,,,Completed,,,,
"""
    groups = parse_yamtrack(raw)
    assert {(g.source, g.media_id) for g in groups} == {("tmdb", "42"), ("imdb", "42")}


def test_yamtrack_movie_maps_tracking_fields():
    raw = b"""media_id,source,media_type,title,image,season_number,episode_number,score,status,notes,start_date,end_date,progress
425909,tmdb,movie,Ghostbusters: Afterlife,https://example/poster.jpg,,,8.5,Completed,fun,2026-01-01,2026-01-02,1
"""
    movie = build_yamtrack_item(parse_yamtrack(raw)[0])
    assert movie.status is MovieStatus.WATCHED
    assert movie.rating_overall == 8.5
    assert movie.poster_url == "https://example/poster.jpg"
    assert movie.note == "fun"


def test_yamtrack_anime_is_supported():
    raw = b"""media_id,source,media_type,title,image,season_number,episode_number,score,status,notes,start_date,end_date,progress
50265,mal,anime,SPYxFAMILY,https://example/poster.jpg,,,9,Completed,,,2026-01-01,12
50265,mal,season,SPYxFAMILY,,1,,,Completed,,,2026-01-01,,12
"""
    anime = build_yamtrack_item(parse_yamtrack(raw)[0])
    assert anime.external_id == "50265"
    assert anime.status is AnimeStatus.WATCHED
    assert anime.seasons[0].episodes_watched == 12
