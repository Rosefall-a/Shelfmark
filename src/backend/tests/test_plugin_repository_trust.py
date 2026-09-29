"""Cross-repository package-verification contract tests.

Set PLUGIN_REPOSITORY_PATH to a checkout of unnamed_tracking_app_plugins to
exercise the actual signed artifact, not a host-local fixture.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import zipfile

import pytest

from src.plugin_api.publisher_trust import load_trusted_publishers
from src.plugin_api.updates import PackageVerificationError, PluginPackageVerifier


def _plugin_repository() -> Path:
    configured = os.getenv("PLUGIN_REPOSITORY_PATH")
    if not configured:
        pytest.skip("PLUGIN_REPOSITORY_PATH is required for cross-repository package verification")
    root = Path(configured)
    if not (root / "publishers" / "registry.json").is_file():
        pytest.skip("PLUGIN_REPOSITORY_PATH does not contain the publisher registry")
    return root


def _write_modified_package(source: Path, destination: Path, *, unsigned: bool = False) -> None:
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(destination, "w") as output:
        for info in archive.infolist():
            content = archive.read(info)
            if info.filename == "manifest.json" and unsigned:
                manifest = json.loads(content)
                manifest["integrity"]["signature"] = None
                manifest["integrity"]["key_id"] = None
                content = json.dumps(manifest).encode("utf-8")
            elif info.filename.startswith("payload/") and not info.is_dir() and not unsigned:
                content += b"tampered"
            output.writestr(info, content)


def test_signed_plugin_repo_artifact_is_trusted_and_modified_artifacts_are_blocked(
    tmp_path: Path,
) -> None:
    plugin_repository = _plugin_repository()
    package = next((plugin_repository / "dist").glob("*.utp"))
    verifier = PluginPackageVerifier(
        publishers=load_trusted_publishers(plugin_repository / "publishers" / "registry.json")
    )

    verified = verifier.inspect(package)
    assert verified.manifest.plugin_id.startswith("example.")

    tampered = tmp_path / "tampered.utp"
    _write_modified_package(package, tampered)
    with pytest.raises(PackageVerificationError, match="integrity"):
        verifier.inspect(tampered)

    unsigned = tmp_path / "unsigned.utp"
    _write_modified_package(package, unsigned, unsigned=True)
    with pytest.raises(PackageVerificationError, match="unsigned"):
        verifier.inspect(unsigned)


def test_signed_plugin_repo_artifact_is_forwarded_only_after_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import UploadFile

    from src.api.routes import plugins

    plugin_repository = _plugin_repository()
    package = next((plugin_repository / "dist").glob("*.utp"))
    verifier = PluginPackageVerifier(
        publishers=load_trusted_publishers(plugin_repository / "publishers" / "registry.json")
    )

    class RuntimeClient:
        package_bytes: bytes | None = None

        async def install_package(self, package_bytes: bytes, filename: str) -> dict[str, str]:
            self.package_bytes = package_bytes
            assert filename.endswith(".utp")
            return {"status": "installed"}

    runtime_client = RuntimeClient()
    monkeypatch.setattr(plugins, "_client", runtime_client)
    monkeypatch.setattr(plugins, "_plugin_package_verifier", lambda: verifier)

    source = package.read_bytes()
    upload = UploadFile(file=io.BytesIO(source), filename=package.name)
    result = asyncio.run(plugins.install_plugin(upload, object()))
    assert result["status"] == "installed"
    assert runtime_client.package_bytes == source

    tampered = tmp_path / "tampered.utp"
    _write_modified_package(package, tampered)
    upload = UploadFile(file=io.BytesIO(tampered.read_bytes()), filename=tampered.name)
    with pytest.raises(Exception) as error:
        asyncio.run(plugins.install_plugin(upload, object()))
    assert getattr(error.value, "status_code", None) == 400
    assert runtime_client.package_bytes == source
