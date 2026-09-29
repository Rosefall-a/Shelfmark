"""Tests for plugin lifecycle, health, quarantine and safe mode."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.plugin_api.contracts import PluginManifest
from src.plugin_api.lifecycle import LifecycleState, NoopPackageInstaller, PluginLifecycleManager, Sha256PackageVerifier
from src.plugin_api.updates import canonical_payload_digest


def manifest_data(plugin_id: str = "example.plugin", app_range: str = "*") -> dict:
    return {
        "plugin_id": plugin_id, "name": "Example", "version": "1.0.0",
        "entrypoint": "plugin:main", "sdk_version_range": "*",
        "application_version_range": app_range, "integrity": {"sha256": "a" * 64},
    }


class FakeRuntime:
    def __init__(self, *, healthy: bool = True, fail_start: bool = False) -> None:
        self.healthy = healthy
        self.fail_start = fail_start
        self.started: list[str] = []
        self.stopped: list[str] = []

    async def start(self, plugin_id: str, package_path: Path) -> None:
        del package_path
        if self.fail_start:
            raise RuntimeError("sandbox unavailable")
        self.started.append(plugin_id)

    async def stop(self, plugin_id: str) -> None:
        self.stopped.append(plugin_id)

    async def health(self, plugin_id: str) -> bool:
        del plugin_id
        return self.healthy


class AlwaysValidVerifier:
    def verify(self, package_path: Path, expected_sha256: str) -> bool:
        del package_path, expected_sha256
        return True


def manager(runtime: FakeRuntime, **kwargs) -> PluginLifecycleManager:
    return PluginLifecycleManager(
        sdk_version="1.0.0", application_version="1.0.0", runtime=runtime,
        installer=NoopPackageInstaller(), verifier=AlwaysValidVerifier(), **kwargs,
    )


def discover(manager: PluginLifecycleManager, tmp_path: Path, data: dict | None = None) -> None:
    path = tmp_path / f"{data.get('plugin_id', 'example.plugin') if data else 'example.plugin'}.json"
    path.write_text(json.dumps(data or manifest_data()), encoding="utf-8")
    manager.discover([path])


def install(manager: PluginLifecycleManager, plugin_id: str = "example.plugin") -> None:
    asyncio.run(manager.install(plugin_id))


def test_discovery_is_static_and_does_not_execute_plugins(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    lifecycle = manager(runtime)
    discover(lifecycle, tmp_path)
    assert lifecycle.health("example.plugin").state == LifecycleState.DISCOVERED
    assert runtime.started == []


def test_incompatible_and_invalid_plugins_are_contained(tmp_path: Path) -> None:
    lifecycle = manager(FakeRuntime())
    discover(lifecycle, tmp_path, manifest_data(app_range=">=2.0.0,<3.0.0"))
    assert lifecycle.health("example.plugin").state == LifecycleState.INCOMPATIBLE

    broken = tmp_path / "broken.json"
    broken.write_text("{not-json", encoding="utf-8")
    record = lifecycle.discover([broken])[0]
    assert record.state == LifecycleState.INVALID
    assert record.last_error


def test_install_then_start_uses_runtime_boundary(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    lifecycle = manager(runtime)
    discover(lifecycle, tmp_path)
    assert asyncio.run(lifecycle.install("example.plugin")).state == LifecycleState.INSTALLED
    assert asyncio.run(lifecycle.start("example.plugin")).state == LifecycleState.RUNNING
    assert runtime.started == ["example.plugin"]


def test_dependency_order_is_deterministic(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    lifecycle = manager(runtime)
    base = manifest_data("base")
    dependent = manifest_data("dependent")
    dependent["dependencies"] = [{"plugin_id": "base", "version_range": "^1.0.0"}]
    for data in (dependent, base):
        path = tmp_path / f"{data['plugin_id']}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
    lifecycle.discover([tmp_path / "dependent.json", tmp_path / "base.json"])
    install(lifecycle, "base")
    install(lifecycle, "dependent")
    asyncio.run(lifecycle.start_enabled())
    assert runtime.started == ["base", "dependent"]


def test_start_failures_are_contained_and_quarantined(tmp_path: Path) -> None:
    runtime = FakeRuntime(fail_start=True)
    lifecycle = manager(runtime, quarantine_after=2)
    discover(lifecycle, tmp_path)
    install(lifecycle)
    asyncio.run(lifecycle.start("example.plugin"))
    assert lifecycle.health("example.plugin").state == LifecycleState.FAILED_START
    asyncio.run(lifecycle.start("example.plugin"))
    health = lifecycle.health("example.plugin")
    assert health.state == LifecycleState.QUARANTINED
    assert health.consecutive_failures == 2
    assert not lifecycle.records()[0].enabled


def test_health_failures_quarantine_and_success_resets(tmp_path: Path) -> None:
    runtime = FakeRuntime(healthy=False)
    lifecycle = manager(runtime, quarantine_after=2)
    discover(lifecycle, tmp_path)
    install(lifecycle)
    asyncio.run(lifecycle.start("example.plugin"))
    asyncio.run(lifecycle.health_check("example.plugin"))
    assert lifecycle.health("example.plugin").state == LifecycleState.UNHEALTHY
    asyncio.run(lifecycle.health_check("example.plugin"))
    assert lifecycle.health("example.plugin").state == LifecycleState.QUARANTINED


def test_safe_mode_prevents_plugin_activation(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    lifecycle = manager(runtime)
    discover(lifecycle, tmp_path)
    install(lifecycle)
    lifecycle.set_safe_mode(True)
    asyncio.run(lifecycle.start_enabled())
    assert runtime.started == []
    assert lifecycle.safe_mode


def test_quarantine_requires_explicit_recovery(tmp_path: Path) -> None:
    runtime = FakeRuntime(fail_start=True)
    lifecycle = manager(runtime, quarantine_after=1)
    discover(lifecycle, tmp_path)
    install(lifecycle)
    asyncio.run(lifecycle.start("example.plugin"))
    assert lifecycle.health("example.plugin").state == LifecycleState.QUARANTINED
    record = asyncio.run(lifecycle.recover("example.plugin"))
    assert record.state == LifecycleState.DISABLED
    assert not record.enabled
    assert record.consecutive_failures == 0


class FailingInstaller:
    async def install(self, package_path: Path, manifest: PluginManifest) -> Path:
        del package_path, manifest
        raise RuntimeError("installer unavailable")


def test_install_failure_has_deterministic_failure_state(tmp_path: Path) -> None:
    lifecycle = PluginLifecycleManager(
        sdk_version="1.0.0",
        application_version="1.0.0",
        runtime=FakeRuntime(),
        installer=FailingInstaller(),
        verifier=AlwaysValidVerifier(),
        quarantine_after=2,
    )
    discover(lifecycle, tmp_path)
    record = asyncio.run(lifecycle.install("example.plugin"))
    assert record.state == LifecycleState.FAILED_INSTALL
    assert record.last_error
    assert record.consecutive_failures == 1


def test_stop_failure_is_not_overwritten_by_stopped_state(tmp_path: Path) -> None:
    class FailingStopRuntime(FakeRuntime):
        async def stop(self, plugin_id: str) -> None:
            del plugin_id
            raise RuntimeError("stop unavailable")

    lifecycle = manager(FailingStopRuntime())
    discover(lifecycle, tmp_path)
    install(lifecycle)
    asyncio.run(lifecycle.start("example.plugin"))
    record = asyncio.run(lifecycle.stop("example.plugin"))
    assert record.state == LifecycleState.FAILED_STOP
    assert record.consecutive_failures == 1


def test_disabling_running_plugin_stops_runtime(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    lifecycle = manager(runtime)
    discover(lifecycle, tmp_path)
    install(lifecycle)
    asyncio.run(lifecycle.start("example.plugin"))
    record = asyncio.run(lifecycle.disable("example.plugin"))
    assert record.state == LifecycleState.DISABLED
    assert record.enabled is False
    assert runtime.stopped == ["example.plugin"]


def test_quarantine_stops_running_runtime(tmp_path: Path) -> None:
    runtime = FakeRuntime(healthy=False)
    lifecycle = manager(runtime, quarantine_after=2)
    discover(lifecycle, tmp_path)
    install(lifecycle)
    asyncio.run(lifecycle.start("example.plugin"))
    asyncio.run(lifecycle.health_check("example.plugin"))
    asyncio.run(lifecycle.health_check("example.plugin"))
    assert lifecycle.health("example.plugin").state == LifecycleState.QUARANTINED
    assert runtime.stopped == ["example.plugin"]


def test_disable_running_plugin_stops_before_disabled_state(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    lifecycle = manager(runtime)
    discover(lifecycle, tmp_path)
    install(lifecycle)
    asyncio.run(lifecycle.start("example.plugin"))
    record = asyncio.run(lifecycle.disable("example.plugin"))
    assert record.state == LifecycleState.DISABLED
    assert runtime.stopped == ["example.plugin"]


def test_uninstall_cleans_plugin_storage_before_removing_record(tmp_path: Path) -> None:
    class FakeStorage:
        def __init__(self) -> None:
            self.uninstalled: list[str] = []

        def uninstall(self, plugin_id: str) -> None:
            self.uninstalled.append(plugin_id)

    runtime = FakeRuntime()
    storage = FakeStorage()
    lifecycle = manager(runtime, storage_cleanup=storage)
    discover(lifecycle, tmp_path)
    install(lifecycle)
    asyncio.run(lifecycle.uninstall("example.plugin"))
    assert storage.uninstalled == ["example.plugin"]
    assert lifecycle.records() == ()


def test_uninstall_keeps_record_when_storage_cleanup_fails(tmp_path: Path) -> None:
    class FailingStorage:
        def uninstall(self, plugin_id: str) -> None:
            raise RuntimeError(f"cannot remove {plugin_id}")

    runtime = FakeRuntime()
    lifecycle = manager(runtime, storage_cleanup=FailingStorage())
    discover(lifecycle, tmp_path)
    install(lifecycle)
    try:
        asyncio.run(lifecycle.uninstall("example.plugin"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("uninstall should report storage cleanup failure")
    assert lifecycle.records()[0].manifest.plugin_id == "example.plugin"


def test_default_verifier_uses_v1_payload_digest(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text("{}", encoding="utf-8")
    (package / "plugin.py").write_bytes(b"print('ok')")
    expected = canonical_payload_digest([("plugin.py", b"print('ok')")])
    assert Sha256PackageVerifier().verify(package, expected)
    assert not Sha256PackageVerifier().verify(package, "0" * 64)


def test_default_verifier_ignores_manifest_bytes(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text("one", encoding="utf-8")
    (package / "plugin.py").write_bytes(b"payload")
    expected = canonical_payload_digest([("plugin.py", b"payload")])
    (package / "manifest.json").write_text("different", encoding="utf-8")
    assert Sha256PackageVerifier().verify(package, expected)
