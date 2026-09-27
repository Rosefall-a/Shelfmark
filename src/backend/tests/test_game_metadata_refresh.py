"""Tests for game metadata-provider refresh safety and provider result handling."""

from types import SimpleNamespace

from src.api.routes.games import _GAME_METADATA_FIELDS, _metadata_value_is_present, _normalize_metadata_title
from src.features.metadata.games import search as game_search
from src.features.metadata.locked_fields import apply_updates_with_locking


def test_game_metadata_title_normalization_matches_storefront_marks():
    assert _normalize_metadata_title("Portal 2™") == _normalize_metadata_title("portal 2")


def test_empty_provider_values_are_not_applied():
    assert _metadata_value_is_present(None) is False
    assert _metadata_value_is_present("") is False
    assert _metadata_value_is_present([]) is False
    assert _metadata_value_is_present("value") is True


def test_manual_game_metadata_changes_are_locked():
    game = SimpleNamespace(title="Old", description="Old description", locked_fields=[])
    apply_updates_with_locking(game, {"description": "Manual description"}, _GAME_METADATA_FIELDS)
    assert game.description == "Manual description"
    assert game.locked_fields == ["description"]


def test_provider_refresh_cannot_change_a_locked_field():
    game = SimpleNamespace(title="Old", description="Manual", locked_fields=["description"])
    updates = {"description": "Provider", "developer": "Provider Dev"}
    safe = {k: v for k, v in updates.items() if k not in game.locked_fields}
    apply_updates_with_locking(game, safe, _GAME_METADATA_FIELDS)
    assert game.description == "Manual"
    assert game.developer == "Provider Dev"


def _fake_spec(name, run, available=lambda _ctx: True):
    return game_search.ProviderSpec(name, "primary", available, run)


def test_provider_success_and_provider_priority(monkeypatch):
    def first(query, limit, ctx, existing):
        return [{"provider": "First", "provider_id": "1", "title": "Example", "developer": "First Dev", "links": []}]

    def second(query, limit, ctx, existing):
        return [{"provider": "Second", "provider_id": "2", "title": "Example", "developer": "Second Dev", "links": []}]

    monkeypatch.setattr(game_search, "PROVIDERS", {
        "First": _fake_spec("First", first),
        "Second": _fake_spec("Second", second),
    })
    monkeypatch.setattr(game_search, "DATA_PROVIDER_NAMES", {"First", "Second"})
    result = game_search.search_game_metadata(
        "Example",
        preferences={"provider_order": ["First", "Second"], "image_provider_order": []},
    )
    assert result["providers"] == ["First", "Second"]
    assert result["results"][0]["provider"] == "First"
    assert result["results"][0]["developer"] == "First Dev"


def test_provider_failure_does_not_hide_other_results(monkeypatch):
    def broken(query, limit, ctx, existing):
        raise RuntimeError("provider unavailable")

    def working(query, limit, ctx, existing):
        return [{"provider": "Working", "provider_id": "1", "title": "Example", "links": []}]

    monkeypatch.setattr(game_search, "PROVIDERS", {
        "Broken": _fake_spec("Broken", broken),
        "Working": _fake_spec("Working", working),
    })
    monkeypatch.setattr(game_search, "DATA_PROVIDER_NAMES", {"Broken", "Working"})
    result = game_search.search_game_metadata(
        "Example",
        preferences={"provider_order": ["Broken", "Working"], "image_provider_order": []},
    )
    assert result["results"][0]["title"] == "Example"
    assert "Broken: provider unavailable" in result["provider_errors"]


def test_unavailable_provider_is_skipped(monkeypatch):
    monkeypatch.setattr(game_search, "PROVIDERS", {
        "Unavailable": _fake_spec("Unavailable", lambda *args: [], available=lambda _ctx: False),
    })
    monkeypatch.setattr(game_search, "DATA_PROVIDER_NAMES", {"Unavailable"})
    result = game_search.search_game_metadata(
        "Example",
        preferences={"provider_order": ["Unavailable"], "image_provider_order": []},
    )
    assert result["providers"] == []
    assert result["results"] == []
    assert result["provider_errors"] == []


def test_no_provider_result_is_a_normal_no_result(monkeypatch):
    monkeypatch.setattr(game_search, "PROVIDERS", {
        "Empty": _fake_spec("Empty", lambda *args: []),
    })
    monkeypatch.setattr(game_search, "DATA_PROVIDER_NAMES", {"Empty"})
    result = game_search.search_game_metadata(
        "Missing",
        preferences={"provider_order": ["Empty"], "image_provider_order": []},
    )
    assert result["results"] == []


def test_malformed_provider_result_is_ignored(monkeypatch):
    monkeypatch.setattr(game_search, "PROVIDERS", {
        "Malformed": _fake_spec("Malformed", lambda *args: [{"provider": "Malformed"}, None]),
    })
    monkeypatch.setattr(game_search, "DATA_PROVIDER_NAMES", {"Malformed"})
    result = game_search.search_game_metadata(
        "Broken",
        preferences={"provider_order": ["Malformed"], "image_provider_order": []},
    )
    assert result["results"] == []
