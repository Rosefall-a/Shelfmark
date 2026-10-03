"""Runtime contract test helpers; no plugin implementation is executed."""

import json
from uuid import uuid4

import pytest


@pytest.fixture
def activate_registry(monkeypatch):
    def activate(registry, plugin_id):
        package, manifest = registry.package(plugin_id)
        manifest["integrity"] = {"sha256": registry.digest(package)}
        (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        registry._transition(
            plugin_id, enabled=True, status="running", installation_id=str(uuid4())
        )
        monkeypatch.setattr(registry.supervisor, "running", lambda _: True)

    return activate
