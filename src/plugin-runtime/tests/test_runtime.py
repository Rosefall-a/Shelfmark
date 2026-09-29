from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from runtime import (
    OutboundNetworkPolicy,
    PluginSpec,
    ResourceLimits,
    RuntimePolicyError,
)


def test_plugin_environment_is_default_deny_for_core_secrets() -> None:
    with pytest.raises(RuntimePolicyError):
        PluginSpec("example", ("run",), {"SECRET_KEY": "nope"}).validate()


def test_plugin_ids_and_commands_are_validated() -> None:
    with pytest.raises(RuntimePolicyError):
        PluginSpec("../escape", ("run",)).validate()
    with pytest.raises(RuntimePolicyError):
        PluginSpec("example", ()).validate()


def test_network_is_default_deny() -> None:
    policy = OutboundNetworkPolicy()
    policy.validate()
    assert policy.allowed_hosts == ()


def test_network_requires_capability_approval() -> None:
    with pytest.raises(RuntimePolicyError, match="network.outbound"):
        OutboundNetworkPolicy(("api.example.com",), (443,), False).validate()


def test_network_ports_are_bounded() -> None:
    with pytest.raises(RuntimePolicyError):
        OutboundNetworkPolicy(("api.example.com",), (70000,), True).validate()


def test_resource_limits_are_positive() -> None:
    with pytest.raises(RuntimePolicyError):
        PluginSpec(
            "example",
            ("run",),
            resources=ResourceLimits(cpu_seconds=0),
        ).validate()


def test_supervisor_starts_a_validated_plugin_in_its_sandbox(tmp_path, monkeypatch) -> None:
    import runtime
    from runtime import PluginSupervisor

    class FakeProcess:
        pid = 123

        @staticmethod
        def poll():
            return None

    calls = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)
    supervisor = PluginSupervisor(root=tmp_path / "work", storage_root=tmp_path / "storage")
    package = tmp_path / "package"
    package.mkdir()
    process = supervisor.start(PluginSpec("example", ("python", "-c", "pass")), package)

    assert process.pid == 123
    assert supervisor.running("example") is True
    assert calls[0][0][0][:2] == ["bwrap", "--unshare-all"]
    assert calls[0][1]["env"]["HOME"] == "/plugin"
    assert (tmp_path / "work" / "example").is_dir()


def test_supervisor_can_start_without_bubblewrap_for_development(tmp_path, monkeypatch) -> None:
    import runtime
    from runtime import PluginSupervisor

    class FakeProcess:
        pid = 123

        @staticmethod
        def poll():
            return None

    calls = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setenv("NONBUBBLE_ENV", "true")
    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)
    supervisor = PluginSupervisor(root=tmp_path / "work", storage_root=tmp_path / "storage")
    package = tmp_path / "package"
    package.mkdir()
    supervisor.start(PluginSpec("example", ("python", "-c", "pass")), package)

    assert calls[0][0][0] == ["python", "-c", "pass"]
    assert calls[0][1]["cwd"] == package
    assert calls[0][1]["env"]["HOME"] == str(package)


def test_nonbubble_flag_is_off_by_default(monkeypatch) -> None:
    from runtime import PluginSupervisor

    monkeypatch.delenv("NONBUBBLE_ENV", raising=False)
    assert PluginSupervisor._nonbubble_enabled() is False


