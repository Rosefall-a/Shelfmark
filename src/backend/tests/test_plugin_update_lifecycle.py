"""Integration-level regressions for update discovery and permission review."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.routes import plugins
from src.database.models import achievement as _achievement  # noqa: F401
from src.plugin_api.installer import inspect_package
from src.plugin_api.updates import PluginPackageVerifier


def _unsigned_update(path: Path) -> None:
    payload = b"def main():\n    pass\n"
    digest = hashlib.sha256()
    digest.update(b"plugin.py\0")
    digest.update(payload)
    digest.update(b"\0")
    manifest = {
        "manifest_version": 1,
        "plugin_id": "example.update",
        "name": "Update Example",
        "version": "2.0.0",
        "entrypoint": "plugin:main",
        "sdk_version_range": "*",
        "application_version_range": "*",
        "capabilities": [{"name": "api.full", "version": 1}],
        "permissions": [
            {
                "capability": {"name": "api.full", "version": 1},
                "rationale": "Exercise update permission review.",
            }
        ],
        "dependencies": [],
        "integrity": {"sha256": digest.hexdigest()},
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("payload/plugin.py", payload)


@pytest.mark.asyncio
async def test_catalogue_update_detection_includes_release_notes(monkeypatch) -> None:
    async def fake_catalog(*, source, user):
        assert source == "https://catalogue.example/list.json"
        assert user is not None
        return [
            plugins.PluginCatalogEntry(
                plugin_id="example.update",
                name="Update Example",
                version="2.0.0",
                url="https://packages.example/update.utp",
                release_notes="Security fixes",
            )
        ]

    monkeypatch.setattr(plugins, "plugin_catalog", fake_catalog)
    result = await plugins._check_plugin_update(
        {
            "plugin_id": "example.update",
            "version": "1.0.0",
            "source": {
                "type": "catalogue",
                "catalogue_url": "https://catalogue.example/list.json",
            },
        },
        SimpleNamespace(),
    )
    assert result["update_available"] is True
    assert result["available_version"] == "2.0.0"
    assert result["release_notes"] == "Security fixes"


@pytest.mark.asyncio
async def test_unverified_update_re_reviews_every_permission(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "update.bin"
    _unsigned_update(package)
    inspected = inspect_package(package, PluginPackageVerifier(require_signature=False))
    installation_id = uuid4()

    class Runtime:
        async def plugins(self):
            return [
                {
                    "plugin_id": "example.update",
                    "version": "1.0.0",
                    "installation_id": str(installation_id),
                    "trust": {"status": "unsigned", "publisher_key_id": None},
                    "permission_refs": [{"name": "api.full", "version": 1}],
                    "dependencies": [],
                }
            ]

    class Result:
        def all(self):
            return [("api.full", 1)]

    class Db:
        async def execute(self, statement):
            del statement
            return Result()

    monkeypatch.setattr(plugins, "_client", Runtime())
    _, _, delta, _, can_retain = await plugins._update_context(
        "example.update",
        inspected,
        Db(),
    )
    assert can_retain is False
    assert [item.name.value for item in delta.newly_requested_grants] == ["api.full"]
    assert delta.existing_grants == ()


@pytest.mark.asyncio
async def test_update_notification_uses_existing_notification_rows() -> None:
    admin_id = uuid4()

    class Db:
        def __init__(self) -> None:
            self.calls = 0
            self.rows = []

        async def scalars(self, statement):
            del statement
            self.calls += 1
            return [admin_id] if self.calls == 1 else []

        def add(self, row):
            self.rows.append(row)

    db = Db()
    await plugins._notify_plugin_update(
        db,
        {
            "plugin_id": "example.update",
            "current_version": "1.0.0",
            "available_version": "2.0.0",
            "update_available": True,
        },
    )
    assert len(db.rows) == 1
    assert db.rows[0].kind == "plugin_update"
    assert db.rows[0].dedupe_key == "plugin-update:example.update:2.0.0"


@pytest.mark.asyncio
async def test_inline_changelog_is_returned_before_update(monkeypatch) -> None:
    class Runtime:
        async def plugins(self):
            return [{"plugin_id": "example.update", "version": "1.0.0"}]

    async def fake_check(plugin, admin):
        del plugin, admin
        return {
            "available_version": "2.0.0",
            "release_notes": "Security fixes",
        }

    monkeypatch.setattr(plugins, "_client", Runtime())
    monkeypatch.setattr(plugins, "_check_plugin_update", fake_check)
    changelog = await plugins.plugin_changelog("example.update", SimpleNamespace())
    assert changelog == {
        "plugin_id": "example.update",
        "version": "2.0.0",
        "format": "markdown",
        "source": "catalogue",
        "body": "Security fixes",
    }


@pytest.mark.asyncio
async def test_catalogue_failure_updates_persistent_status(monkeypatch, tmp_path: Path) -> None:
    registry = tmp_path / "catalogues.json"
    monkeypatch.setenv("PLUGIN_CATALOGUE_REGISTRY", str(registry))
    plugins._catalogue_store_for.cache_clear()
    store = plugins._catalogue_store()
    catalogue = store.add(
        name="Broken",
        url="https://catalogue.example/list.json",
        enabled=True,
        priority=10,
    )

    async def fail_download(url, *, json_document=False):
        del url, json_document
        raise HTTPException(status_code=502, detail="network failure")

    monkeypatch.setattr(plugins, "_download_remote_file", fail_download)
    with pytest.raises(HTTPException):
        await plugins.plugin_catalog(
            source="https://catalogue.example/list.json",
            user=SimpleNamespace(),
        )
    persisted = next(item for item in store.list() if item["id"] == catalogue["id"])
    assert persisted["last_error"] == "network failure"
