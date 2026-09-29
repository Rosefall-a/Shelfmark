from __future__ import annotations

import tarfile
from io import BytesIO

import pytest

from storage import PluginStorage, StorageQuotaExceeded, StorageSecurityError


def test_storage_is_namespaced_and_persistent(tmp_path) -> None:
    storage = PluginStorage(tmp_path, "example.plugin", quota_bytes=1024)
    storage.put("data/value", b"hello")
    assert storage.get("data/value") == b"hello"
    assert storage.keys() == ("data/value",)

    reopened = PluginStorage(tmp_path, "example.plugin", quota_bytes=1024)
    assert reopened.get("data/value") == b"hello"
    assert reopened.metadata().plugin_id == "example.plugin"


def test_storage_rejects_escape_keys(tmp_path) -> None:
    storage = PluginStorage(tmp_path, "example.plugin")
    for key in ("../other", "/absolute", "data/../../other"):
        with pytest.raises(StorageSecurityError):
            storage.put(key, b"x")


def test_storage_quota_is_enforced(tmp_path) -> None:
    storage = PluginStorage(tmp_path, "example.plugin", quota_bytes=4)
    storage.put("value", b"1234")
    with pytest.raises(StorageQuotaExceeded):
        storage.put("other", b"x")


def test_storage_versioning_and_uninstall_are_namespace_local(tmp_path) -> None:
    one = PluginStorage(tmp_path, "one", quota_bytes=1024)
    two = PluginStorage(tmp_path, "two", quota_bytes=1024)
    one.set_schema_version(3)
    assert one.metadata().schema_version == 3
    one.uninstall()
    assert not (tmp_path / "one").exists()
    assert (tmp_path / "two").exists()


def test_backup_restore_is_namespace_bound_and_quota_checked(tmp_path) -> None:
    storage = PluginStorage(tmp_path, "example.plugin", quota_bytes=1024)
    storage.put("data/value", b"hello")
    backup = storage.backup()
    storage.put("data/value", b"changed")
    storage.restore(backup)
    assert storage.get("data/value") == b"hello"

    other = PluginStorage(tmp_path, "other", quota_bytes=1024)
    with pytest.raises(StorageSecurityError):
        other.restore(backup)

    small = PluginStorage(tmp_path, "small", quota_bytes=4)
    oversized = BytesIO()
    with tarfile.open(fileobj=oversized, mode="w:gz") as archive:
        metadata = b'{"plugin_id":"small","quota_bytes":4,"schema_version":1}\n'
        metadata_info = tarfile.TarInfo(".storage.json")
        metadata_info.size = len(metadata)
        archive.addfile(metadata_info, BytesIO(metadata))
        value_info = tarfile.TarInfo("data/value")
        value_info.size = 5
        archive.addfile(value_info, BytesIO(b"12345"))
    with pytest.raises(StorageQuotaExceeded):
        small.restore(oversized.getvalue())


def test_backup_rejects_path_traversal(tmp_path) -> None:
    storage = PluginStorage(tmp_path, "example.plugin", quota_bytes=1024)
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        archive.addfile(info, BytesIO(b"x"))
    with pytest.raises(StorageSecurityError):
        storage.restore(buffer.getvalue())
