from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile

from fastapi import UploadFile

from src.api.routes import plugins
from src.plugin_api.updates import PluginPackageVerifier


def package_bytes() -> bytes:
    files = {"plugin.py": b"def main():\n    pass\n"}
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    manifest = {
        "manifest_version": 1,
        "plugin_id": "example.upload",
        "name": "Upload Example",
        "version": "1.0.0",
        "entrypoint": "plugin:main",
        "sdk_version_range": "*",
        "application_version_range": "*",
        "capabilities": [],
        "permissions": [],
        "dependencies": [],
        "integrity": {"sha256": digest.hexdigest()},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("payload/plugin.py", files["plugin.py"])
    return output.getvalue()


class FakeClient:
    def __init__(self) -> None:
        self.package: bytes | None = None
        self.filename = ""

    async def install_package(self, package: bytes, filename: str) -> dict[str, str]:
        self.package = package
        self.filename = filename
        return {"status": "installed"}


def test_upload_endpoint_verifies_and_forwards_utp(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(
        plugins,
        "_plugin_package_verifier",
        lambda: PluginPackageVerifier(require_signature=False),
    )
    upload = UploadFile(file=io.BytesIO(package_bytes()), filename="example-upload.utp")

    class FakeDb:
        def add_all(self, rows): self.rows = rows
        async def commit(self): pass
        async def rollback(self): pass

    try:
        asyncio.run(plugins.install_plugin(upload, object(), FakeDb()))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
        assert exc.detail["code"] == "untrusted_plugin"
    else:
        raise AssertionError("untrusted package was installed without confirmation")

    upload = UploadFile(file=io.BytesIO(package_bytes()), filename="example-upload.utp")
    result = asyncio.run(plugins.install_plugin(upload, allow_untrusted=True, admin=object(), db=FakeDb()))

    assert result["plugin_id"] == "example.upload"
    assert result["version"] == "1.0.0"
    assert client.package == package_bytes()
    assert client.filename == "example-upload.utp"
    assert result["trust_status"] == "untrusted"
    assert "Untrusted signing key" in result["trust_warning"]


def test_upload_endpoint_rejects_non_utp() -> None:
    upload = UploadFile(file=io.BytesIO(package_bytes()), filename="example.zip")

    try:
        asyncio.run(plugins.install_plugin(upload, object()))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("non-.utp upload was accepted")


def test_upload_endpoint_rejects_oversized_package() -> None:
    upload = UploadFile(file=io.BytesIO(b"x" * (64 * 1024 * 1024 + 1)), filename="large.utp")

    try:
        asyncio.run(plugins.install_plugin(upload, object()))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 413
    else:
        raise AssertionError("oversized upload was accepted")
