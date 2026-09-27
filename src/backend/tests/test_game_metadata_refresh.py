"""Regression tests for the editor metadata refresh contract."""

from types import SimpleNamespace

from src.api.routes.games import _metadata_value_is_present, _normalize_metadata_title
from src.features.metadata.locked_fields import apply_updates_with_locking


def test_provider_title_matching_ignores_marks_and_case():
    assert _normalize_metadata_title("Portal 2™") == "portal 2"


def test_provider_empty_values_are_not_applied():
    assert _metadata_value_is_present(None) is False
    assert _metadata_value_is_present("") is False
    assert _metadata_value_is_present([]) is False
    assert _metadata_value_is_present("value") is True


def test_manual_edit_records_a_lock():
    game = SimpleNamespace(description="Provider description", locked_fields=[])
    apply_updates_with_locking(game, {"description": "My description"}, {"description"})
    assert game.description == "My description"
    assert game.locked_fields == ["description"]


def test_provider_refresh_skips_existing_manual_lock():
    game = SimpleNamespace(description="My description", developer="Old", locked_fields=["description"])
    provider = {"description": "Provider description", "developer": "New"}
    safe = {k: v for k, v in provider.items() if k not in game.locked_fields}
    apply_updates_with_locking(game, safe, {"description", "developer"})
    assert game.description == "My description"
    assert game.developer == "New"
