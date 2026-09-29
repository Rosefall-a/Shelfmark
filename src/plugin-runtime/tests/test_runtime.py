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

    registry = PluginRegistry(tmp_path / "plugins", PluginSupervisor(tmp_path / "work"))
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
    registry = PluginRegistry(tmp_path / "plugins", PluginSupervisor(tmp_path / "work"))
    with pytest.raises(RuntimePolicyError, match="archive|integrity"):
        registry.install_package(tampered.getvalue(), "bad.utp")


def test_runtime_rejects_duplicate_plugin_install(tmp_path):
    from runtime import PluginRegistry, PluginSupervisor, RuntimePolicyError

    registry = PluginRegistry(tmp_path / "plugins", PluginSupervisor(tmp_path / "work"))
    registry.install_package(_package_bytes(), "first.utp")
    with pytest.raises(RuntimePolicyError, match="already installed"):
        registry.install_package(_package_bytes(), "second.utp")
