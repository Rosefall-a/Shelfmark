"""Real registry persistence, isolation reporting, and recovery behavior."""

import json
import sys
from pathlib import Path
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


@pytest.mark.parametrize("exits", [False, True])
def test_health_verification_observes_real_worker_startup_failure(tmp_path, monkeypatch, exits):
    monkeypatch.setenv("NONBUBBLE_ENV", "true")
    supervisor = PluginSupervisor(tmp_path / "work", tmp_path / "storage")
    registry = PluginRegistry(tmp_path / "plugins", supervisor)
    registry.install_package(_package_bytes(), "worker.utp", installation_id=str(uuid.uuid4()))
    package = registry.package("example.upload")[0]
    command = "import time; time.sleep(0.1); raise SystemExit(9)" if exits else "import time; time.sleep(60)"
    supervisor.start(runtime.PluginSpec("example.upload", (sys.executable, "-c", command)), package)
    try:
        assert registry.health("example.upload") is not exits
        assert registry._state()["example.upload"]["last_health"] is not exits
        if exits:
            assert supervisor._last_exit_codes["example.upload"] == 9
    finally:
        supervisor.stop("example.upload")


@pytest.mark.parametrize("boundary", ["before_publish", "after_publish", "history", "rollback"])
def test_runtime_exit_during_filesystem_switch_recovers_journal(tmp_path, monkeypatch, boundary):
    supervisor = PluginSupervisor(tmp_path / "work", tmp_path / "storage")
    running = set()
    monkeypatch.setattr(supervisor, "start", lambda spec, package: running.add(spec.plugin_id))
    monkeypatch.setattr(supervisor, "stop", lambda plugin: running.discard(plugin))
    monkeypatch.setattr(supervisor, "running", lambda plugin: plugin in running)
    registry = PluginRegistry(tmp_path / "plugins", supervisor)
    plugin = "example.upload"
    identity, operation = str(uuid.uuid4()), str(uuid.uuid4())
    registry.install_package(_package_bytes(), "first.utp", installation_id=identity)
    registry.start(plugin, user_id="administrator")
    registry.settings(plugin, {"server": "media.example", "profile": "default"})
    supervisor._storage(plugin).put("secrets/api-key", b"secret")

    def prepare():
        registry.install_package(_package_bytes(version="2.0.0"), "second.utp", replace=True,
                                 expected_version="1.0.0", installation_id=identity, operation_id=operation)

    if boundary in {"history", "rollback"}:
        prepare()
        registry.finish_installation(plugin, operation, commit=True)
    original_rename = Path.rename
    original_save = registry._save_state
    with monkeypatch.context() as interrupted:
        def rename(path, destination):
            if boundary == "before_publish" and path.name.startswith(".install-"):
                raise SystemExit("runtime exited before candidate publication")
            result = original_rename(path, destination)
            if ((boundary == "history" and path.name.startswith(".backup-"))
                    or (boundary == "rollback" and Path(destination).name.startswith(".rejected-"))):
                raise SystemExit("runtime exited after package rename")
            return result

        def save(state):
            pending = state.get(plugin, {}).get("pending_installation", {})
            if boundary == "after_publish" and pending.get("publication_pending") is False:
                raise SystemExit("runtime exited before publication acknowledgement")
            original_save(state)

        interrupted.setattr(Path, "rename", rename)
        interrupted.setattr(registry, "_save_state", save)
        with pytest.raises(SystemExit):
            if boundary in {"before_publish", "after_publish"}:
                prepare()
            else:
                registry.finish_activation(plugin, operation, commit=boundary == "history")

    restarted = PluginRegistry(registry.root, supervisor)
    if boundary == "history":
        # The host must re-verify activation; the durable history move is repeatable.
        assert restarted.list()[0]["pending_transaction"]["phase"] == "activation"
        restarted.finish_activation(plugin, operation, commit=True)
        assert [item["version"] for item in restarted.list()[0]["history"]] == ["1.0.0"]
    else:
        assert restarted.package(plugin)[1]["version"] == "1.0.0"
    assert restarted.list()[0]["pending_transaction"] is None
    assert restarted.list()[0]["enabled"]
    assert supervisor._settings(plugin) == {"server": "media.example", "profile": "default"}
    assert supervisor._storage(plugin).get("secrets/api-key") == b"secret"