def _package_bytes(plugin_id: str = "example.upload") -> bytes:
    files = {"plugin.py": b"def main():\n    return None\n", "sdk/plugin_protocol.py": b"API_VERSION = 1\n"}
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("utf-8")); digest.update(b"\0"); digest.update(data); digest.update(b"\0")
    manifest = {
        "manifest_version": 1, "plugin_id": plugin_id, "name": "Upload Example", "version": "1.0.0",
        "entrypoint": "plugin:main", "sdk_version_range": "*", "application_version_range": "*",
        "capabilities": [], "permissions": [], "dependencies": [],
        "integrity": {"sha256": digest.hexdigest()},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items(): archive.writestr("payload/" + name, data)
    return output.getvalue()


def test_runtime_installs_verified_utp_atomically(tmp_path):
    from runtime import PluginRegistry, PluginSupervisor

    registry = PluginRegistry(tmp_path / "plugins", PluginSupervisor(tmp_path / "work", storage_root=tmp_path / "storage"))
    result = registry.install_package(_package_bytes(), "example-upload.utp")
    assert result["plugin_id"] == "example.upload"
    assert (tmp_path / "plugins" / "example.upload" / "manifest.json").is_file()
    assert (tmp_path / "plugins" / "example.upload" / "plugin.py").is_file()


def test_runtime_rejects_tampered_utp(tmp_path):
    from runtime import PluginRegistry, PluginSupervisor, RuntimePolicyError

    original = _package_bytes()
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(tampered, "w") as destination:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "payload/plugin.py":
                data = b"tampered"
            destination.writestr(info, data)
    registry = PluginRegistry(tmp_path / "plugins", PluginSupervisor(tmp_path / "work", storage_root=tmp_path / "storage"))
    with pytest.raises(RuntimePolicyError, match="archive|integrity"):
        registry.install_package(tampered.getvalue(), "bad.utp")


def test_runtime_rejects_duplicate_plugin_install(tmp_path):
    from runtime import PluginRegistry, PluginSupervisor, RuntimePolicyError

    registry = PluginRegistry(tmp_path / "plugins", PluginSupervisor(tmp_path / "work"))
    registry.install_package(_package_bytes(), "first.utp")
    with pytest.raises(RuntimePolicyError, match="already installed"):
        registry.install_package(_package_bytes(), "second.utp")


def test_plugin_storage_files_are_owner_only(tmp_path) -> None:
    from storage import PluginStorage

    storage = PluginStorage(tmp_path / "storage", "example", quota_bytes=1024)
    storage.put("secrets/webhook", b"secret")
    assert (storage.root / "secrets" / "webhook").stat().st_mode & 0o777 == 0o600
    assert (storage.root / ".storage.json").stat().st_mode & 0o777 == 0o600


def test_frontend_asset_is_namespaced(tmp_path) -> None:
    from runtime import PluginRegistry, PluginSupervisor

    registry = PluginRegistry(tmp_path / "plugins", PluginSupervisor(tmp_path / "work", storage_root=tmp_path / "storage"))
    package = tmp_path / "plugins" / "example.frontend"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(json.dumps({
        "plugin_id": "example.frontend",
        "entrypoint": "plugin:main",
        "frontend": {"entry": "frontend/index.html"},
    }), encoding="utf-8")
    frontend = package / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<div>ok</div>", encoding="utf-8")
    asset = registry.frontend("example.frontend", "frontend/index.html")
    assert asset["path"] == "frontend/index.html"
    assert "PG" in asset["content"]


def test_runtime_gateway_settings_use_active_package_path(tmp_path) -> None:
    from runtime import PluginSupervisor

    package = tmp_path / "package"
    package.mkdir()
    (package / ".settings.json").write_text(json.dumps({"display_mode": "dark"}), encoding="utf-8")
    supervisor = PluginSupervisor(
        root=tmp_path / "work",
        storage_root=tmp_path / "storage",
        gateway_url="http://gateway",
        gateway_token="x" * 32,
    )
    supervisor._package_paths["example.ui-api"] = package
    assert supervisor._handle_gateway_request(
        "example.ui-api",
        {"method": "settings.get", "capability": "plugin.settings", "payload": {"key": "display_mode"}},
    ) == {"payload": {"value": "dark"}}


def test_runtime_digest_ignores_python_runtime_cache(tmp_path) -> None:
    from runtime import PluginRegistry

    package = tmp_path / "package"
    package.mkdir()
    (package / "plugin.py").write_text("def main(): pass\n", encoding="utf-8")
    digest = PluginRegistry.digest(package)
    cache = package / "__pycache__"
    cache.mkdir()
    (cache / "plugin.cpython-312.pyc").write_bytes(b"runtime-generated")
    assert PluginRegistry.digest(package) == digest
    (package / "plugin.py").write_text("def main(): return 1\n", encoding="utf-8")
    assert PluginRegistry.digest(package) != digest
