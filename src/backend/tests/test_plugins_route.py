from pathlib import Path

import pytest

from src.api.routes import plugins


def test_plugin_state_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(plugins, "_STATE_PATH", state_path)

    assert plugins._load_state() == {}
    plugins._save_state({"demo": True})
    assert plugins._load_state() == {"demo": True}
