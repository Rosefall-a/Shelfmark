from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from types import SimpleNamespace
from uuid import uuid4

from fastapi import UploadFile

from src.api.routes import plugins
from src.core.auth import hash_password

# Register the relationship target before these focused tests instantiate ORM rows.
from src.database.models import achievement as _achievement  # noqa: F401
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

    async def install_package(
        self,
        package: bytes,
        filename: str,
        *,
        installation_id: str,
        source_metadata=None,
        trust_metadata=None,
    ) -> dict[str, str]:
        self.package = package
        self.filename = filename
        self.installation_id = installation_id
        self.source_metadata = source_metadata
        self.trust_metadata = trust_metadata
        return {"status": "installed"}

    async def start(self, plugin_id: str, user_id: str | None = None) -> None:
        self.started = (plugin_id, user_id)

    async def plugin_health(self, plugin_id: str) -> bool:
        self.health_checked = plugin_id
        return True


def frontend_package_bytes() -> bytes:
    files = {
        "plugin.py": b"def main():\n    pass\n",
        "sdk/plugin_protocol.py": b"API_VERSION = 1\n",
        "frontend/index.html": b"<!doctype html><html><body>playground</body></html>",
    }
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    manifest = {
        "manifest_version": 1,
        "plugin_id": "example.ui-playground",
        "name": "Plugin UI Playground",
        "version": "1.0.0",
        "entrypoint": "plugin:main",
        "sdk_version_range": "^1.0.0",
        "application_version_range": "*",
        "capabilities": [{"name": "notifications.send", "version": 1}],
        "permissions": [
            {
                "capability": {"name": "notifications.send", "version": 1},
                "rationale": "Send page announcements.",
            }
        ],
        "dependencies": [],
        "ui": {"settings": ["filters"], "actions": ["announce-page"], "pages": ["overview"]},
        "storage": {"quota_mb": 1},
        "integrity": {"sha256": digest.hexdigest(), "signature": None, "key_id": None},
        "frontend": {"entry": "frontend/index.html"},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items():
            archive.writestr("payload/" + name, data)
    return output.getvalue()


def dangerous_package_bytes() -> bytes:
    files = {"plugin.py": b"def main():\n    pass\n"}
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    manifest = {
        "manifest_version": 1,
        "plugin_id": "example.dangerous",
        "name": "Dangerous Example",
        "version": "1.0.0",
        "entrypoint": "plugin:main",
        "sdk_version_range": "*",
        "application_version_range": "*",
        "capabilities": [{"name": "api.full", "version": 1}],
        "permissions": [
            {
                "capability": {"name": "api.full", "version": 1},
                "rationale": "Exercise the elevated install boundary.",
            }
        ],
        "dependencies": [],
        "integrity": {"sha256": digest.hexdigest()},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("payload/plugin.py", files["plugin.py"])
    return output.getvalue()


def test_upload_endpoint_verifies_and_forwards_utp(monkeypatch) -> None:
    client = FakeClient()
    payload = package_bytes()
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(
        plugins,
        "_plugin_package_verifier",
        lambda: PluginPackageVerifier(require_signature=True),
    )
    upload = UploadFile(file=io.BytesIO(payload), filename="example-upload.utp")

    class FakeDb:
        def add_all(self, rows):
            self.rows = rows

        async def commit(self):
            pass

        async def rollback(self):
            pass

    try:
        asyncio.run(plugins.install_plugin(upload, admin=object(), db=FakeDb()))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
        assert exc.detail["code"] == "untrusted_plugin"
    else:
        raise AssertionError("untrusted package was installed without confirmation")

    upload = UploadFile(file=io.BytesIO(payload), filename="example-upload.utp")
    result = asyncio.run(
        plugins.install_plugin(upload, allow_untrusted=True, admin=object(), db=FakeDb())
    )

    assert result["plugin_id"] == "example.upload"
    assert result["version"] == "1.0.0"
    assert client.package == payload
    assert client.filename == "example.upload-1.0.0.utp"
    assert result["trust_status"] == "unsigned"
    assert "unsigned" in result["trust_warning"].lower()


def test_upload_endpoint_accepts_ui_playground_frontend_manifest(monkeypatch) -> None:
    client = FakeClient()
    payload = frontend_package_bytes()
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(
        plugins,
        "_plugin_package_verifier",
        lambda: PluginPackageVerifier(require_signature=True),
    )
    upload = UploadFile(
        file=io.BytesIO(payload),
        filename="example.ui-playground-1.0.0.utp",
    )

    class FakeDb:
        def add_all(self, rows):
            self.rows = rows

        async def commit(self):
            pass

        async def rollback(self):
            pass

    db = FakeDb()
    result = asyncio.run(
        plugins.install_plugin(
            upload,
            allow_untrusted=True,
            approved_permissions=["notifications.send:v1"],
            admin=object(),
            db=db,
        )
    )
    assert result["plugin_id"] == "example.ui-playground"
    assert result["trust_status"] == "unsigned"
    assert result["permissions_granted"] == 1
    assert result["permissions_denied"] == 0
    assert {type(row).__name__ for row in db.rows} == {
        "PluginPermissionRequest",
        "PluginPermissionGrant",
        "PluginPermissionAudit",
    }
    assert client.package == payload


def test_upload_preview_is_static_and_lists_requested_permissions(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(
        plugins,
        "_plugin_package_verifier",
        lambda: PluginPackageVerifier(require_signature=True),
    )
    upload = UploadFile(
        file=io.BytesIO(frontend_package_bytes()),
        filename="example.ui-playground-1.0.0.utp",
    )
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/plugins/install/preview",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
        }
    )

    preview = asyncio.run(plugins.preview_plugin_install(request, file=upload, admin=object()))

    assert preview["plugin_id"] == "example.ui-playground"
    assert preview["trust_status"] == "unsigned"
    assert preview["permissions"][0] == {
        "key": "notifications.send:v1",
        "capability": "notifications.send",
        "capability_version": 1,
        "rationale": "Send page announcements.",
        "title": "Notifications / Send",
        "category": "Notifications",
        "parent": "notifications",
        "children": [],
        "risk": "high",
        "highly_privileged": False,
    }
    assert client.package is None


def test_dangerous_unsigned_grant_requires_password_reauthentication(monkeypatch) -> None:
    client = FakeClient()
    payload = dangerous_package_bytes()
    monkeypatch.setattr(plugins, "_client", client)
    admin = SimpleNamespace(
        id=uuid4(),
        password_hash=hash_password("Correct-password!"),
    )

    class FakeDb:
        def add_all(self, rows):
            self.rows = rows

        async def commit(self):
            pass

        async def rollback(self):
            pass

    def attempt(password: str | None, confirm: bool):
        return plugins.install_plugin(
            UploadFile(file=io.BytesIO(payload), filename="dangerous.bin"),
            allow_untrusted=True,
            approved_permissions=["api.full:v1"],
            admin_password=password,
            confirm_dangerous=confirm,
            admin=admin,
            db=FakeDb(),
        )

    try:
        asyncio.run(attempt(None, False))
    except Exception as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "dangerous_permissions_confirmation_required"
    else:
        raise AssertionError("dangerous grant did not require confirmation")

    try:
        asyncio.run(attempt("wrong", True))
    except Exception as exc:
        assert exc.status_code == 401
        assert exc.detail["code"] == "administrator_reauthentication_failed"
    else:
        raise AssertionError("dangerous grant accepted an invalid password")

    result = asyncio.run(attempt("Correct-password!", True))
    assert result["dangerous_permissions_reauthenticated"] == ["api.full:v1"]
    assert client.package == payload


def test_upload_endpoint_accepts_zip_package() -> None:
    upload = UploadFile(file=io.BytesIO(package_bytes()), filename="example.zip")

    class FakeDb:
        def add_all(self, rows):
            self.rows = rows

        async def commit(self):
            pass

        async def rollback(self):
            pass

    client = FakeClient()
    original = plugins._client
    plugins._client = client
    try:
        result = asyncio.run(
            plugins.install_plugin(upload, allow_untrusted=True, admin=object(), db=FakeDb())
        )
    finally:
        plugins._client = original
    assert result["plugin_id"] == "example.upload"
    assert client.filename == "example.upload-1.0.0.utp"


def test_upload_endpoint_accepts_package_with_unusual_filename() -> None:
    upload = UploadFile(file=io.BytesIO(package_bytes()), filename="example.plugin.download")

    class FakeDb:
        def add_all(self, rows):
            self.rows = rows

        async def commit(self):
            pass

        async def rollback(self):
            pass

    client = FakeClient()
    original = plugins._client
    plugins._client = client
    try:
        result = asyncio.run(
            plugins.install_plugin(upload, allow_untrusted=True, admin=object(), db=FakeDb())
        )
    finally:
        plugins._client = original

    assert result["plugin_id"] == "example.upload"
    assert client.filename == "example.upload-1.0.0.utp"


def test_upload_endpoint_rejects_invalid_archive_regardless_of_extension() -> None:
    upload = UploadFile(file=io.BytesIO(b"not a zip archive"), filename="example.utp")

    try:
        asyncio.run(plugins.install_plugin(upload, object()))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("invalid archive was accepted")


def test_upload_endpoint_rejects_oversized_package() -> None:
    upload = UploadFile(file=io.BytesIO(b"x" * (64 * 1024 * 1024 + 1)), filename="large.utp")

    try:
        asyncio.run(plugins.install_plugin(upload, object()))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 413
    else:
        raise AssertionError("oversized upload was accepted")


def test_upload_preview_missing_file_is_a_client_error_not_fastapi_422() -> None:
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/plugins/install/preview",
        "headers": [],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    }
    request = Request(scope)
    try:
        asyncio.run(plugins.preview_plugin_install(request, file=None, admin=object()))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
        assert exc.detail["code"] == "plugin_file_missing"
    else:
        raise AssertionError("missing plugin package was accepted")


