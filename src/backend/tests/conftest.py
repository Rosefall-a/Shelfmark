"""Keep durable plugin manager records isolated between application tests."""

import pytest


@pytest.fixture(autouse=True)
def isolated_plugin_manager_state(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGIN_MANAGER_STATE_PATH", str(tmp_path / "plugin-manager.json"))
