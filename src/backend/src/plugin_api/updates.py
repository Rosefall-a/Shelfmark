"""Secure staged plugin package updates, activation and rollback.

The update manager is deliberately independent of plugin execution. Packages are
validated as data, staged in versioned directories, and switched through an
atomic active-version pointer. Runtime execution is delegated to the lifecycle
runtime boundary.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Protocol
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .contracts import CompatibilityStatus, PluginManifest, parse_semver, resolve_plugin_dependencies


def canonical_payload_digest(entries: list[tuple[str, bytes]]) -> str:
    """Return the Plugin Package v1 canonical payload digest."""
    digest = hashlib.sha256()
    for name, data in sorted(entries):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


class PackageFormatError(ValueError):
    """Raised when a plugin package does not follow the v1 package format."""


class PackageVerificationError(ValueError):
    """Raised when package integrity or publisher verification fails."""


class UpdateActivationError(RuntimeError):
    """Raised when a staged update cannot be activated safely."""


class UpdateDependencyError(ValueError):
    """Raised when an update would create an invalid dependency graph."""


class UpdateRuntime(Protocol):
    """Runtime boundary used for health-tested activation."""

    async def start(self, plugin_id: str, package_path: Path) -> None: ...
    async def stop(self, plugin_id: str) -> None: ...
    async def health(self, plugin_id: str) -> bool: ...


@dataclass(frozen=True)
class TrustedPublisher:
    """Trusted Ed25519 publisher key."""

    key_id: str
    public_key: bytes

    def verifier(self) -> Ed25519PublicKey:
        try:
            return Ed25519PublicKey.from_public_bytes(self.public_key)
        except ValueError as exc:
            raise PackageVerificationError("invalid trusted publisher public key") from exc


@dataclass(frozen=True)
class VerifiedPackage:
    """Verified package metadata and extracted payload location."""

    manifest: PluginManifest
    package_path: Path
    payload_digest: str


@dataclass(frozen=True)
class InstalledPlugin:
    """Installed version metadata used for dependency planning."""

    manifest: PluginManifest
    version_path: Path


@dataclass(frozen=True)
class UpdatePlan:
    """Dependency-safe update plan in activation order."""

    order: tuple[str, ...]
    candidate: PluginManifest


@dataclass(frozen=True)
class ActiveVersion:
    """Atomic active/previous version pointer."""

    active_version: str
    previous_version: str | None = None


class PluginPackageVerifier:
    """Verify ZIP package structure, integrity and optional publisher signature.

    Package format v1:
      manifest.json
      payload/<plugin files...>

    The manifest's integrity.sha256 is the SHA-256 of a canonical stream of
    payload paths and bytes, excluding manifest.json. A signature, when present,
    is an Ed25519 signature over plugin-package-v1:<sha256> and must name a
    trusted publisher key.
    """

    MANIFEST = "manifest.json"
    PAYLOAD_PREFIX = "payload/"
    SIGNING_PREFIX = b"plugin-package-v1:"

    def __init__(
        self,
        publishers: dict[str, TrustedPublisher] | None = None,
        *,
        require_signature: bool = True,
        max_package_bytes: int = 64 * 1024 * 1024,
        max_entries: int = 1000,
        max_file_bytes: int = 16 * 1024 * 1024,
        max_uncompressed_bytes: int = 64 * 1024 * 1024,
        max_compression_ratio: float = 100.0,
    ) -> None:
        if min(max_package_bytes, max_entries, max_file_bytes, max_uncompressed_bytes) < 1:
            raise ValueError("package limits must be positive")
        if max_compression_ratio < 1:
            raise ValueError("max_compression_ratio must be at least 1")
        self.publishers = publishers or {}
        self.require_signature = require_signature
        self.max_package_bytes = max_package_bytes
        self.max_entries = max_entries
        self.max_file_bytes = max_file_bytes
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_compression_ratio = max_compression_ratio

    @staticmethod
    def _validate_member(name: str) -> None:
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise PackageFormatError("package contains an unsafe path")
        if "\\" in name:
            raise PackageFormatError("package paths must use POSIX separators")

    @classmethod
    def _payload_digest(cls, entries: list[tuple[str, bytes]]) -> str:
        return canonical_payload_digest(entries)

    def _read_bounded(self, archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
        data = bytearray()
        with archive.open(info) as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > self.max_file_bytes:
                    raise PackageFormatError("plugin payload file exceeds maximum size")
        return bytes(data)

    def inspect(self, package_path: Path) -> VerifiedPackage:
        if not package_path.is_file():
            raise PackageFormatError("plugin package must be a file")
        try:
            if package_path.stat().st_size > self.max_package_bytes:
                raise PackageFormatError("plugin package exceeds maximum compressed size")
            with zipfile.ZipFile(package_path) as archive:
                infos = archive.infolist()
                if len(infos) > self.max_entries:
                    raise PackageFormatError("plugin package exceeds maximum entry count")
                total_uncompressed = 0
                names: set[str] = set()
                payload: list[tuple[str, bytes]] = []
                manifest_data: bytes | None = None
                for info in infos:
                    self._validate_member(info.filename)
                    if info.file_size > self.max_file_bytes:
                        raise PackageFormatError("plugin payload file exceeds maximum size")
                    total_uncompressed += info.file_size
                    if total_uncompressed > self.max_uncompressed_bytes:
                        raise PackageFormatError("plugin package exceeds maximum uncompressed size")
                    if info.compress_size and info.file_size / info.compress_size > self.max_compression_ratio:
                        raise PackageFormatError("plugin package exceeds maximum compression ratio")
                    if info.filename in names:
                        raise PackageFormatError("package contains duplicate paths")
                    names.add(info.filename)
                    if info.is_dir():
                        if info.filename != self.PAYLOAD_PREFIX and not info.filename.startswith(
                            self.PAYLOAD_PREFIX
                        ):
                            raise PackageFormatError("package contains an unsupported directory")
                        continue
                    if info.filename == self.MANIFEST:
                        manifest_data = archive.read(info)
                    elif info.filename.startswith(self.PAYLOAD_PREFIX):
                        relative = info.filename[len(self.PAYLOAD_PREFIX):]
                        if not relative:
                            raise PackageFormatError("payload entry must have a filename")
                        payload.append((relative, self._read_bounded(archive, info)))
                    else:
                        raise PackageFormatError("package contains an unexpected file")
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise PackageFormatError("invalid plugin package archive") from exc

        if manifest_data is None:
            raise PackageFormatError("package is missing manifest.json")
        try:
            manifest = PluginManifest.model_validate_json(manifest_data)
        except ValueError as exc:
            raise PackageFormatError("package manifest is invalid") from exc

        digest = self._payload_digest(payload)
        if digest.lower() != manifest.integrity.sha256.lower():
            raise PackageVerificationError("plugin package integrity verification failed")

        signature = manifest.integrity.signature
        if signature is None:
            if self.require_signature:
                raise PackageVerificationError("plugin package is unsigned")
        else:
            if not manifest.integrity.key_id:
                raise PackageVerificationError("signed package is missing integrity.key_id")
            publisher = self.publishers.get(manifest.integrity.key_id)
            if publisher is None:
                raise PackageVerificationError("plugin package publisher is not trusted")
            try:
                signature_bytes = base64.b64decode(signature, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise PackageVerificationError("plugin package signature is not valid base64") from exc
            try:
                publisher.verifier().verify(
                    signature_bytes,
                    self.SIGNING_PREFIX + digest.encode("ascii"),
                )
            except InvalidSignature as exc:
                raise PackageVerificationError("plugin package signature verification failed") from exc

        return VerifiedPackage(manifest=manifest, package_path=package_path, payload_digest=digest)

    def extract(self, verified: VerifiedPackage, destination: Path) -> Path:
        if destination.exists():
            raise PackageFormatError("plugin extraction destination already exists")
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        try:
            with zipfile.ZipFile(verified.package_path) as archive:
                for info in archive.infolist():
                    if info.is_dir() or not info.filename.startswith(self.PAYLOAD_PREFIX):
                        continue
                    relative = PurePosixPath(info.filename[len(self.PAYLOAD_PREFIX):])
                    target = destination.joinpath(*relative.parts)
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o700)
        except (OSError, zipfile.BadZipFile) as exc:
            shutil.rmtree(destination, ignore_errors=True)
            raise PackageFormatError("failed to extract plugin package") from exc
        return destination


class UpdateStore:
    """Versioned plugin store with an atomically replaced active pointer."""

    POINTER = "active.json"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _plugin_root(self, plugin_id: str) -> Path:
        if not plugin_id or not re.fullmatch(r"^[a-z0-9][a-z0-9._-]*$", plugin_id):
            raise UpdateActivationError("invalid plugin ID for update store")
        path = self.root / plugin_id
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path

    def version_path(self, plugin_id: str, version: str) -> Path:
        try:
            parse_semver(version)
        except ValueError as exc:
            raise UpdateActivationError("invalid semantic version for update store") from exc
        return self._plugin_root(plugin_id) / "versions" / version

    def read_active(self, plugin_id: str) -> ActiveVersion | None:
        pointer = self._plugin_root(plugin_id) / self.POINTER
        if not pointer.is_file():
            return None
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
            active_version = str(data["active_version"])
            previous_version = (
                str(data["previous_version"])
                if data.get("previous_version") is not None
                else None
            )
            parse_semver(active_version)
            if previous_version is not None:
                parse_semver(previous_version)
            return ActiveVersion(active_version=active_version, previous_version=previous_version)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise UpdateActivationError("active plugin version pointer is corrupt") from exc

    def remove_active(self, plugin_id: str) -> None:
        """Remove the active pointer when no known-good version exists."""
        root = self._plugin_root(plugin_id)
        pointer = root / self.POINTER
        if pointer.is_file():
            pointer.unlink()
            directory_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def atomically_set_active(
        self,
        plugin_id: str,
        active_version: str,
        previous_version: str | None,
    ) -> None:
        root = self._plugin_root(plugin_id)
        pointer = root / self.POINTER
        temporary = root / f".{self.POINTER}.tmp"
        payload = json.dumps(
            {"active_version": active_version, "previous_version": previous_version},
            sort_keys=True,
        ).encode("utf-8")
        temporary.write_bytes(payload)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, pointer)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def versions(self, plugin_id: str) -> tuple[str, ...]:
        versions = self._plugin_root(plugin_id) / "versions"
        if not versions.is_dir():
            return ()
        return tuple(sorted(path.name for path in versions.iterdir() if path.is_dir()))


class PluginUpdateManager:
    """Stage, plan, atomically activate and roll back plugin updates."""

    def __init__(
        self,
        *,
        store: UpdateStore,
        runtime: UpdateRuntime,
        verifier: PluginPackageVerifier,
        sdk_version: str,
        application_version: str,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.verifier = verifier
        self.sdk_version = sdk_version
        self.application_version = application_version
        self._staged: dict[str, VerifiedPackage] = {}

    def stage(self, package_path: Path) -> VerifiedPackage:
        """Verify and extract a package without changing the active version."""
        verified = self.verifier.inspect(package_path)
        from .contracts import evaluate_manifest_compatibility

        decision = evaluate_manifest_compatibility(
            verified.manifest, self.sdk_version, self.application_version
        )
        if decision.status != CompatibilityStatus.COMPATIBLE:
            raise PackageVerificationError(
                f"plugin update is not compatible: {decision.reason}"
            )

        target = self.store.version_path(
            verified.manifest.plugin_id, verified.manifest.version
        )
        if target.exists():
            raise PackageFormatError("plugin version is already staged or installed")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        package_fd, package_name = tempfile.mkstemp(prefix=".package-", dir=target.parent)
        os.close(package_fd)
        package_snapshot = Path(package_name)
        stage_fd, stage_name = tempfile.mkstemp(prefix=".stage-", dir=target.parent)
        os.close(stage_fd)
        staging = Path(stage_name)
        staging.unlink()
        try:
            shutil.copyfile(package_path, package_snapshot)
            snapshot = self.verifier.inspect(package_snapshot)
            if snapshot.manifest != verified.manifest or snapshot.payload_digest != verified.payload_digest:
                raise PackageVerificationError("plugin package changed after verification")
            verified_snapshot = VerifiedPackage(
                manifest=snapshot.manifest,
                package_path=package_snapshot,
                payload_digest=snapshot.payload_digest,
            )
            self.verifier.extract(verified_snapshot, staging)
            (staging / "manifest.json").write_text(
                verified.manifest.model_dump_json(indent=2), encoding="utf-8"
            )
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            package_snapshot.unlink(missing_ok=True)
            raise
        package_snapshot.unlink(missing_ok=True)

        staged = VerifiedPackage(
            manifest=verified.manifest,
            package_path=target,
            payload_digest=verified.payload_digest,
        )
        self._staged[verified.manifest.plugin_id] = staged
        return staged

    def plan(
        self,
        installed: tuple[InstalledPlugin, ...],
        candidate: VerifiedPackage,
    ) -> UpdatePlan:
        """Reject updates that make the complete dependency graph invalid."""
        manifests = {item.manifest.plugin_id: item.manifest for item in installed}
        manifests[candidate.manifest.plugin_id] = candidate.manifest
        try:
            order = resolve_plugin_dependencies(tuple(manifests.values()))
        except ValueError as exc:
            raise UpdateDependencyError(str(exc)) from exc
        return UpdatePlan(order=order, candidate=candidate.manifest)

    async def activate(
        self,
        candidate: VerifiedPackage,
        *,
        installed: tuple[InstalledPlugin, ...],
    ) -> ActiveVersion:
        """Activate a staged candidate and restore the previous version on failure."""
        if candidate.manifest.plugin_id not in self._staged:
            raise UpdateActivationError("update must be staged before activation")
        self.plan(installed, candidate)
        plugin_id = candidate.manifest.plugin_id
        current = self.store.read_active(plugin_id)
        if current is not None and current.active_version == candidate.manifest.version:
            raise UpdateActivationError("candidate is already active")

        candidate_path = self.store.version_path(plugin_id, candidate.manifest.version)
        if not candidate_path.is_dir():
            raise UpdateActivationError("staged package payload is missing")

        old_version = current.active_version if current else None
        old_path = self.store.version_path(plugin_id, old_version) if old_version else None

        if old_version:
            await self.runtime.stop(plugin_id)

        self.store.atomically_set_active(plugin_id, candidate.manifest.version, old_version)
        try:
            await self.runtime.start(plugin_id, candidate_path)
            if not await self.runtime.health(plugin_id):
                raise UpdateActivationError("staged plugin failed its health check")
        except Exception as exc:
            try:
                await self.runtime.stop(plugin_id)
            except Exception:
                pass
            if old_version and old_path and old_path.is_dir():
                previous_version = current.previous_version if current is not None else None
                self.store.atomically_set_active(
                    plugin_id, old_version, previous_version
                )
                try:
                    await self.runtime.start(plugin_id, old_path)
                except Exception as rollback_exc:
                    raise UpdateActivationError(
                        "update failed and previous version could not be restarted"
                    ) from rollback_exc
            else:
                self.store.remove_active(plugin_id)
            if isinstance(exc, UpdateActivationError):
                raise
            raise UpdateActivationError("staged plugin failed to start") from exc

        self._staged.pop(plugin_id, None)
        return ActiveVersion(candidate.manifest.version, old_version)

    async def rollback(self, plugin_id: str) -> ActiveVersion:
        """Switch to the retained previous known-good version and health-check it."""
        current = self.store.read_active(plugin_id)
        if current is None or current.previous_version is None:
            raise UpdateActivationError("no previous known-good version is retained")
        previous = self.store.version_path(plugin_id, current.previous_version)
        if not previous.is_dir():
            raise UpdateActivationError("previous known-good version is missing")

        await self.runtime.stop(plugin_id)
        self.store.atomically_set_active(
            plugin_id, current.previous_version, current.active_version
        )
        try:
            await self.runtime.start(plugin_id, previous)
            if not await self.runtime.health(plugin_id):
                raise UpdateActivationError("rollback target failed its health check")
        except Exception as exc:
            try:
                await self.runtime.stop(plugin_id)
            except Exception:
                pass
            self.store.atomically_set_active(
                plugin_id, current.active_version, current.previous_version
            )
            recovery_path = self.store.version_path(plugin_id, current.active_version)
            try:
                await self.runtime.start(plugin_id, recovery_path)
                if not await self.runtime.health(plugin_id):
                    raise UpdateActivationError("former active version failed recovery health check")
            except Exception as recovery_exc:
                raise UpdateActivationError(
                    "rollback target failed and former active version could not be recovered"
                ) from recovery_exc
            raise UpdateActivationError("rollback target failed; former active version was recovered") from exc
        return ActiveVersion(current.previous_version, current.active_version)


__all__ = [
    "ActiveVersion", "InstalledPlugin", "PackageFormatError",
    "PackageVerificationError", "PluginPackageVerifier", "PluginUpdateManager",
    "TrustedPublisher", "UpdateActivationError", "UpdateDependencyError",
    "UpdatePlan", "UpdateRuntime", "UpdateStore", "VerifiedPackage",
]