def test_remote_preview_uses_downloaded_package(monkeypatch) -> None:
    package = package_bytes()

    async def fake_download(url, *, json_document=False):
        handle = __import__("tempfile").NamedTemporaryFile(delete=False)
        handle.write(package)
        handle.close()
        path = __import__("pathlib").Path(handle.name)
        return path, "example.zip", len(package)

    monkeypatch.setattr(plugins, "_download_remote_file", fake_download)
    result = asyncio.run(
        plugins.preview_plugin_install_url(
            plugins.PluginInstallUrl(url="https://example.com/example.zip"),
            admin=object(),
        )
    )
    assert result["plugin_id"] == "example.upload"
    assert result["source_url"] == "https://example.com/example.zip"


def test_remote_url_validation_rejects_private_destinations() -> None:
    import pytest

    with pytest.raises(Exception) as exc:
        plugins._validate_remote_url("http://127.0.0.1/plugin.utp")
    assert getattr(exc.value, "status_code", None) == 400


def test_catalog_entries_accept_explicit_source(monkeypatch) -> None:
    payload = {
        "version": 1,
        "plugins": [
            {
                "plugin_id": "example.catalog",
                "name": "Catalogue Example",
                "description": "Demo",
                "version": "1.0.0",
                "url": "https://example.com/example.utp",
            }
        ],
    }
    import pathlib

    async def fake_download(url, *, json_document=False):
        assert json_document is True
        handle = __import__("tempfile").NamedTemporaryFile(delete=False)
        handle.write(json.dumps(payload).encode("utf-8"))
        handle.close()
        return pathlib.Path(handle.name), "list.json", len(json.dumps(payload))

    monkeypatch.setattr(plugins, "_download_remote_file", fake_download)
    result = asyncio.run(
        plugins.plugin_catalog(
            source="https://example.com/list.json",
            user=object(),
        )
    )
    assert result[0].plugin_id == "example.catalog"


