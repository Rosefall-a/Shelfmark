"""Real registry persistence, isolation reporting, and recovery behavior."""

import json
import uuid
from types import SimpleNamespace

import pytest
import runtime
from runtime import PluginRegistry, PluginSupervisor, RuntimePolicyError
from test_runtime import _package_bytes


def test_startup_probe_reports_actual_bubblewrap_capability(tmp_path, monkeypatch):
    supervisor = PluginSupervisor(tmp_path / "work", tmp_path / "storage")
    calls = []

    def probe(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stderr=b"user namespaces disabled")

    monkeypatch.setattr(runtime.subprocess, "run", probe)
    unavailable = supervisor.probe_isolation()
    assert unavailable["bubblewrap_available"] is False
    assert unavailable["sandbox_available"] is False
    assert unavailable["mechanism"] == "process"
    assert "namespaces" in unavailable["last_error"]
    assert "--unshare-all" in calls[0]
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=b""),
    )
    available = supervisor.probe_isolation()
    assert available["bubblewrap_available"] is True
    assert available["sandbox_available"] is True
    monkeypatch.setenv("NONBUBBLE_ENV", "true")
    reduced = supervisor.probe_isolation()
    assert reduced["bubblewrap_available"] is True
    assert reduced["sandbox_available"] is False
    assert reduced["reduced_isolation_allowed"] is True


def test_missing_bubblewrap_binary_is_reported(tmp_path, monkeypatch):
    supervisor = PluginSupervisor(tmp_path / "work", tmp_path / "storage")

    def missing(*args, **kwargs):
        raise FileNotFoundError("bwrap")

    monkeypatch.setattr(runtime.subprocess, "run", missing)
    assert supervisor.probe_isolation()["bubblewrap_available"] is False


def test_legacy_settings_are_migrated_before_package_replacement(tmp_path):
    supervisor = PluginSupervisor(tmp_path / "work", tmp_path / "storage")
    registry = PluginRegistry(tmp_path / "plugins", supervisor)
    identity = str(uuid.uuid4())
    registry.install_package(_package_bytes(), "package.utp", installation_id=identity)
    package = registry.package("example.upload")[0]
    (package / ".settings.json").write_text(
        json.dumps({"endpoint": "server", "profile": "default"})
    )
    supervisor._storage("example.upload").put("secrets/api-key", b"secret")
    operation = str(uuid.uuid4())
    registry.install_package(
        _package_bytes(version="2.0.0"),
        "update.utp",
        installation_id=identity,
        replace=True,
        expected_version="1.0.0",
        operation_id=operation,
    )
    registry.finish_installation("example.upload", operation, commit=True)
    registry.finish_activation("example.upload", operation, commit=True)
    assert supervisor._settings("example.upload") == {
        "endpoint": "server",
        "profile": "default",
    }
    assert supervisor._storage("example.upload").get("secrets/api-key") == b"secret"
    assert registry.list()[0]["history"][0]["version"] == "1.0.0"
    registry.prune_history("example.upload", retain=1)
    registry.delete("example.upload")
    assert not (tmp_path / ".configuration" / "example.upload.json").exists()
    assert not (registry.root / ".history" / "example.upload").exists()
