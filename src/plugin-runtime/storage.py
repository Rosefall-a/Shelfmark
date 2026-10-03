"""Persistent, namespaced plugin storage.

Storage is intentionally owned by the plugin runtime rather than the core
application database. A PluginStorage instance is permanently bound to one
plugin ID and refuses path traversal, symlinks and quota violations.
"""
from __future__ import annotations
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
from dataclasses import dataclass

_PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_KEY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,254}$")
_METADATA = ".storage.json"
_MAX_KEY_BYTES = 255

class StorageError(ValueError):
    """Base error for plugin storage operations."""

class StorageQuotaExceeded(StorageError):
    """Raised when an operation would exceed the plugin quota."""

class StorageSecurityError(StorageError):
    """Raised when an operation would escape the plugin namespace."""

@dataclass(frozen=True)
class StorageMetadata:
    plugin_id: str
    schema_version: int
    quota_bytes: int

class PluginStorage:
    """Stable byte-oriented storage API for one plugin namespace."""

    def __init__(self, root: Path, plugin_id: str, *, quota_bytes: int = 64 * 1024 * 1024) -> None:
        if not _PLUGIN_ID.fullmatch(plugin_id):
            raise StorageSecurityError("invalid plugin id")
        if quota_bytes < 1:
            raise StorageError("storage quota must be positive")
        self.root = root / plugin_id
        self.plugin_id = plugin_id
        self.quota_bytes = quota_bytes
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._metadata_path = self.root / _METADATA
        if self._metadata_path.exists():
            metadata = self._read_metadata()
            if metadata.plugin_id != plugin_id:
                raise StorageSecurityError("storage namespace identity mismatch")
            if metadata.quota_bytes != quota_bytes:
                raise StorageError("storage quota differs from the persisted namespace quota")
        else:
            self._write_metadata(schema_version=1)

    def _read_metadata(self) -> StorageMetadata:
        try:
            data = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            return StorageMetadata(
                plugin_id=str(data["plugin_id"]),
                schema_version=int(data["schema_version"]),
                quota_bytes=int(data["quota_bytes"]),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StorageError("plugin storage metadata is invalid") from exc

    def _write_metadata(self, *, schema_version: int) -> None:
        if schema_version < 1:
            raise StorageError("storage schema version must be positive")
        temporary = self._metadata_path.with_suffix(".tmp")
        payload = json.dumps(
            {"plugin_id": self.plugin_id, "schema_version": schema_version, "quota_bytes": self.quota_bytes},
            sort_keys=True,
        )
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, self._metadata_path)

    def metadata(self) -> StorageMetadata:
        return self._read_metadata()

    def set_schema_version(self, version: int) -> None:
        self._write_metadata(schema_version=version)

    def _path(self, key: str) -> Path:
        if not key or len(key.encode("utf-8")) > _MAX_KEY_BYTES or not _KEY.fullmatch(key):
            raise StorageSecurityError("invalid storage key")
        relative = PurePosixPath(key)
        if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
            raise StorageSecurityError("storage key escapes the plugin namespace")
        path = self.root.joinpath(*relative.parts)
        try:
            path.resolve(strict=False).relative_to(self.root.resolve())
        except ValueError as exc:
            raise StorageSecurityError("storage key escapes the plugin namespace") from exc
        return path

    def _usage(self) -> int:
        total = 0
        for path in self.root.rglob("*"):
            if path == self._metadata_path:
                continue
            if path.is_symlink():
                raise StorageSecurityError("symlinks are not permitted in plugin storage")
            if path.is_file():
                total += path.stat().st_size
        return total

    def _ensure_quota(self, additional: int) -> None:
        if additional >= 0 and self._usage() + additional > self.quota_bytes:
            raise StorageQuotaExceeded("plugin storage quota exceeded")

    def put(self, key: str, value: bytes) -> None:
        path = self._path(key)
        if path.exists() and path.is_symlink():
            raise StorageSecurityError("symlinks are not permitted in plugin storage")
        previous = path.stat().st_size if path.is_file() else 0
        self._ensure_quota(max(0, len(value) - previous))
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(value)
        temporary.chmod(0o600)
        os.replace(temporary, path)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise StorageSecurityError("invalid storage object")
        return path.read_bytes()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        if path.is_symlink() or not path.is_file():
            raise StorageSecurityError("invalid storage object")
        path.unlink()
        return True

    def keys(self, prefix: str = "") -> tuple[str, ...]:
        values: list[str] = []
        for path in self.root.rglob("*"):
            if path == self._metadata_path or not path.is_file():
                continue
            if path.is_symlink():
                raise StorageSecurityError("symlinks are not permitted in plugin storage")
            key = path.relative_to(self.root).as_posix()
            if not prefix or key.startswith(prefix):
                values.append(key)
        return tuple(sorted(values))

    def backup(self) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for path in sorted(self.root.rglob("*")):
                if path.is_symlink():
                    raise StorageSecurityError("symlinks are not permitted in plugin storage")
                archive.add(path, arcname=path.relative_to(self.root).as_posix(), recursive=False)
        return buffer.getvalue()

    def restore(self, archive_data: bytes) -> None:
        staging = self.root.parent / f".{self.plugin_id}.restore"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as archive:
                members = archive.getmembers()
                for member in members:
                    relative = PurePosixPath(member.name)
                    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                        raise StorageSecurityError("invalid backup path")
                    if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                        raise StorageSecurityError("backup contains an unsupported filesystem entry")
                    target = staging.joinpath(*relative.parts)
                    try:
                        target.resolve(strict=False).relative_to(staging.resolve())
                    except ValueError as exc:
                        raise StorageSecurityError("backup path escapes plugin namespace") from exc
                archive.extractall(staging)
            metadata_path = staging / _METADATA
            if not metadata_path.is_file():
                raise StorageError("backup is missing storage metadata")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("plugin_id") != self.plugin_id:
                raise StorageSecurityError("backup belongs to another plugin")
            if int(metadata.get("quota_bytes", 0)) != self.quota_bytes:
                raise StorageError("backup quota does not match the installed plugin")
            usage = sum(
                path.stat().st_size for path in staging.rglob("*")
                if path.is_file() and path.name != _METADATA
            )
            if usage > self.quota_bytes:
                raise StorageQuotaExceeded("backup exceeds plugin storage quota")
            replacement = self.root.parent / f".{self.plugin_id}.replacement"
            if replacement.exists():
                shutil.rmtree(replacement)
            os.replace(staging, replacement)
            if self.root.exists():
                shutil.rmtree(self.root)
            os.replace(replacement, self.root)
        except (tarfile.TarError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, StorageError):
                raise
            raise StorageError("plugin storage restore failed") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def uninstall(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
