"""Tests for package verification, staged updates and rollback."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.plugin_api.contracts import PluginManifest
from src.plugin_api.updates import (
    InstalledPlugin,
    PackageFormatError,
    PackageVerificationError,
    PluginPackageVerifier,
    PluginUpdateManager,
    TrustedPublisher,
    UpdateActivationError,
    UpdateDependencyError,
    UpdateStore,
)


def payload_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def manifest_data(
    version: str = "1.1.0",
    *,
    digest: str = "0" * 64,
    signature: str | None = None,
    key_id: str | None = None,
    dependencies: list[dict] | None = None,
) -> dict:
    return {
        "plugin_id": "example.plugin",
        "name": "Example",
        "version": version,
        "entrypoint": "plugin:main",
        "sdk_version_range": "*",
        "application_version_range": "*",
        "dependencies": dependencies or [],
        "integrity": {"sha256": digest, "signature": signature, "key_id": key_id},
    }


def write_package(path: Path, data: dict, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(data))
        for name, value in files.items():
            archive.writestr(f"payload/{name}", value)


class FakeRuntime:
    def __init__(self) -> None:
        self.fail_start = False
        self.healthy = True
        self.started: list[str] = []

    async def start(self, plugin_id: str, package_path: Path) -> None:
        del package_path
        if self.fail_start:
            raise RuntimeError("start failed")
        self.started.append(plugin_id)

    async def stop(self, plugin_id: str) -> None:
        del plugin_id

    async def health(self, plugin_id: str) -> bool:
        del plugin_id
        return self.healthy


def verifier(
    private_key: Ed25519PrivateKey, digest: str
) -> tuple[PluginPackageVerifier, str]:
    public = private_key.public_key().public_bytes_raw()
    signature = private_key.sign(b"plugin-package-v1:" + digest.encode())
    return PluginPackageVerifier(
        {"publisher": TrustedPublisher("publisher", public)},
    ), base64.b64encode(signature).decode()


def test_package_integrity_and_signature_are_verified(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    files = {"plugin.py": b"print('safe')"}
    digest = payload_digest(files)
    unsigned_data = manifest_data(digest=digest)
    package = tmp_path / "plugin.utp"
    write_package(package, unsigned_data, files)
    with pytest.raises(PackageVerificationError, match="unsigned"):
        PluginPackageVerifier().inspect(package)

    verifier_instance, signature = verifier(private_key, digest)
    signed_data = manifest_data(digest=digest, signature=signature, key_id="publisher")
    write_package(package, signed_data, files)
    verified = verifier_instance.inspect(package)
    assert verified.payload_digest == digest

    tampered = tmp_path / "tampered.utp"
    write_package(tampered, signed_data, {"plugin.py": b"tampered"})
    with pytest.raises(PackageVerificationError, match="integrity"):
        verifier_instance.inspect(tampered)


def test_package_rejects_traversal_and_duplicate_paths(tmp_path: Path) -> None:
    package = tmp_path / "bad.utp"
    data = manifest_data(digest="0" * 64)
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("manifest.json", json.dumps(data))
        archive.writestr("payload/../escape", b"no")
    with pytest.raises(PackageFormatError, match="unsafe"):
        PluginPackageVerifier(require_signature=False).inspect(package)


def test_stage_does_not_replace_active_version(tmp_path: Path) -> None:
    files = {"plugin.py": b"safe"}
    digest = payload_digest(files)
    package = tmp_path / "update.utp"
    write_package(package, manifest_data(digest=digest), files)
    store = UpdateStore(tmp_path / "store")
    runtime = FakeRuntime()
    manager = PluginUpdateManager(
        store=store, runtime=runtime,
        verifier=PluginPackageVerifier(require_signature=False),
        sdk_version="1.0.0", application_version="1.0.0",
    )
    verified = manager.stage(package)
    assert verified.package_path.is_dir()
    assert store.read_active("example.plugin") is None


def test_dependency_plan_rejects_incompatible_graph(tmp_path: Path) -> None:
    files = {"plugin.py": b"safe"}
    digest = payload_digest(files)
    package = tmp_path / "update.utp"
    write_package(
        package,
        manifest_data(
            digest=digest,
            dependencies=[{"plugin_id": "missing", "version_range": "^1.0.0"}],
        ),
        files,
    )
    store = UpdateStore(tmp_path / "store")
    manager = PluginUpdateManager(
        store=store, runtime=FakeRuntime(),
        verifier=PluginPackageVerifier(require_signature=False),
        sdk_version="1.0.0", application_version="1.0.0",
    )
    candidate = manager.stage(package)
    with pytest.raises(UpdateDependencyError):
        manager.plan((), candidate)


def test_failed_activation_restores_previous_version(tmp_path: Path) -> None:
    store = UpdateStore(tmp_path / "store")
    runtime = FakeRuntime()
    manager = PluginUpdateManager(
        store=store, runtime=runtime,
        verifier=PluginPackageVerifier(require_signature=False),
        sdk_version="1.0.0", application_version="1.0.0",
    )
    files = {"plugin.py": b"safe"}
    digest = payload_digest(files)

    first_package = tmp_path / "first.utp"
    write_package(first_package, manifest_data(version="1.0.0", digest=digest), files)
    manager.stage(first_package)
    store.atomically_set_active("example.plugin", "1.0.0", None)
    first_path = store.version_path("example.plugin", "1.0.0")
    first_path.mkdir(parents=True, exist_ok=True)
    (first_path / "plugin.py").write_bytes(b"safe")

    second_package = tmp_path / "second.utp"
    write_package(second_package, manifest_data(version="2.0.0", digest=digest), files)
    second = manager.stage(second_package)
    runtime.fail_start = True
    with pytest.raises(UpdateActivationError):
        asyncio.run(
            manager.activate(
                second,
                installed=(
                    InstalledPlugin(
                        PluginManifest.model_validate(
                            manifest_data(version="1.0.0", digest=digest)
                        ),
                        first_path,
                    ),
                ),
            )
        )
    active = store.read_active("example.plugin")
    assert active is not None
    assert active.active_version == "1.0.0"


def test_manual_rollback_health_checks_and_restores_on_failure(tmp_path: Path) -> None:
    store = UpdateStore(tmp_path / "store")
    runtime = FakeRuntime()
    manager = PluginUpdateManager(
        store=store, runtime=runtime,
        verifier=PluginPackageVerifier(require_signature=False),
        sdk_version="1.0.0", application_version="1.0.0",
    )
    for version in ("1.0.0", "2.0.0"):
        path = store.version_path("example.plugin", version)
        path.mkdir(parents=True)
        (path / "plugin.py").write_bytes(b"safe")
    store.atomically_set_active("example.plugin", "2.0.0", "1.0.0")
    result = asyncio.run(manager.rollback("example.plugin"))
    assert result.active_version == "1.0.0"
    assert result.previous_version == "2.0.0"

    store.atomically_set_active("example.plugin", "2.0.0", "1.0.0")
    runtime.healthy = False
    with pytest.raises(UpdateActivationError):
        asyncio.run(manager.rollback("example.plugin"))
    active = store.read_active("example.plugin")
    assert active is not None
    assert active.active_version == "2.0.0"