def test_upload_url_and_catalogue_converge_on_one_commit_path(monkeypatch) -> None:
    committed_sources: list[str] = []

    async def fake_commit(file, **kwargs):
        del file
        committed_sources.append(kwargs["source_metadata"]["type"])
        return {"status": "installed"}

    payload = package_bytes()

    async def fake_download(url, *, json_document=False):
        del url, json_document
        handle = __import__("tempfile").NamedTemporaryFile(delete=False)
        handle.write(payload)
        handle.close()
        return __import__("pathlib").Path(handle.name), "candidate.bin", len(payload)

    monkeypatch.setattr(plugins, "_install_plugin_package", fake_commit)
    monkeypatch.setattr(plugins, "_download_remote_file", fake_download)
    asyncio.run(
        plugins.install_plugin(
            UploadFile(file=io.BytesIO(payload), filename="candidate.bin"),
            admin=object(),
            db=object(),
        )
    )
    asyncio.run(
        plugins.install_plugin_url(
            plugins.PluginInstallUrl(url="https://example.com/candidate.utp"),
            admin=object(),
            db=object(),
        )
    )
    asyncio.run(
        plugins.install_plugin_url(
            plugins.PluginInstallUrl(
                url="https://example.com/candidate.utp",
                source_type="catalogue",
                catalogue_url="https://example.com/list.json",
            ),
            admin=object(),
            db=object(),
        )
    )
    assert committed_sources == ["upload", "url", "catalogue"]
