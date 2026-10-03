"""Plugin lifecycle orchestration for Plugin API v1.

The lifecycle manager owns plugin state, dependency-aware activation, health
tracking, quarantine, safe mode and structured diagnostics. It never imports or
executes plugin code itself; execution is delegated to the isolated runtime
through the RuntimeController protocol.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Awaitable, Mapping, Protocol
from uuid import UUID, uuid4

from .contracts import (
    CompatibilityStatus,
    IntegrityMetadata,
    PluginManifest,
    PluginUiDeclaration,
    StorageRequirements,
    resolve_plugin_dependencies,
)
from .updates import (
    PluginPackageVerifier,
    TrustedPublisher,
    VerifiedPackage,
    canonical_payload_digest,
)


class LifecycleState(StrEnum):
    DISCOVERED = "discovered"
    VALIDATING = "validating"
    INVALID = "invalid"
    INCOMPATIBLE = "incompatible"
    INSTALLED = "installed"
    DISABLED = "disabled"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED_INSTALL = "failed_install"
    FAILED_START = "failed_start"
    FAILED_STOP = "failed_stop"
    UNHEALTHY = "unhealthy"
    QUARANTINED = "quarantined"


class RuntimeUnavailable(RuntimeError):
    """Raised when the isolated runtime cannot accept a lifecycle operation."""


def plugin_contributions_active(plugin: Mapping[str, object]) -> bool:
    """Enablement is a preference; contributions require a live, healthy runtime."""
    return bool(
        plugin.get("enabled") is True
        and plugin.get("compatible") is True
        and plugin.get("status") == LifecycleState.RUNNING
        and plugin.get("health") in {"healthy", "unknown"}
    )


class RuntimeController(Protocol):
    """Execution boundary owned by the isolated plugin runtime."""

    async def start(self, plugin_id: str, package_path: Path) -> None: ...
    async def stop(self, plugin_id: str) -> None: ...
    async def health(self, plugin_id: str) -> bool: ...


class PackageInstaller(Protocol):
    """Installation boundary; package extraction never executes plugin code."""

    async def install(self, package_path: Path, manifest: PluginManifest) -> Path: ...


class PluginStorageCleanup(Protocol):
    """Authoritative owner of a plugin installation namespace."""

    def uninstall(self, plugin_id: str) -> None | Awaitable[None]: ...


class PackageVerifier(Protocol):
    """Integrity boundary for plugin artifacts."""

    def verify(self, package_path: Path, expected_sha256: str) -> bool: ...


class PackageRemover(Protocol):
    """Removal boundary for installed plugin artifacts."""

    async def remove(self, package_path: Path) -> None: ...


class StorageRemover(Protocol):
    """Removal boundary for plugin-owned persistent storage."""

    async def remove(self, plugin_id: str) -> None: ...


class Sha256PackageVerifier:
    """Verify the authoritative v1 package digest for files or directories."""

    def __init__(
        self,
        publishers: Mapping[str, TrustedPublisher] | None = None,
        *,
        require_signature: bool = True,
    ) -> None:
        self.publishers = dict(publishers) if publishers is not None else None
        self.require_signature = require_signature

    def inspect(self, package_path: Path) -> VerifiedPackage:
        """Inspect a signed v1 archive using the host publisher-trust policy."""
        publishers = self.publishers
        if publishers is None:
            from .publisher_trust import load_trusted_publishers

            publishers = load_trusted_publishers()
        return PluginPackageVerifier(
            publishers=publishers,
            require_signature=self.require_signature,
        ).inspect(package_path)

    def verify(self, package_path: Path, expected_sha256: str) -> bool:
        if package_path.is_file():
            try:
                verified = self.inspect(package_path)
            except (OSError, ValueError):
                return False
            return verified.payload_digest.lower() == expected_sha256.lower()

        if not package_path.is_dir():
            return False

        from .updates import canonical_payload_digest

        entries: list[tuple[str, bytes]] = []
        try:
            for path in sorted(p for p in package_path.rglob("*") if p.is_file()):
                relative = path.relative_to(package_path).as_posix()
                if relative == "manifest.json":
                    continue
                entries.append((relative, path.read_bytes()))
        except OSError:
            return False
        return canonical_payload_digest(entries).lower() == expected_sha256.lower()


class NoopPackageInstaller:
    """Development/test installer for already-isolated package directories."""

    async def install(self, package_path: Path, manifest: PluginManifest) -> Path:
        del manifest
        return package_path


@dataclass(frozen=True)
class LifecycleLog:
    """Structured, administrator-safe lifecycle diagnostic."""

    timestamp: datetime
    level: str
    event: str
    plugin_id: str | None
    message: str
    failure_count: int = 0


@dataclass(frozen=True)
class PluginHealth:
    """Current health and failure information for one plugin."""

    state: LifecycleState
    consecutive_failures: int
    last_checked_at: datetime | None
    last_error: str | None


@dataclass
class PluginRecord:
    """Mutable manager state; never exposed directly to plugins."""

    manifest: PluginManifest
    package_path: Path
    state: LifecycleState = LifecycleState.DISCOVERED
    enabled: bool = True
    consecutive_failures: int = 0
    last_checked_at: datetime | None = None
    last_error: str | None = None
    installed_at: datetime | None = None
    started_at: datetime | None = None
    installation_id: UUID = field(default_factory=uuid4)


class PluginLifecycleManager:
    """Coordinate safe plugin lifecycle without making core startup fragile."""

    def __init__(
        self,
        *,
        sdk_version: str,
        application_version: str,
        runtime: RuntimeController,
        installer: PackageInstaller | None = None,
        verifier: PackageVerifier | None = None,
        package_remover: PackageRemover | None = None,
        storage_remover: StorageRemover | None = None,
        quarantine_after: int = 3,
        max_logs: int = 200,
        storage_cleanup: PluginStorageCleanup | None = None,
    ) -> None:
        if quarantine_after < 1:
            raise ValueError("quarantine_after must be positive")
        self.sdk_version = sdk_version
        self.application_version = application_version
        self.runtime = runtime
        self.installer = installer or NoopPackageInstaller()
        self.verifier = verifier or Sha256PackageVerifier()
        self.package_remover = package_remover
        self.storage_remover = storage_remover
        self.quarantine_after = quarantine_after
        self.safe_mode = False
        self._records: dict[str, PluginRecord] = {}
        self._operation_locks: dict[str, asyncio.Lock] = {}
        self._logs: deque[LifecycleLog] = deque(maxlen=max_logs)
        self.storage_cleanup = storage_cleanup

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _log(
        self, level: str, event: str, plugin_id: str | None, message: str, failure_count: int = 0
    ) -> None:
        self._logs.append(
            LifecycleLog(self._now(), level, event, plugin_id, message, failure_count)
        )

    def discover(self, manifest_paths: list[Path]) -> tuple[PluginRecord, ...]:
        """Discover manifests without importing or executing plugin code."""
        discovered: list[PluginRecord] = []
        for manifest_path in sorted(manifest_paths):
            plugin_id: str | None = None
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                plugin_id = str(data.get("plugin_id") or data.get("id") or "") or None
                record = self._validate_manifest(data, manifest_path.parent)
                self._records[record.manifest.plugin_id] = record
                discovered.append(record)
                self._log("info", "discovered", record.manifest.plugin_id, "manifest discovered")
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                if plugin_id and plugin_id in self._records:
                    self._records.pop(plugin_id, None)
                invalid = self._invalid_record(plugin_id, manifest_path, str(exc))
                if plugin_id:
                    self._records[plugin_id] = invalid
                discovered.append(invalid)
                self._log("error", "invalid_manifest", plugin_id, str(exc))
        return tuple(discovered)

    def discover_package(self, package_path: Path) -> PluginRecord:
        """Register a verified v1 archive without importing its payload code."""
        if not isinstance(self.verifier, Sha256PackageVerifier):
            raise RuntimeError("package discovery requires the production package verifier")
        verified = self.verifier.inspect(package_path)
        from .contracts import evaluate_manifest_compatibility

        decision = evaluate_manifest_compatibility(
            verified.manifest, self.sdk_version, self.application_version
        )
        if decision.status == CompatibilityStatus.INVALID:
            raise ValueError(decision.reason)
        state = (
            LifecycleState.INCOMPATIBLE
            if decision.status == CompatibilityStatus.INCOMPATIBLE
            else LifecycleState.DISCOVERED
        )
        record = PluginRecord(manifest=verified.manifest, package_path=package_path, state=state)
        self._records[record.manifest.plugin_id] = record
        self._log(
            "info", "package_discovered", record.manifest.plugin_id, "verified package discovered"
        )
        return record

    def _validate_manifest(self, data: dict, package_path: Path) -> PluginRecord:
        manifest = PluginManifest.model_validate(data)
        from .contracts import evaluate_manifest_compatibility

        decision = evaluate_manifest_compatibility(
            manifest, self.sdk_version, self.application_version
        )
        if decision.status == CompatibilityStatus.INVALID:
            raise ValueError(decision.reason)
        state = (
            LifecycleState.INCOMPATIBLE
            if decision.status == CompatibilityStatus.INCOMPATIBLE
            else LifecycleState.DISCOVERED
        )
        return PluginRecord(manifest=manifest, package_path=package_path, state=state)

    @staticmethod
    def _invalid_record(plugin_id: str | None, manifest_path: Path, error: str) -> PluginRecord:
        fallback_id = plugin_id or f"invalid.{manifest_path.stem}"
        manifest = PluginManifest.model_construct(
            plugin_id=fallback_id,
            name="Invalid plugin",
            version="0.0.0",
            description="",
            entrypoint="invalid:manifest",
            sdk_version_range="*",
            application_version_range="*",
            capabilities=(),
            permissions=(),
            dependencies=(),
            ui=PluginUiDeclaration(),
            storage=StorageRequirements(),
            integrity=IntegrityMetadata(sha256="0" * 64),
        )
        return PluginRecord(
            manifest=manifest,
            package_path=manifest_path.parent,
            state=LifecycleState.INVALID,
            enabled=False,
            last_error=error,
        )

    def records(self) -> tuple[PluginRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def health(self, plugin_id: str) -> PluginHealth:
        record = self._get(plugin_id)
        return PluginHealth(
            record.state, record.consecutive_failures, record.last_checked_at, record.last_error
        )

    def logs(self, plugin_id: str | None = None) -> tuple[LifecycleLog, ...]:
        return tuple(log for log in self._logs if plugin_id is None or log.plugin_id == plugin_id)

    async def install(self, plugin_id: str) -> PluginRecord:
        """Verify and install a discovered compatible plugin package."""
        record = self._get(plugin_id)
        self._require_state(record, LifecycleState.DISCOVERED)
        record.state = LifecycleState.VALIDATING
        if not self.verifier.verify(record.package_path, record.manifest.integrity.sha256):
            record.state = LifecycleState.INCOMPATIBLE
            record.enabled = False
            record.last_error = "plugin package integrity verification failed"
            self._log("error", "integrity_failed", plugin_id, record.last_error)
            return record
        try:
            record.package_path = await self.installer.install(record.package_path, record.manifest)
        except Exception as exc:
            self._record_failure(record, "install_failed", f"plugin installation failed: {exc}")
            if record.state != LifecycleState.QUARANTINED:
                record.state = LifecycleState.FAILED_INSTALL
            return record
        record.state = LifecycleState.INSTALLED
        record.installed_at = self._now()
        record.last_error = None
        self._log("info", "installed", plugin_id, "plugin installed")
        return record

    async def uninstall(self, plugin_id: str) -> None:
        """Stop and fully remove one plugin installation and its owned data."""
        record = self._get(plugin_id)
        if record.state in {
            LifecycleState.RUNNING,
            LifecycleState.STARTING,
            LifecycleState.UNHEALTHY,
        }:
            stopped = await self.stop(plugin_id)
            if stopped.state in {LifecycleState.FAILED_STOP, LifecycleState.QUARANTINED}:
                raise RuntimeError(f"plugin {plugin_id} could not be stopped for uninstall")
        if self.package_remover is not None:
            await self.package_remover.remove(record.package_path)
        if self.storage_remover is not None:
            await self.storage_remover.remove(plugin_id)
            await self.stop(plugin_id)
        if self.storage_cleanup is not None:
            cleanup = self.storage_cleanup.uninstall
            try:
                result = cleanup(plugin_id)
                if result is not None:
                    await result
            except Exception as exc:
                self._log(
                    "error",
                    "storage_cleanup_failed",
                    plugin_id,
                    f"plugin storage cleanup failed: {exc}",
                )
                raise RuntimeError(f"plugin storage cleanup failed: {exc}") from exc
        self._records.pop(plugin_id, None)
        self._log("info", "uninstalled", plugin_id, "plugin and owned data removed")

    def enable(self, plugin_id: str) -> PluginRecord:
        record = self._get(plugin_id)
        if record.state == LifecycleState.QUARANTINED:
            raise RuntimeError("quarantined plugin must be recovered before enabling")
        if record.state in {LifecycleState.INVALID, LifecycleState.INCOMPATIBLE}:
            raise RuntimeError("invalid or incompatible plugin cannot be enabled")
        record.enabled = True
        if record.state == LifecycleState.DISABLED:
            record.state = LifecycleState.STOPPED
        self._log("info", "enabled", plugin_id, "plugin enabled")
        return record

    async def disable(self, plugin_id: str) -> PluginRecord:
        record = self._get(plugin_id)
        if record.state == LifecycleState.QUARANTINED:
            record.enabled = False
            return await self.stop(plugin_id)
        if record.state in {
            LifecycleState.RUNNING,
            LifecycleState.STARTING,
            LifecycleState.UNHEALTHY,
            LifecycleState.FAILED_START,
            LifecycleState.FAILED_STOP,
        }:
            record.enabled = False
            result = await self.stop(plugin_id)
            if result.state == LifecycleState.FAILED_STOP:
                return result
        else:
            record.enabled = False
            if record.state not in {LifecycleState.INVALID, LifecycleState.INCOMPATIBLE}:
                record.state = LifecycleState.DISABLED
        self._log("info", "disabled", plugin_id, "plugin disabled")
        return record

    async def start(self, plugin_id: str) -> PluginRecord:
        """Start one plugin, containing failures so core startup cannot fail."""
        async with self._operation_locks.setdefault(plugin_id, asyncio.Lock()):
            return await self._start(plugin_id)

    async def _start(self, plugin_id: str) -> PluginRecord:
        record = self._get(plugin_id)
        if self.safe_mode or not record.enabled:
            if self.safe_mode:
                self._log("warning", "safe_mode_skip", plugin_id, "plugin safe mode is active")
            return record
        if record.state in {
            LifecycleState.INVALID,
            LifecycleState.INCOMPATIBLE,
            LifecycleState.QUARANTINED,
        }:
            return record
        if record.state not in {
            LifecycleState.INSTALLED,
            LifecycleState.STOPPED,
            LifecycleState.FAILED_START,
        }:
            raise RuntimeError(f"plugin {plugin_id} cannot start from {record.state}")
        for dependency in record.manifest.dependencies:
            dependency_record = self._records.get(dependency.plugin_id)
            if dependency_record is None:
                if dependency.optional:
                    continue
                self._record_failure(
                    record,
                    "dependency_unavailable",
                    f"required dependency {dependency.plugin_id} is missing",
                )
                return record
            if dependency_record.state != LifecycleState.RUNNING and not dependency.optional:
                self._record_failure(
                    record,
                    "dependency_unavailable",
                    f"required dependency {dependency.plugin_id} is not running",
                )
                return record
        record.state = LifecycleState.STARTING
        try:
            await self.runtime.start(plugin_id, record.package_path)
            record.state = LifecycleState.RUNNING
            record.started_at = self._now()
            record.last_error = None
            self._log("info", "started", plugin_id, "plugin is running")
        except Exception as exc:
            self._record_failure(record, "start_failed", f"plugin failed to start: {exc}")
            try:
                await self.runtime.stop(plugin_id)
            except Exception as cleanup_error:
                self._log("error", "start_cleanup_failed", plugin_id, str(cleanup_error))
        return record

    async def stop(self, plugin_id: str) -> PluginRecord:
        """Serialize shutdown with startup so late startup cannot revive workers."""
        async with self._operation_locks.setdefault(plugin_id, asyncio.Lock()):
            return await self._stop(plugin_id)

    async def _stop(self, plugin_id: str) -> PluginRecord:
        record = self._get(plugin_id)
        quarantined = record.state == LifecycleState.QUARANTINED
        record.state = LifecycleState.STOPPING
        try:
            await self.runtime.stop(plugin_id)
        except Exception as exc:
            self._record_failure(record, "stop_failed", f"plugin failed to stop: {exc}")
            if quarantined:
                record.state = LifecycleState.QUARANTINED
                record.enabled = False
            if record.state == LifecycleState.QUARANTINED:
                return record
            return record
        record.state = (
            LifecycleState.QUARANTINED
            if quarantined
            else LifecycleState.STOPPED
            if record.enabled
            else LifecycleState.DISABLED
        )
        self._log("info", "stopped", plugin_id, "plugin stopped")
        return record

    async def restart(self, plugin_id: str) -> PluginRecord:
        await self.stop(plugin_id)
        return await self.start(plugin_id)

    async def start_enabled(self) -> tuple[PluginRecord, ...]:
        """Start all enabled plugins without propagating plugin failures."""
        if self.safe_mode:
            self._log("warning", "safe_mode", None, "plugin safe mode is active")
            return self.records()
        manifests = tuple(
            record.manifest
            for record in self._records.values()
            if record.enabled
            and record.state
            not in {
                LifecycleState.INVALID,
                LifecycleState.INCOMPATIBLE,
                LifecycleState.QUARANTINED,
            }
        )
        try:
            order = resolve_plugin_dependencies(manifests)
        except ValueError as exc:
            self._log("error", "dependency_resolution_failed", None, str(exc))
            return self.records()
        for plugin_id in order:
            try:
                await self.start(plugin_id)
            except Exception as exc:
                self._record_failure(self._records[plugin_id], "startup_contained", str(exc))
        return self.records()

    async def health_check(self, plugin_id: str) -> PluginHealth:
        """Check one plugin and quarantine after repeated failures."""
        async with self._operation_locks.setdefault(plugin_id, asyncio.Lock()):
            return await self._health_check(plugin_id)

    async def _health_check(self, plugin_id: str) -> PluginHealth:
        record = self._get(plugin_id)
        record.last_checked_at = self._now()
        if record.state not in {LifecycleState.RUNNING, LifecycleState.UNHEALTHY}:
            return self.health(plugin_id)
        try:
            healthy = await self.runtime.health(plugin_id)
        except Exception as exc:
            healthy = False
            record.last_error = f"health check failed: {exc}"
        if healthy:
            record.consecutive_failures = 0
            record.last_error = None
            record.state = LifecycleState.RUNNING
            self._log("info", "healthy", plugin_id, "plugin health check passed")
        else:
            record.consecutive_failures += 1
            record.last_error = record.last_error or "plugin reported unhealthy"
            if record.consecutive_failures >= self.quarantine_after:
                record.enabled = False
                record.state = LifecycleState.STOPPING
                try:
                    await self.runtime.stop(plugin_id)
                except Exception as exc:
                    record.state = LifecycleState.QUARANTINED
                    record.last_error = f"plugin quarantine stop failed: {exc}"
                    self._log(
                        "error",
                        "quarantine_stop_failed",
                        plugin_id,
                        record.last_error,
                        record.consecutive_failures,
                    )
                else:
                    record.state = LifecycleState.QUARANTINED
                    self._log(
                        "error",
                        "quarantined",
                        plugin_id,
                        "plugin quarantined and stopped after repeated failures",
                        record.consecutive_failures,
                    )
            else:
                record.state = LifecycleState.UNHEALTHY
                self._log(
                    "error", "unhealthy", plugin_id, record.last_error, record.consecutive_failures
                )
        return self.health(plugin_id)

    async def health_check_all(self) -> tuple[PluginHealth, ...]:
        return tuple([await self.health_check(plugin_id) for plugin_id in sorted(self._records)])

    async def recover(self, plugin_id: str) -> PluginRecord:
        """Clear quarantine after administrator review without changing grants."""
        record = self._get(plugin_id)
        if record.state != LifecycleState.QUARANTINED:
            raise RuntimeError("plugin is not quarantined")
        record.consecutive_failures = 0
        record.last_error = None
        record.state = LifecycleState.STOPPED if record.enabled else LifecycleState.DISABLED
        self._log("warning", "recovered", plugin_id, "administrator cleared quarantine")
        return record

    def set_safe_mode(self, enabled: bool) -> None:
        self.safe_mode = enabled
        self._log(
            "warning" if enabled else "info",
            "safe_mode_changed",
            None,
            "plugin safe mode enabled" if enabled else "plugin safe mode disabled",
        )

    def _record_failure(self, record: PluginRecord, event: str, message: str) -> None:
        record.consecutive_failures += 1
        record.last_error = message
        if record.consecutive_failures >= self.quarantine_after:
            record.state = LifecycleState.QUARANTINED
            record.enabled = False
            self._log(
                "error",
                "quarantined",
                record.manifest.plugin_id,
                "plugin quarantined after repeated failures",
                record.consecutive_failures,
            )
        else:
            if event == "unhealthy":
                record.state = LifecycleState.UNHEALTHY
            elif event == "start_failed":
                record.state = LifecycleState.FAILED_START
            elif event == "stop_failed":
                record.state = LifecycleState.FAILED_STOP
            self._log(
                "error", event, record.manifest.plugin_id, message, record.consecutive_failures
            )

    def _get(self, plugin_id: str) -> PluginRecord:
        try:
            return self._records[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {plugin_id}") from exc

    @staticmethod
    def _require_state(record: PluginRecord, state: LifecycleState) -> None:
        if record.state != state:
            raise RuntimeError(
                f"plugin {record.manifest.plugin_id} must be {state}, got {record.state}"
            )


__all__ = [
    "LifecycleLog",
    "LifecycleState",
    "NoopPackageInstaller",
    "PackageInstaller",
    "PackageRemover",
    "PackageVerifier",
    "StorageRemover",
    "PluginHealth",
    "PluginLifecycleManager",
    "PluginRecord",
    "plugin_contributions_active",
    "RuntimeController",
    "RuntimeUnavailable",
    "Sha256PackageVerifier",
]
