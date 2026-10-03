"""Tests for persistent multi-catalogue configuration."""

from pathlib import Path

import pytest

from src.plugin_api.catalogues import CatalogueStore, CatalogueStoreError


def test_official_catalogue_is_enabled_and_package_trust_stays_independent(
    tmp_path: Path,
) -> None:
    store = CatalogueStore(tmp_path / "catalogues.json", "https://official.example/list.json")
    official = store.list()[0]
    assert official["id"] == "official"
    assert official["enabled"] is True
    assert official["trust_metadata"]["package_signature_trust"] == "independent"


def test_catalogue_metadata_and_failures_are_persisted(tmp_path: Path) -> None:
    store = CatalogueStore(tmp_path / "catalogues.json", "https://official.example/list.json")
    added = store.add(
        name="Community",
        url="https://community.example/list.json",
        enabled=True,
        priority=50,
    )
    store.record_check(added["id"], "network failure")
    persisted = next(item for item in store.list() if item["id"] == added["id"])
    assert persisted["last_error"] == "network failure"
    assert persisted["last_successful_check"] is None

    store.record_check(added["id"], None)
    persisted = next(item for item in store.list() if item["id"] == added["id"])
    assert persisted["last_error"] is None
    assert isinstance(persisted["last_successful_check"], int)
    successful_at = persisted["last_successful_check"]

    store.record_check(added["id"], "later failure")
    persisted = next(item for item in store.list() if item["id"] == added["id"])
    assert persisted["last_successful_check"] == successful_at

    with pytest.raises(CatalogueStoreError, match="official"):
        store.remove("official")


def test_official_catalogue_check_metadata_is_persisted(tmp_path: Path) -> None:
    store = CatalogueStore(tmp_path / "catalogues.json", "https://official.example/list.json")
    store.record_check("official", "temporarily unavailable")
    official = next(item for item in store.list() if item["id"] == "official")
    assert official["last_error"] == "temporarily unavailable"

    store.record_check("official", None)
    official = next(item for item in store.list() if item["id"] == "official")
    assert official["last_error"] is None
    assert isinstance(official["last_successful_check"], int)
