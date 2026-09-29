from __future__ import annotations

import hashlib
import json
from pathlib import Path

from runtime import PluginRegistry, PluginSupervisor


def package_digest(package: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        p for p in package.rglob("*")
        if p.is_file() and p.name not in {"manifest.json", ".settings.json"}
    ):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_runtime_discovers_and_serves_declarative_plugin(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    package = root / "example.plugin"
    package.mkdir(parents=True)
    (package / "main.py").write_text("def main():\n    return None\n", encoding="utf-8")
    (package / "ui.json").write_text(
        json.dumps({
            "schema_version": "v1", "plugin_id": "example.plugin", "title": "Example",
            "settings": [], "actions": [{"id": "ping", "handler": "main:action"}], "tables": [], "dialogs": [], "menus": [],
            "pages": [],
        }),
        encoding="utf-8",
    )
    digest = package_digest(package)
    (package / "manifest.json").write_text(
        json.dumps({
            "plugin_id": "example.plugin", "name": "Example", "version": "1.0.0",
            "entrypoint": "main:main", "integrity": {"sha256": digest},
        }),
        encoding="utf-8",
    )

    registry = PluginRegistry(root, PluginSupervisor(root=tmp_path / "processes"))
    items = registry.list()
    assert items[0]["plugin_id"] == "example.plugin"
    assert items[0]["compatible"] is True
    assert items[0]["enabled"] is False
    assert items[0]["status"] == "disabled"
    assert registry.ui("example.plugin")["title"] == "Example"


def test_runtime_dispatches_declared_action_in_supervisor(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "plugins"
    package = root / "example.plugin"
    package.mkdir(parents=True)
    (package / "main.py").write_text("def main():\n    return None\n", encoding="utf-8")
    (package / "ui.json").write_text(
        json.dumps({"plugin_id": "example.plugin", "settings": [], "actions": [{"id": "ping", "handler": "main:action"}]}),
        encoding="utf-8",
    )
    digest = package_digest(package)
    (package / "manifest.json").write_text(
        json.dumps({"plugin_id": "example.plugin", "name": "Example", "version": "1.0.0", "entrypoint": "main:main", "integrity": {"sha256": digest}}),
        encoding="utf-8",
    )
    registry = PluginRegistry(root, PluginSupervisor(root=tmp_path / "processes"))
    calls = []
    monkeypatch.setattr(registry.supervisor, "execute", lambda spec, package, payload: calls.append((spec, package, payload)))

    assert registry.action("example.plugin", "ping", {"value": "ok"}) == {"completed": True}
    assert calls[0][0].command[0] == "python"
    assert calls[0][2] == b'{"value":"ok"}'


def test_runtime_handles_discord_action_output(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "plugins"
    package = root / "example.plugin"
    package.mkdir(parents=True)
    (package / "main.py").write_text("def main():\n    return None\n", encoding="utf-8")
    (package / "ui.json").write_text(json.dumps({"plugin_id": "example.plugin", "settings": [], "actions": [{"id": "announce", "handler": "main:action"}]}), encoding="utf-8")
    digest = package_digest(package)
    (package / "manifest.json").write_text(json.dumps({"plugin_id": "example.plugin", "name": "Example", "version": "1.0.0", "entrypoint": "main:main", "capabilities": [{"name": "notifications.send", "version": 1}], "integrity": {"sha256": digest}}), encoding="utf-8")
    registry = PluginRegistry(
        root,
        PluginSupervisor(root=tmp_path / "processes", storage_root=tmp_path / "storage"),
    )
    monkeypatch.setenv("PLUGIN_RUNTIME_DISCORD_EGRESS", "true")
    registry.supervisor._storage("example.plugin").put(
        "secrets/discord_webhook",
        b"https://discord.com/api/webhooks/test/x",
    )
    monkeypatch.setattr(registry.supervisor, "execute", lambda spec, package, payload: b'{"discord":true,"content":"hello"}')
    sent = []
    monkeypatch.setattr(registry, "_discord_webhook", lambda url, content: sent.append((url, content)))

    assert registry.action("example.plugin", "announce", {}) == {"completed": True}
    assert sent == [("https://discord.com/api/webhooks/test/x", "hello")]


def test_runtime_rejects_tampered_package(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    package = root / "example.plugin"
    package.mkdir(parents=True)
    (package / "main.py").write_text("def main():\n    return None\n", encoding="utf-8")
    (package / "manifest.json").write_text(
        json.dumps({
            "plugin_id": "example.plugin", "name": "Example", "version": "1.0.0",
            "entrypoint": "main:main", "integrity": {"sha256": "0" * 64},
        }),
        encoding="utf-8",
    )
    registry = PluginRegistry(root, PluginSupervisor(root=tmp_path / "processes"))
    assert registry.list()[0]["compatible"] is False
