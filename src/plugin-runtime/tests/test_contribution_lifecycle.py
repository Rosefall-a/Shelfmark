"""Regression coverage for lifecycle cleanup of host-owned execution workers."""

import json
import threading
import time
from unittest.mock import Mock
from uuid import uuid4

import pytest
from runtime import PluginRegistry, PluginSpec, PluginSupervisor, RuntimePolicyError


def test_stop_terminates_action_workers_even_without_a_main_process(
    tmp_path, monkeypatch
):
    supervisor = PluginSupervisor(
        root=tmp_path / "work", storage_root=tmp_path / "storage"
    )
    action = Mock()
    supervisor._action_processes["contract"] = {action}
    terminate = Mock()
    monkeypatch.setattr(supervisor, "_terminate", terminate)
    supervisor.stop("contract")
    terminate.assert_called_once_with(action, 5.0)
    assert "contract" not in supervisor._action_processes


def test_stop_attempts_every_worker_when_one_cleanup_fails(tmp_path, monkeypatch):
    supervisor = PluginSupervisor(
        root=tmp_path / "work", storage_root=tmp_path / "storage"
    )
    supervisor._action_processes["contract"] = {Mock(), Mock()}
    terminate = Mock(side_effect=[OSError("stop failed"), None])
    monkeypatch.setattr(supervisor, "_terminate", terminate)
    with pytest.raises(RuntimePolicyError, match="cleanup failed"):
        supervisor.stop("contract")
    assert terminate.call_count == 2
    assert len(supervisor._action_processes["contract"]) == 1
    terminate.side_effect = None
    supervisor.stop("contract")
    assert terminate.call_count == 3
    assert "contract" not in supervisor._action_processes


def test_failed_main_cleanup_retains_worker_for_retry(tmp_path, monkeypatch):
    supervisor = PluginSupervisor(
        root=tmp_path / "work", storage_root=tmp_path / "storage"
    )
    process = Mock(returncode=None)
    supervisor._processes["contract"] = process
    terminate = Mock(side_effect=OSError("stop failed"))
    monkeypatch.setattr(supervisor, "_terminate", terminate)
    with pytest.raises(RuntimePolicyError, match="cleanup failed"):
        supervisor.stop("contract")
    assert supervisor._processes["contract"] is process
    terminate.side_effect = None
    supervisor.stop("contract")
    assert "contract" not in supervisor._processes


def test_stop_all_attempts_every_plugin_when_one_cleanup_fails(tmp_path, monkeypatch):
    supervisor = PluginSupervisor(
        root=tmp_path / "work", storage_root=tmp_path / "storage"
    )
    supervisor._action_processes = {"b.contract": {Mock()}, "a.contract": {Mock()}}
    stop = Mock(side_effect=[OSError("stop failed"), None])
    monkeypatch.setattr(supervisor, "stop", stop)
    with pytest.raises(RuntimePolicyError, match="cleanup failed"):
        supervisor.stop_all()
    assert [call.args[0] for call in stop.call_args_list] == [
        "a.contract",
        "b.contract",
    ]


def test_disable_blocks_gateway_requests_before_process_cleanup(tmp_path, monkeypatch):
    package = tmp_path / "packages" / "contract"
    package.mkdir(parents=True)
    manifest = {
        "plugin_id": "contract",
        "entrypoint": "contract:main",
        "integrity": {"sha256": PluginRegistry.digest(package)},
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    supervisor = PluginSupervisor(
        root=tmp_path / "work", storage_root=tmp_path / "storage"
    )
    registry = PluginRegistry(package.parent, supervisor)
    registry._transition(
        "contract", enabled=True, status="running", installation_id=str(uuid4())
    )

    def cleanup(plugin_id):
        assert registry.list()[0]["status"] == "stopping"
        assert not registry.list()[0]["enabled"]
        for method in (
            "lifecycle.ready",
            "events.poll",
            "notification_providers.register",
            "settings.get",
        ):
            with pytest.raises(RuntimePolicyError, match="not active"):
                supervisor._handle_gateway_request(plugin_id, {"method": method})

    monkeypatch.setattr(supervisor, "stop", cleanup)
    registry.stop("contract")
    assert registry.list()[0]["status"] == "disabled"


def test_starting_allows_local_bootstrap_but_not_contributions(tmp_path):
    supervisor = PluginSupervisor(
        root=tmp_path / "work", storage_root=tmp_path / "storage"
    )
    registry = PluginRegistry(tmp_path / "packages", supervisor)
    registry._transition("contract", enabled=True, status="starting")
    for method in ("lifecycle.ready", "settings.get", "storage.get", "storage.keys"):
        assert registry._execution_allowed("contract", method)
    assert supervisor._handle_gateway_request(
        "contract", {"method": "lifecycle.ready"}
    )["payload"] == {"accepted": True}
    for method in (
        "events.poll",
        "notification_providers.register",
        "action",
        "storage.put",
    ):
        assert not registry._execution_allowed("contract", method)
        with pytest.raises(RuntimePolicyError, match="not active"):
            supervisor._handle_gateway_request("contract", {"method": method})


def test_stop_cancels_a_real_inflight_action(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    import runtime

    monkeypatch.setenv("NONBUBBLE_ENV", "true")
    # Windows cannot use preexec_fn; production Linux still exercises resource limits.
    original_popen = subprocess.Popen

    def popen(*args, **kwargs):
        if os.name == "nt":
            kwargs.pop("preexec_fn", None)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    supervisor = PluginSupervisor(
        root=tmp_path / "work", storage_root=tmp_path / "storage"
    )
    errors = []

    def execute():
        try:
            supervisor.execute(
                PluginSpec(
                    "contract", (sys.executable, "-c", "import time; time.sleep(60)")
                ),
                tmp_path,
                b"{}",
                timeout=10,
            )
        except RuntimePolicyError as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=execute, daemon=True)
    worker.start()
    deadline = time.monotonic() + 3
    while (
        not supervisor._action_processes.get("contract") and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    try:
        assert supervisor._action_processes.get("contract")
        supervisor.stop("contract", timeout=0.5)
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert errors
        assert not supervisor._action_processes.get("contract")
    finally:
        supervisor.stop("contract", timeout=0.5)
