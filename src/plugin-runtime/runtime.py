"""Isolated Plugin Runtime service.

The runtime is the only component that loads plugin code. The host talks to
this service over an authenticated container-network boundary.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import queue
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from storage import PluginStorage

try:
    import resource
except ImportError:  # pragma: no cover - Windows development/test fallback
    resource = None  # type: ignore[assignment]

_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ENTRYPOINT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*(?::[A-Za-z_][A-Za-z0-9_]*)?$")
_RESERVED_ENV = {
    "DATABASE_URL",
    "SECRET_KEY",
    "PRIMARY_USER_PASSWORD",
    "POSTGRES_PASSWORD",
    "DOCKER_HOST",
    "PLUGIN_GATEWAY_BOOTSTRAP_TOKEN",
    "PLUGIN_GATEWAY_SESSION_TOKEN",
}
_SENSITIVE_VALUE = re.compile(
    r"(?i)((?:authorization|password|secret|token|webhook)[\s\"']*[:=][\s\"']*)([^\s,\"']+)"
)
_WEBHOOK_URL = re.compile(r"https?://[^\s/]+/(?:api/)?webhooks?/[^\s]+", re.IGNORECASE)
_DIAGNOSTIC_LEVELS = {"debug", "info", "warning", "error"}
_MAX_PACKAGE_BYTES = 64 * 1024 * 1024
_MAX_PACKAGE_ENTRIES = 1000
_MAX_PACKAGE_FILE_BYTES = 16 * 1024 * 1024
_MAX_PACKAGE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_PACKAGE_COMPRESSION_RATIO = 100.0
_BACKEND_ROUTE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_BACKEND_ROUTE_SEGMENT = re.compile(r"^(?:[a-z0-9][a-z0-9._-]*|\{[a-z_][a-z0-9_]*\})$")
_BACKEND_ROUTE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_RESERVED_PLUGIN_ROUTE_ROOTS = {
    "actions",
    "changelog",
    "capabilities",
    "disable",
    "enable",
    "frontend",
    "logs",
    "native-frontend",
    "permissions",
    "retry",
    "reinstall",
    "rollback",
    "history",
    "start",
    "stop",
    "auto-update",
    "detail",
    "secrets",
    "settings",
    "ui",
    "update",
}


class RuntimePolicyError(ValueError):
    """Raised when a plugin request violates the runtime contract."""


@dataclass(frozen=True)
class ResourceLimits:
    cpu_seconds: int = 60
    address_space_bytes: int = 256 * 1024 * 1024
    open_files: int = 256
    processes: int = 32


@dataclass(frozen=True)
class OutboundNetworkPolicy:
    """Default-deny outbound policy for plugin declarations."""

    allowed_hosts: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] = (443,)
    capability_approved: bool = False

    def validate(self) -> None:
        if not self.allowed_hosts:
            return
        if not self.capability_approved:
            raise RuntimePolicyError(
                "outbound network requires an approved network.outbound capability"
            )
        if any(
            not host or any(char.isspace() for char in host)
            for host in self.allowed_hosts
        ):
            raise RuntimePolicyError("outbound hosts must be non-empty hostnames")
        if any(port < 1 or port > 65535 for port in self.allowed_ports):
            raise RuntimePolicyError("outbound ports must be between 1 and 65535")


@dataclass(frozen=True)
class PluginSpec:
    plugin_id: str
    command: tuple[str, ...]
    environment: Mapping[str, str] = field(default_factory=dict)
    resources: ResourceLimits = field(default_factory=ResourceLimits)

    def validate(self) -> None:
        if (
            self.resources.cpu_seconds < 1
            or self.resources.address_space_bytes < 1
            or self.resources.open_files < 1
            or self.resources.processes < 1
        ):
            raise RuntimePolicyError("resource limits must be positive")
        if not _PLUGIN_ID.fullmatch(self.plugin_id):
            raise RuntimePolicyError("invalid plugin id")
        if not self.command or any(not part for part in self.command):
            raise RuntimePolicyError("plugin command must not be empty")
        if any(name in _RESERVED_ENV for name in self.environment):
            raise RuntimePolicyError("plugin cannot receive core or gateway secrets")


class PluginSupervisor:
    def __init__(
        self,
        root: Path = Path("/tmp/plugins"),
        storage_root: Path = Path("/var/lib/unnamed-tracking/plugins/.storage"),
        gateway_url: str | None = None,
        gateway_token: str | None = None,
    ) -> None:
        self.root = root
        self.storage_root = storage_root
        self.gateway_url = (gateway_url or os.getenv("PLUGIN_GATEWAY_URL", "")).rstrip(
            "/"
        )
        self.gateway_token = gateway_token or os.getenv("PLUGIN_RUNTIME_TOKEN", "")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._action_processes: dict[str, set[subprocess.Popen[bytes]]] = {}
        self.execution_allowed: Callable[[str, str], bool] | None = None
        self._last_exit_codes: dict[str, int | None] = {}
        self._logs: dict[str, deque[dict[str, Any]]] = {}
        self._diagnostic_sequence = 0
        self._user_ids: dict[str, str | None] = {}
        self._installation_ids: dict[str, str] = {}
        self._storage_quotas: dict[str, int] = {}
        self._package_paths: dict[str, Path] = {}
        self._package_manifests: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.isolation: dict[str, Any] = {
            "bubblewrap_available": None,
            "sandbox_available": False,
            "mechanism": "unprobed",
            "reduced_isolation_allowed": self._nonbubble_enabled(),
        }

    def probe_isolation(self) -> dict[str, Any]:
        """Test namespaces on this host, rather than trusting an installed binary."""
        error = None
        try:
            result = subprocess.run(
                ["bwrap", "--unshare-all", "--ro-bind", "/", "/", "--", "/bin/true"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            available = result.returncode == 0
            if not available:
                error = self._redact(result.stderr.decode(errors="replace"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            available = False
            error = self._redact(str(exc))
        reduced = self._nonbubble_enabled()
        self.isolation = {
            "bubblewrap_available": available,
            "sandbox_available": available and not reduced,
            "mechanism": "bubblewrap" if available and not reduced else "process",
            "reduced_isolation_allowed": reduced,
            "last_error": error,
        }
        return dict(self.isolation)

    @staticmethod
    def _redact(value: str) -> str:
        value = _WEBHOOK_URL.sub("[REDACTED_WEBHOOK]", value)
        return _SENSITIVE_VALUE.sub(r"\1[REDACTED]", value)[:4000]

    @classmethod
    def _safe_metadata(cls, metadata: Mapping[str, Any] | None) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in (metadata or {}).items():
            if any(
                marker in key.lower()
                for marker in ("token", "secret", "password", "webhook")
            ):
                safe[key] = "[REDACTED]"
            elif isinstance(value, (str, int, float, bool)) or value is None:
                safe[key] = cls._redact(value) if isinstance(value, str) else value
        return safe

    def _log(
        self,
        plugin_id: str,
        message: str,
        *,
        level: str = "info",
        event: str = "plugin.message",
        source: str = "runtime",
        correlation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        normalized_level = level if level in _DIAGNOSTIC_LEVELS else "info"
        with self._lock:
            self._diagnostic_sequence += 1
            self._logs.setdefault(plugin_id, deque(maxlen=200)).append(
                {
                    "sequence": self._diagnostic_sequence,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": normalized_level,
                    "event": event,
                    "message": self._redact(message),
                    "source": source,
                    "plugin_id": plugin_id,
                    "correlation_id": correlation_id,
                    "metadata": self._safe_metadata(metadata),
                }
            )

    def logs(self, plugin_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._logs.get(plugin_id, ()))

    def exit_code(self, plugin_id: str) -> int | None:
        with self._lock:
            return self._last_exit_codes.get(plugin_id)

    def _serve_stdout(self, plugin_id: str, process: subprocess.Popen[bytes]) -> None:
        stdout = getattr(process, "stdout", None)
        if stdout is None:
            return
        for raw in iter(stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            request: Any = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("gateway request must be an object")
                response = self._handle_gateway_request(plugin_id, request)
            except Exception as exc:
                request_id = (
                    request.get("request_id") if isinstance(request, dict) else None
                )
                self._log(
                    plugin_id,
                    f"Gateway request failed: {exc}",
                    level="error",
                    event="gateway.request_failed",
                    correlation_id=str(request_id) if request_id else None,
                )
                response = {"error": str(exc)}
            try:
                if process.stdin is None:
                    break
                process.stdin.write(
                    (json.dumps(response, separators=(",", ":")) + "\n").encode()
                )
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                break

    def _serve_stderr(self, plugin_id: str, process: subprocess.Popen[bytes]) -> None:
        stderr = getattr(process, "stderr", None)
        if stderr is None:
            return
        for raw in iter(stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                self._log(
                    plugin_id,
                    line,
                    level="warning",
                    event="plugin.stderr",
                    source="plugin",
                )

    def _storage(self, plugin_id: str) -> PluginStorage:
        quota = self._storage_quotas.get(plugin_id, 64 * 1024 * 1024)
        return PluginStorage(self.storage_root, plugin_id, quota_bytes=quota)

    def _manifest(self, plugin_id: str) -> dict[str, Any]:
        return self._package_manifests.get(plugin_id, {})

    def _settings(self, plugin_id: str) -> dict[str, Any]:
        package = self._package_paths.get(plugin_id)
        if package is None:
            return {}
        path = self.storage_root.parent / ".configuration" / f"{plugin_id}.json"
        legacy = package / ".settings.json"
        if not path.exists() and legacy.exists():
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(legacy, path)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _handle_gateway_request(
        self,
        plugin_id: str,
        request: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        method = str(request.get("method", ""))
        if self.execution_allowed is not None and not self.execution_allowed(
            plugin_id, method
        ):
            raise RuntimePolicyError("plugin contributions are not active")
        capability = str(request.get("capability", ""))
        payload = request.get("payload", {})
        if not isinstance(payload, dict):
            raise RuntimePolicyError("gateway payload must be an object")
        local_capability = {
            "storage.put": "plugin.storage",
            "storage.get": "plugin.storage",
            "storage.delete": "plugin.storage",
            "storage.keys": "plugin.storage",
            "settings.get": "plugin.settings",
        }.get(method)
        if local_capability is not None:
            # Declarations and caller-selected capabilities cannot authorize
            # runtime-local operations. The host owns the live grant decision.
            self._authorize_capability(plugin_id, local_capability, user_id=user_id)
        if method == "lifecycle.ready":
            self._log(
                plugin_id,
                "Plugin reported ready.",
                event="lifecycle.ready",
                metadata={"payload_keys": ",".join(sorted(payload))},
            )
            return {"payload": {"accepted": True}}
        if method == "settings.get":
            key = str(payload.get("key", ""))
            return {"payload": {"value": self._settings(plugin_id).get(key)}}
        if method == "storage.put":
            self._storage(plugin_id).put(
                str(payload.get("key", "")), str(payload.get("value", "")).encode()
            )
            return {"payload": {"saved": True}}
        if method == "storage.get":
            value = self._storage(plugin_id).get(str(payload.get("key", "")))
            return {"payload": {"value": None if value is None else value.decode()}}
        if method == "storage.delete":
            return {
                "payload": {
                    "deleted": self._storage(plugin_id).delete(
                        str(payload.get("key", ""))
                    )
                }
            }
        if method == "storage.keys":
            return {
                "payload": {
                    "keys": list(
                        self._storage(plugin_id).keys(str(payload.get("prefix", "")))
                    )
                }
            }
        if not self.gateway_url or len(self.gateway_token) < 32:
            raise RuntimePolicyError("plugin gateway is not configured")
        resolved_user_id = user_id or self._user_ids.get(plugin_id)
        if not resolved_user_id:
            raise RuntimePolicyError(
                "plugin has no user context; enable it from the Plugin Manager first"
            )
        installation_id = self._installation_ids.get(plugin_id)
        if not installation_id:
            raise RuntimePolicyError("plugin installation identity is missing")
        body = json.dumps(
            {
                "plugin_id": plugin_id,
                "installation_id": installation_id,
                "request_id": str(uuid4()),
                "user_id": resolved_user_id,
                "method": method,
                "capability": capability,
                "capability_version": request.get("capability_version", 1),
                "payload": payload,
            }
        ).encode()
        req = Request(
            f"{self.gateway_url}/api/plugins/runtime/gateway",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Plugin-Runtime-Token": self.gateway_token,
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
        except Exception as exc:
            raise RuntimePolicyError("plugin gateway request failed") from exc
        if not isinstance(data, dict):
            raise RuntimePolicyError("plugin gateway returned an invalid response")
        if data.get("error"):
            raise RuntimePolicyError(str(data["error"]))
        return {"payload": data.get("payload", {})}

    def _authorize_capability(
        self,
        plugin_id: str,
        capability: str,
        *,
        user_id: str | None = None,
        version: int = 1,
    ) -> None:
        response = self._handle_gateway_request(
            plugin_id,
            {
                "method": "capabilities.check",
                "capability": capability,
                "capability_version": version,
                "payload": {},
            },
            user_id=user_id,
        )
        payload = response.get("payload")
        if not isinstance(payload, dict) or payload.get("authorized") is not True:
            raise RuntimePolicyError("host did not authorize the capability")

    @staticmethod
    def _limits(limits: ResourceLimits) -> None:
        if resource is None:
            return
        resource.setrlimit(
            resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds)
        )
        resource.setrlimit(
            resource.RLIMIT_AS, (limits.address_space_bytes, limits.address_space_bytes)
        )
        resource.setrlimit(
            resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files)
        )
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.processes, limits.processes))

    @staticmethod
    def _nonbubble_enabled() -> bool:
        return os.getenv("NONBUBBLE_ENV", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _sandbox_command(
        self, spec: PluginSpec, workdir: Path, package_dir: Path
    ) -> list[str]:
        if self._nonbubble_enabled():
            # Development escape hatch for hosts where bubblewrap is unavailable.
            # The Docker/container boundary and resource limits still apply, but
            # the per-plugin bwrap namespace/filesystem boundary is intentionally
            # disabled.
            return list(spec.command)
        if self.isolation.get("bubblewrap_available") is False:
            raise RuntimePolicyError(
                "Bubblewrap is unavailable. Repair namespace support or explicitly "
                "allow reduced isolation with NONBUBBLE_ENV=true."
            )
        # Create the mask target even before settings have ever been saved.
        # Otherwise a later host write would become visible through /plugin.
        settings_path = package_dir / ".settings.json"
        if settings_path.is_symlink():
            raise RuntimePolicyError("plugin settings path must not be a symlink")
        if not settings_path.exists():
            with settings_path.open("x", encoding="utf-8") as handle:
                handle.write("{}")
            settings_path.chmod(0o600)
        return [
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/etc",
            "/etc",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--ro-bind",
            str(package_dir),
            "/plugin",
            # Mutable settings are accessible only through the granted API.
            "--ro-bind",
            "/dev/null",
            "/plugin/.settings.json",
            "--bind",
            str(workdir),
            "/plugin-work",
            # Persistent storage (including secrets) belongs to the broker.
            "--tmpfs",
            "/plugin-data",
            "--chdir",
            "/plugin",
            "--",
            *spec.command,
        ]

    def start(self, spec: PluginSpec, package_dir: Path) -> subprocess.Popen[bytes]:
        """Launch one validated plugin in its isolated process group."""
        spec.validate()
        workdir = self.root / spec.plugin_id
        with self._lock:
            existing = self._processes.get(spec.plugin_id)
            if existing is not None and existing.poll() is None:
                raise RuntimePolicyError("plugin is already running")
            self._processes.pop(spec.plugin_id, None)
            try:
                workdir.mkdir(mode=0o700, parents=True, exist_ok=False)
            except FileExistsError:
                shutil.rmtree(workdir, ignore_errors=True)
                workdir.mkdir(mode=0o700, parents=True, exist_ok=False)
            except Exception as exc:
                raise RuntimePolicyError(
                    "plugin storage is not writable; ensure /var/lib/unnamed-tracking/plugins is owned by the plugin runtime user"
                ) from exc
            self._storage(spec.plugin_id)
            environment = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/plugin",
                "TMPDIR": "/tmp",
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PLUGIN_DATA_DIR": "/plugin-data",
                **spec.environment,
            }
            try:
                self._package_paths[spec.plugin_id] = package_dir
                try:
                    self._package_manifests[spec.plugin_id] = json.loads(
                        (package_dir / "manifest.json").read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    self._package_manifests[spec.plugin_id] = {}
                process = subprocess.Popen(
                    self._sandbox_command(spec, workdir, package_dir),
                    cwd=package_dir if self._nonbubble_enabled() else workdir,
                    env=environment
                    | {
                        "HOME": str(package_dir)
                        if self._nonbubble_enabled()
                        else "/plugin"
                    },
                    start_new_session=True,
                    # Keep stdin available for the JSON-line plugin protocol.
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=lambda: self._limits(spec.resources),
                )
            except Exception:
                self._package_paths.pop(spec.plugin_id, None)
                self._package_manifests.pop(spec.plugin_id, None)
                shutil.rmtree(workdir, ignore_errors=True)
                raise
            self._processes[spec.plugin_id] = process
            self._last_exit_codes[spec.plugin_id] = None
            self._logs.setdefault(spec.plugin_id, deque(maxlen=200))
            threading.Thread(
                target=self._serve_stdout, args=(spec.plugin_id, process), daemon=True
            ).start()
            threading.Thread(
                target=self._serve_stderr, args=(spec.plugin_id, process), daemon=True
            ).start()
        self._log(
            spec.plugin_id,
            "Plugin process started.",
            event="runtime.started",
            metadata={"pid": process.pid},
        )
        return process

    def execute(
        self,
        spec: PluginSpec,
        package_dir: Path,
        payload: bytes,
        timeout: float = 30.0,
        *,
        user_id: str | None = None,
    ) -> bytes:
        """Run a bounded action while mediating its Plugin API requests."""
        spec.validate()
        if len(payload) > 64 * 1024:
            raise RuntimePolicyError("plugin action payload exceeds 64 KiB")
        workdir = (
            self.root / f"{spec.plugin_id}.action-{os.getpid()}-{threading.get_ident()}"
        )
        workdir.mkdir(mode=0o700, parents=True, exist_ok=False)
        started_at = time.monotonic()
        self._log(spec.plugin_id, "Plugin action started.", event="action.started")
        process: subprocess.Popen[bytes] | None = None
        try:
            self._storage(spec.plugin_id)
            with self._lock:
                if self.execution_allowed is not None and not self.execution_allowed(
                    spec.plugin_id, "action"
                ):
                    raise RuntimePolicyError("plugin contributions are not active")
                process = subprocess.Popen(
                    self._sandbox_command(spec, workdir, package_dir),
                    cwd=package_dir if self._nonbubble_enabled() else workdir,
                    env={
                        "PATH": "/usr/local/bin:/usr/bin:/bin",
                        "HOME": str(package_dir)
                        if self._nonbubble_enabled()
                        else "/plugin",
                        "PLUGIN_DATA_DIR": "/plugin-data",
                        "TMPDIR": "/tmp",
                        "PYTHONUNBUFFERED": "1",
                        "PYTHONDONTWRITEBYTECODE": "1",
                        **spec.environment,
                    },
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    preexec_fn=lambda: self._limits(spec.resources),
                )
                self._action_processes.setdefault(spec.plugin_id, set()).add(process)
            if (
                process.stdin is None
                or process.stdout is None
                or process.stderr is None
            ):
                raise RuntimePolicyError("plugin action pipes are unavailable")

            lines: queue.Queue[tuple[str, bytes | None]] = queue.Queue()

            def read_stream(name: str, stream: Any) -> None:
                for line in iter(stream.readline, b""):
                    lines.put((name, line))
                lines.put((name, None))

            threading.Thread(
                target=read_stream, args=("stdout", process.stdout), daemon=True
            ).start()
            threading.Thread(
                target=read_stream, args=("stderr", process.stderr), daemon=True
            ).start()
            process.stdin.write(payload + b"\n")
            process.stdin.flush()

            deadline = time.monotonic() + timeout
            output: bytes | None = None
            stdout_closed = False
            while time.monotonic() < deadline:
                try:
                    stream_name, line = lines.get(
                        timeout=max(0.01, min(0.25, deadline - time.monotonic()))
                    )
                except queue.Empty:
                    if process.poll() is not None and stdout_closed:
                        break
                    continue
                if line is None:
                    if stream_name == "stdout":
                        stdout_closed = True
                    continue
                if stream_name == "stderr":
                    message = line.decode("utf-8", errors="replace").rstrip()
                    if message:
                        self._log(
                            spec.plugin_id,
                            message,
                            level="warning",
                            event="plugin.stderr",
                            source="plugin",
                        )
                    continue
                try:
                    message = json.loads(line)
                except (UnicodeDecodeError, ValueError) as exc:
                    raise RuntimePolicyError(
                        "plugin action emitted invalid protocol output"
                    ) from exc
                if not isinstance(message, dict):
                    raise RuntimePolicyError(
                        "plugin action protocol output must be an object"
                    )
                if "plugin_action_result" in message:
                    output = json.dumps(message["plugin_action_result"]).encode("utf-8")
                    break
                try:
                    response = (
                        self._handle_gateway_request(spec.plugin_id, message)
                        if user_id is None
                        else self._handle_gateway_request(
                            spec.plugin_id, message, user_id=user_id
                        )
                    )
                except Exception as exc:
                    self._log(
                        spec.plugin_id,
                        f"Gateway request failed: {exc}",
                        level="error",
                        event="gateway.request_failed",
                    )
                    response = {"error": str(exc)}
                process.stdin.write(
                    (json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8")
                )
                process.stdin.flush()

            if output is None:
                if process.poll() is None:
                    process.kill()
                    self._log(
                        spec.plugin_id,
                        "Plugin action timed out.",
                        level="error",
                        event="action.timed_out",
                        metadata={"timeout_seconds": timeout},
                    )
                    raise RuntimePolicyError("plugin action timed out")
                raise RuntimePolicyError("plugin action did not return a result")
            process.stdin.close()
            return_code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if return_code:
                self._log(
                    spec.plugin_id,
                    "Plugin action handler failed.",
                    level="error",
                    event="action.failed",
                    metadata={"return_code": return_code},
                )
                raise RuntimePolicyError("plugin action handler failed")
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                process.kill()
            self._log(
                spec.plugin_id,
                "Plugin action timed out.",
                level="error",
                event="action.timed_out",
                metadata={"timeout_seconds": timeout},
            )
            raise RuntimePolicyError("plugin action timed out") from exc
        finally:
            if process is not None:
                if process.poll() is None or hasattr(os, "killpg"):
                    self._terminate(process, 0.5)
                with self._lock:
                    self._action_processes.get(spec.plugin_id, set()).discard(process)
            shutil.rmtree(workdir, ignore_errors=True)
        assert output is not None
        if len(output) > 64 * 1024:
            raise RuntimePolicyError("plugin action output exceeds 64 KiB")
        self._log(
            spec.plugin_id,
            "Plugin action completed.",
            event="action.completed",
            metadata={"duration_ms": round((time.monotonic() - started_at) * 1000)},
        )
        return output

    def stop(self, plugin_id: str, timeout: float = 5.0) -> None:
        with self._lock:
            process = self._processes.pop(plugin_id, None)
            actions = self._action_processes.pop(plugin_id, set())
        errors: list[Exception] = []
        for action in actions:
            try:
                self._terminate(action, timeout)
            except Exception as exc:
                with self._lock:
                    self._action_processes.setdefault(plugin_id, set()).add(action)
                errors.append(exc)
        if process is None:
            if errors:
                raise RuntimePolicyError("plugin worker cleanup failed") from errors[0]
            return
        self._log(plugin_id, "Stopping plugin process.", event="runtime.stopping")
        try:
            self._terminate(process, timeout)
        except Exception as exc:
            with self._lock:
                self._processes[plugin_id] = process
            errors.append(exc)
        else:
            self._last_exit_codes[plugin_id] = process.returncode
            self._log(
                plugin_id,
                "Plugin process stopped.",
                event="runtime.stopped",
                metadata={"return_code": process.returncode},
            )
            self._package_paths.pop(plugin_id, None)
            self._package_manifests.pop(plugin_id, None)
            workdir = self.root / plugin_id
            if workdir.exists():
                for path in sorted(workdir.rglob("*"), reverse=True):
                    if path.is_file() or path.is_symlink():
                        path.unlink(missing_ok=True)
                    elif path.is_dir():
                        path.rmdir()
                workdir.rmdir()
        if errors:
            raise RuntimePolicyError("plugin worker cleanup failed") from errors[0]

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes], timeout: float) -> None:
        try:
            if hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=timeout)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                if hasattr(os, "killpg"):
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            process.wait()
        finally:
            # A parent can exit before its descendants. Remove the whole group.
            if hasattr(os, "killpg"):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def running(self, plugin_id: str) -> bool:
        exited_code: int | None = None
        with self._lock:
            process = self._processes.get(plugin_id)
            if process is None:
                return False
            if process.poll() is not None:
                self._last_exit_codes[plugin_id] = process.returncode
                exited_code = process.returncode
        if exited_code is not None:
            self._log(
                plugin_id,
                "Plugin process exited unexpectedly.",
                level="error" if exited_code else "warning",
                event="runtime.exited",
                metadata={"return_code": exited_code},
            )
            return False
        return True

    def stop_all(self) -> None:
        errors: list[Exception] = []
        for plugin_id in sorted(set(self._processes) | set(self._action_processes)):
            try:
                self.stop(plugin_id)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimePolicyError("plugin worker cleanup failed") from errors[0]


class PluginRegistry:
    def __init__(self, root: Path, supervisor: PluginSupervisor) -> None:
        self.root = root
        self.supervisor = supervisor
        self.state_path = root / ".runtime-state.json"
        self._state_lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self.supervisor.execution_allowed = self._execution_allowed
        self._installation_lock = self._operation_lock
        self.root.mkdir(mode=0o750, parents=True, exist_ok=True)

    def _state(self) -> dict[str, Any]:
        with self._state_lock:
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        with self._state_lock:
            temporary = self.state_path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(state, sort_keys=True))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.state_path)

    def _transition(self, plugin_id: str, **changes: Any) -> dict[str, Any]:
        with self._state_lock:
            state = self._state()
            previous = state.get(plugin_id)
            record = (
                dict(previous)
                if isinstance(previous, dict)
                else {"enabled": bool(previous)}
            )
            record.update(changes)
            state[plugin_id] = record
            self._save_state(state)
            return record

    def _execution_allowed(self, plugin_id: str, method: str = "action") -> bool:
        state = self._state().get(plugin_id)
        if (
            isinstance(state, dict)
            and state.get("enabled")
            and state.get("status") == "starting"
            and method
            in {
                "lifecycle.ready",
                "settings.get",
                "storage.get",
                "storage.keys",
                "capabilities.check",
            }
        ):
            return True
        return bool(
            isinstance(state, dict)
            and state.get("enabled")
            and state.get("status") == "running"
            and self.supervisor.running(plugin_id)
        )

    def _require_active(self, plugin_id: str) -> None:
        package, _ = self.package(plugin_id)
        item = self._item(package)
        if not item["enabled"] or not item["compatible"] or item["status"] != "running":
            raise RuntimePolicyError(
                "plugin must be enabled and running before contributions can execute"
            )

    def packages(self) -> list[Path]:
        return sorted(
            p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")
        )

    def package(self, plugin_id: str) -> tuple[Path, dict[str, Any]]:
        if not _PLUGIN_ID.fullmatch(plugin_id):
            raise RuntimePolicyError("invalid plugin id")
        package = self.root / plugin_id
        if not package.is_dir():
            raise KeyError(plugin_id)
        manifest_path = package / "manifest.json"
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimePolicyError(f"invalid manifest for {plugin_id}") from exc
        if data.get("plugin_id") != plugin_id:
            raise RuntimePolicyError(
                "manifest plugin_id does not match package directory"
            )
        if not _ENTRYPOINT.fullmatch(str(data.get("entrypoint", ""))):
            raise RuntimePolicyError("manifest has invalid entrypoint")
        return package, data

    @staticmethod
    def _backend_routes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        raw_routes = manifest.get("backend_routes", [])
        if not isinstance(raw_routes, list):
            raise RuntimePolicyError("plugin backend_routes must be a list")
        routes: list[dict[str, Any]] = []
        route_ids: set[str] = set()
        for raw_route in raw_routes:
            if not isinstance(raw_route, dict):
                raise RuntimePolicyError("plugin backend route must be an object")
            route_id = raw_route.get("id")
            scope = raw_route.get("scope", "plugin")
            path = raw_route.get("path")
            methods = raw_route.get("methods", ["GET"])
            handler = raw_route.get("handler")
            authorization = raw_route.get("authorization", "authenticated")
            if not isinstance(route_id, str) or not _BACKEND_ROUTE_ID.fullmatch(
                route_id
            ):
                raise RuntimePolicyError("plugin backend route has an invalid id")
            if route_id in route_ids:
                raise RuntimePolicyError("plugin backend route ids must be unique")
            route_ids.add(route_id)
            if scope not in {"plugin", "host"}:
                raise RuntimePolicyError("plugin backend route has an invalid scope")
            if not isinstance(path, str) or len(path) > 255:
                raise RuntimePolicyError("plugin backend route has an invalid path")
            if scope == "plugin" and path.startswith("/"):
                raise RuntimePolicyError(
                    "namespaced backend route path must be relative"
                )
            if (
                scope == "plugin"
                and path.split("/", 1)[0] in _RESERVED_PLUGIN_ROUTE_ROOTS
            ):
                raise RuntimePolicyError(
                    "namespaced backend route conflicts with plugin management"
                )
            if scope == "host" and not path.startswith("/api/"):
                raise RuntimePolicyError(
                    "host backend route path must start with /api/"
                )
            if scope == "host" and path.startswith("/api/plugins/"):
                raise RuntimePolicyError(
                    "host backend route cannot claim plugin management"
                )
            route_parts = path.removeprefix("/api/").split("/")
            if not route_parts or any(
                not _BACKEND_ROUTE_SEGMENT.fullmatch(part) for part in route_parts
            ):
                raise RuntimePolicyError("plugin backend route path is invalid")
            parameters = [part for part in route_parts if part.startswith("{")]
            if len(parameters) != len(set(parameters)):
                raise RuntimePolicyError(
                    "plugin backend route path contains duplicate parameters"
                )
            if (
                not isinstance(methods, list)
                or not methods
                or len(methods) != len(set(methods))
                or any(method not in _BACKEND_ROUTE_METHODS for method in methods)
            ):
                raise RuntimePolicyError("plugin backend route methods are invalid")
            if not isinstance(handler, str) or not _ENTRYPOINT.fullmatch(handler):
                raise RuntimePolicyError("plugin backend route handler is invalid")
            if authorization not in {"authenticated", "admin"}:
                raise RuntimePolicyError(
                    "plugin backend route authorization is invalid"
                )
            routes.append(
                {
                    "id": route_id,
                    "scope": scope,
                    "path": path,
                    "methods": methods,
                    "handler": handler,
                    "authorization": authorization,
                }
            )
        for index, route in enumerate(routes):
            route_parts = str(route["path"]).strip("/").split("/")
            for other in routes[index + 1 :]:
                if route["scope"] != other["scope"] or not set(
                    route["methods"]
                ).intersection(other["methods"]):
                    continue
                other_parts = str(other["path"]).strip("/").split("/")
                overlaps = len(route_parts) == len(other_parts) and all(
                    left == right or left.startswith("{") or right.startswith("{")
                    for left, right in zip(route_parts, other_parts, strict=True)
                )
                if overlaps:
                    raise RuntimePolicyError("plugin backend routes conflict")
        return routes

    def _validate_host_route_ownership(
        self, plugin_id: str, routes: list[dict[str, Any]]
    ) -> None:
        candidate_routes = [route for route in routes if route["scope"] == "host"]
        for package in self.packages():
            if package.name == plugin_id:
                continue
            _, installed_manifest = self.package(package.name)
            for installed in self._backend_routes(installed_manifest):
                if installed["scope"] != "host":
                    continue
                for candidate in candidate_routes:
                    if not set(installed["methods"]).intersection(candidate["methods"]):
                        continue
                    installed_parts = str(installed["path"]).strip("/").split("/")
                    candidate_parts = str(candidate["path"]).strip("/").split("/")
                    overlaps = len(installed_parts) == len(candidate_parts) and all(
                        left == right or left.startswith("{") or right.startswith("{")
                        for left, right in zip(
                            installed_parts, candidate_parts, strict=True
                        )
                    )
                    if overlaps:
                        raise RuntimePolicyError(
                            f"host backend route conflicts with {package.name}"
                        )

    @staticmethod
    def _payload_files(package: Path) -> list[Path]:
        return sorted(
            p
            for p in package.rglob("*")
            if p.is_file()
            and p.name not in {"manifest.json", ".settings.json"}
            and not p.name.startswith(".runtime-state")
            and "__pycache__" not in p.parts
            and p.suffix not in {".pyc", ".pyo"}
        )

    @classmethod
    def digest(cls, package: Path) -> str:
        """Hash the v1 payload stream, ignoring runtime-generated Python caches."""
        digest = hashlib.sha256()
        for path in cls._payload_files(package):
            digest.update(path.relative_to(package).as_posix().encode())
            digest.update(b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _package_icon(package: Path, manifest: dict[str, Any]) -> str | None:
        for name, content_type in (
            ("icon.svg", "image/svg+xml"),
            ("icon.png", "image/png"),
        ):
            path = package / name
            if (
                path.is_file()
                and not path.is_symlink()
                and path.stat().st_size <= 256 * 1024
            ):
                return f"data:{content_type};base64," + base64.b64encode(
                    path.read_bytes()
                ).decode("ascii")
        icon = manifest.get("icon")
        return icon if isinstance(icon, str) else None

    def _item(self, package: Path) -> dict[str, Any]:
        data = self.package(package.name)[1]
        plugin_id = data["plugin_id"]
        expected = data.get("integrity", {}).get("sha256")
        compatible = (
            bool(expected) and self.digest(package).lower() == str(expected).lower()
        )
        state = self._state()
        raw_state = state.get(plugin_id, False)
        enabled = (
            raw_state.get("enabled", False)
            if isinstance(raw_state, dict)
            else bool(raw_state)
        )
        running = self.supervisor.running(plugin_id)
        status = raw_state.get("status") if isinstance(raw_state, dict) else None
        if status is None:
            status = (
                "running"
                if enabled and running
                else "stopped"
                if enabled
                else "disabled"
            )
        elif status == "running" and not running:
            status = "failed"
        if not enabled and status not in {"stopping", "quarantined", "failed"}:
            status = "disabled"
        if (
            status == "failed"
            and isinstance(raw_state, dict)
            and raw_state.get("status") != "failed"
        ):
            self._transition(plugin_id, status="failed")
            self.supervisor.stop(plugin_id)
        return {
            "plugin_id": plugin_id,
            "name": data.get("name", plugin_id),
            "description": data.get("description", ""),
            "icon": self._package_icon(package, data),
            "tags": data.get("tags", []),
            "version": data.get("version", "0.0.0"),
            "publisher": (
                data.get("integrity", {}).get("key_id")
                if data.get("integrity", {}).get("signature")
                else None
            ),
            "digest": data.get("integrity", {}).get("sha256"),
            "installation_id": raw_state.get("installation_id")
            if isinstance(raw_state, dict)
            else None,
            "compatible": compatible,
            "compatibility_reason": ""
            if compatible
            else "package integrity verification failed",
            "permissions": [
                p.get("capability", {}).get("name") for p in data.get("permissions", [])
            ],
            "permission_declarations": data.get("permissions", []),
            "permission_refs": [
                p.get("capability")
                for p in data.get("permissions", [])
                if isinstance(p.get("capability"), dict)
            ],
            "backend_routes": self._backend_routes(data),
            "dependencies": [
                dependency
                for dependency in data.get("dependencies", [])
                if isinstance(dependency, dict)
            ],
            "source": raw_state.get("source", {"type": "unknown"})
            if isinstance(raw_state, dict)
            else {"type": "unknown"},
            "trust": raw_state.get("trust", {}) if isinstance(raw_state, dict) else {},
            "enabled": enabled,
            "installation_pending": bool(raw_state.get("pending_installation"))
            if isinstance(raw_state, dict)
            else False,
            "health": "healthy"
            if running
            else (
                "unhealthy"
                if self.supervisor.exit_code(plugin_id) not in (None, 0)
                else "unknown"
            ),
            "logs_available": bool(self.supervisor.logs(plugin_id)),
            "last_exit_code": self.supervisor.exit_code(plugin_id),
            "status": status,
            "last_error": raw_state.get("last_error")
            if isinstance(raw_state, dict)
            else None,
            "runtime": dict(self.supervisor.isolation),
            "pending_transaction": (
                {"phase": "prepared", **raw_state["pending_installation"]}
                if isinstance(raw_state, dict) and raw_state.get("pending_installation")
                else {"phase": "activation", **raw_state["pending_activation"]}
                if isinstance(raw_state, dict) and raw_state.get("pending_activation")
                else None
            ),
            "history": raw_state.get("history", [])
            if isinstance(raw_state, dict)
            else [],
        }

    def install_package(
        self,
        package: bytes,
        filename: str,
        *,
        installation_id: str,
        replace: bool = False,
        source_metadata: dict[str, Any] | None = None,
        trust_metadata: dict[str, Any] | None = None,
        operation_id: str | None = None,
        expected_version: str | None = None,
    ) -> dict[str, Any]:
        with self._installation_lock:
            return self._install_package(
                package,
                filename,
                installation_id=installation_id,
                replace=replace,
                source_metadata=source_metadata,
                trust_metadata=trust_metadata,
                operation_id=operation_id,
                expected_version=expected_version,
            )

    def _install_package(
        self,
        package: bytes,
        filename: str,
        *,
        installation_id: str,
        replace: bool = False,
        source_metadata: dict[str, Any] | None = None,
        trust_metadata: dict[str, Any] | None = None,
        operation_id: str | None = None,
        expected_version: str | None = None,
    ) -> dict[str, Any]:
        # The archive contents, not a user-controlled filename, define the format.
        del filename
        if not package:
            raise RuntimePolicyError("plugin package is empty")
        if len(package) > _MAX_PACKAGE_BYTES:
            raise RuntimePolicyError("plugin package exceeds the 64 MiB upload limit")
        try:
            UUID(installation_id)
            if operation_id is not None:
                UUID(operation_id)
        except ValueError as exc:
            raise RuntimePolicyError("plugin installation ID is invalid") from exc

        try:
            archive = zipfile.ZipFile(io.BytesIO(package))
        except (OSError, zipfile.BadZipFile, UnicodeError) as exc:
            raise RuntimePolicyError("invalid plugin package archive") from exc

        try:
            names: set[str] = set()
            manifest_data: bytes | None = None
            payload: list[tuple[str, bytes]] = []

            def read_bounded(info: zipfile.ZipInfo) -> bytes:
                data = bytearray()
                with archive.open(info) as source:
                    while chunk := source.read(1024 * 1024):
                        data.extend(chunk)
                        if len(data) > _MAX_PACKAGE_FILE_BYTES:
                            raise RuntimePolicyError(
                                "plugin package file exceeds maximum size"
                            )
                return bytes(data)

            infos = archive.infolist()
            if len(infos) > _MAX_PACKAGE_ENTRIES:
                raise RuntimePolicyError("plugin package exceeds maximum entry count")
            total_uncompressed = 0
            for info in infos:
                path = PurePosixPath(info.filename)
                raw_parts = info.filename.split("/")
                if info.filename.endswith("/"):
                    raw_parts = raw_parts[:-1]
                if (
                    not info.filename
                    or path.is_absolute()
                    or any(
                        not part or part in {".", ".."} or ":" in part
                        for part in raw_parts
                    )
                    or any(ord(character) < 32 for character in info.filename)
                    or "\\" in info.filename
                ):
                    raise RuntimePolicyError("plugin package contains an unsafe path")
                if info.filename in names:
                    raise RuntimePolicyError("plugin package contains duplicate paths")
                names.add(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise RuntimePolicyError("plugin package contains a symbolic link")
                if info.file_size > _MAX_PACKAGE_FILE_BYTES:
                    raise RuntimePolicyError("plugin package file exceeds maximum size")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_PACKAGE_UNCOMPRESSED_BYTES:
                    raise RuntimePolicyError(
                        "plugin package exceeds maximum uncompressed size"
                    )
                if (
                    info.compress_size
                    and info.file_size / info.compress_size
                    > _MAX_PACKAGE_COMPRESSION_RATIO
                ):
                    raise RuntimePolicyError(
                        "plugin package exceeds maximum compression ratio"
                    )
                if info.is_dir():
                    if info.filename != "payload/" and not info.filename.startswith(
                        "payload/"
                    ):
                        raise RuntimePolicyError(
                            "plugin package contains an unsupported directory"
                        )
                    continue
                if info.filename == "manifest.json":
                    manifest_data = read_bounded(info)
                elif info.filename.startswith("payload/"):
                    relative = info.filename[len("payload/") :]
                    if not relative:
                        raise RuntimePolicyError("payload entry must have a filename")
                    data = read_bounded(info)
                    payload.append((relative, data))
                else:
                    raise RuntimePolicyError(
                        "plugin package contains an unexpected file"
                    )
        except (
            OSError,
            RuntimeError,
            zipfile.BadZipFile,
            EOFError,
            UnicodeError,
            zlib.error,
        ) as exc:
            raise RuntimePolicyError("failed to read plugin package") from exc
        finally:
            archive.close()

        if manifest_data is None:
            raise RuntimePolicyError("plugin package is missing manifest.json")
        try:
            manifest = json.loads(manifest_data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimePolicyError("plugin manifest is invalid JSON") from exc
        plugin_id = str(manifest.get("plugin_id", ""))
        if not _PLUGIN_ID.fullmatch(plugin_id):
            raise RuntimePolicyError("plugin manifest has an invalid plugin id")
        if not _ENTRYPOINT.fullmatch(str(manifest.get("entrypoint", ""))):
            raise RuntimePolicyError("plugin manifest has an invalid entrypoint")
        backend_routes = self._backend_routes(manifest)
        capabilities = {
            item.get("name")
            for item in manifest.get("capabilities", [])
            if isinstance(item, dict)
        }
        for backend_route in backend_routes:
            required = (
                "backend.routes.plugin"
                if backend_route["scope"] == "plugin"
                else "backend.routes.host"
            )
            if not {required, "backend.routes", "api.full"}.intersection(capabilities):
                raise RuntimePolicyError(f"plugin backend route requires {required}")
        self._validate_host_route_ownership(plugin_id, backend_routes)
        frontend = manifest.get("frontend")
        if frontend is not None:
            if (
                isinstance(frontend, dict)
                and type(frontend.get("inline_assets", False)) is not bool
            ):
                raise RuntimePolicyError("frontend inline_assets must be a boolean")
            if not isinstance(frontend, dict) or not isinstance(
                frontend.get("entry"), str
            ):
                raise RuntimePolicyError(
                    "plugin manifest has an invalid frontend declaration"
                )
            entry = str(frontend["entry"])
            frontend_path = PurePosixPath(entry)
            if (
                not entry
                or frontend_path.is_absolute()
                or ".." in frontend_path.parts
                or "." in frontend_path.parts
                or "\\" in entry
                or not entry.startswith("frontend/")
            ):
                raise RuntimePolicyError(
                    "plugin manifest has an invalid frontend entry"
                )
            if not any(name == entry for name, _ in payload):
                raise RuntimePolicyError(
                    "plugin frontend entry is missing from the package payload"
                )
        native_frontend = manifest.get("native_frontend")
        if native_frontend is not None:
            if not isinstance(native_frontend, dict) or not isinstance(
                native_frontend.get("entry"), str
            ):
                raise RuntimePolicyError(
                    "plugin manifest has an invalid native frontend declaration"
                )
            native_styles = native_frontend.get("styles", [])
            if not isinstance(native_styles, list) or not all(
                isinstance(value, str) for value in native_styles
            ):
                raise RuntimePolicyError(
                    "plugin manifest has invalid native frontend styles"
                )
            capabilities = {
                item.get("name")
                for item in manifest.get("capabilities", [])
                if isinstance(item, dict)
            }
            if "frontend.native" not in capabilities:
                raise RuntimePolicyError(
                    "plugin native frontend requires frontend.native"
                )
            native_paths = [
                str(native_frontend["entry"]),
                *native_styles,
            ]
            for native_path_value in native_paths:
                native_path = PurePosixPath(native_path_value)
                if (
                    not native_path_value.startswith("native/")
                    or native_path.is_absolute()
                    or ".." in native_path.parts
                    or "." in native_path.parts
                    or "\\" in native_path_value
                ):
                    raise RuntimePolicyError(
                        "plugin manifest has an invalid native frontend asset"
                    )
                if not any(name == native_path_value for name, _ in payload):
                    raise RuntimePolicyError(
                        "plugin native frontend asset is missing from the package payload"
                    )

        digest = hashlib.sha256()
        for name, data in sorted(payload):
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
        expected = str(manifest.get("integrity", {}).get("sha256", ""))
        if (
            not re.fullmatch(r"[0-9a-fA-F]{64}", expected)
            or digest.hexdigest().lower() != expected.lower()
        ):
            raise RuntimePolicyError("plugin package integrity verification failed")

        target = self.root / plugin_id
        state = self._state()
        previous_state = state.get(plugin_id)
        if isinstance(previous_state, dict) and (
            previous_state.get("pending_installation")
            or previous_state.get("pending_activation")
        ):
            raise RuntimePolicyError(
                "plugin installation is awaiting its permission commit"
            )
        if target.exists() and not replace:
            raise RuntimePolicyError("plugin is already installed")
        if replace and (
            not target.is_dir()
            or not isinstance(previous_state, dict)
            or previous_state.get("installation_id") != installation_id
        ):
            raise RuntimePolicyError(
                "plugin update installation identity does not match"
            )
        if (
            replace
            and operation_id is not None
            and (
                expected_version is None
                or str(self.package(plugin_id)[1].get("version")) != expected_version
            )
        ):
            raise RuntimePolicyError(
                "installed plugin version changed after update planning"
            )
        if target.exists():
            self.supervisor._package_paths[plugin_id] = target
            self.supervisor._settings(
                plugin_id
            )  # Migrate data before replacing its package.
            self._transition(plugin_id, enabled=False, status="stopping")
            self.supervisor.stop(plugin_id)
        staging = (
            self.root / f".install-{plugin_id}-{os.getpid()}-{threading.get_ident()}"
        )
        if staging.exists():
            raise RuntimePolicyError("plugin installation is already in progress")
        backup: Path | None = None
        published = False
        try:
            staging.mkdir(mode=0o700)
        except OSError as exc:
            raise RuntimePolicyError(
                "plugin storage is not writable; ensure /var/lib/unnamed-tracking/plugins "
                "is owned by the plugin runtime user"
            ) from exc
        try:
            for name, data in payload:
                relative = PurePosixPath(name)
                destination = staging.joinpath(*relative.parts)
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                destination.write_bytes(data)
                destination.chmod(0o700)
            (staging / "manifest.json").write_bytes(manifest_data)
            if target.exists():
                backup = (
                    self.root
                    / f".backup-{plugin_id}-{os.getpid()}-{threading.get_ident()}"
                )
                target.rename(backup)
                try:
                    staging.rename(target)
                except Exception:
                    backup.rename(target)
                    raise
            else:
                staging.rename(target)
            published = True
            if replace and isinstance(previous_state, dict):
                next_state = dict(previous_state)
                next_state["status"] = (
                    "quarantined"
                    if previous_state.get("status") == "quarantined"
                    else "stopped"
                    if previous_state.get("enabled")
                    else "disabled"
                )
                if source_metadata:
                    next_state["source"] = source_metadata
                if trust_metadata:
                    next_state["trust"] = trust_metadata
                state[plugin_id] = next_state
            else:
                state[plugin_id] = {
                    "enabled": False,
                    "user_id": None,
                    "installation_id": installation_id,
                    "source": source_metadata or {"type": "upload"},
                    "trust": trust_metadata or {},
                }
            if operation_id is not None:
                state[plugin_id]["enabled"] = False
                state[plugin_id]["pending_installation"] = {
                    "operation_id": operation_id,
                    "previous_state": previous_state,
                    "backup": backup.name if backup is not None else None,
                }
            self._save_state(state)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if published:
                shutil.rmtree(target, ignore_errors=True)
                if backup is not None:
                    backup.rename(target)
            raise
        if backup is not None and operation_id is None:
            shutil.rmtree(backup, ignore_errors=True)
        self.supervisor._log(
            plugin_id,
            "Plugin package updated." if replace else "Plugin package installed.",
            event="package.updated" if replace else "package.installed",
            metadata={"version": manifest.get("version", "0.0.0")},
        )
        return {
            "plugin_id": plugin_id,
            "name": manifest.get("name", plugin_id),
            "version": manifest.get("version", "0.0.0"),
            "status": "updated" if replace else "installed",
            "operation_id": operation_id,
        }

    def finish_installation(
        self, plugin_id: str, operation_id: str, *, commit: bool
    ) -> None:
        """Finish a host grant transaction; unfinished packages cannot execute."""
        with self._installation_lock:
            self.package(plugin_id)
            state = self._state()
            current = state.get(plugin_id, {})
            pending = current.get("pending_installation")
            if (
                not isinstance(pending, dict)
                or pending.get("operation_id") != operation_id
            ):
                raise RuntimePolicyError("plugin installation operation does not match")
            backup_name = pending.get("backup")
            backup = self.root / backup_name if backup_name else None
            if backup is not None and (
                not re.fullmatch(r"\.backup-[A-Za-z0-9._-]+", str(backup_name))
                or not backup.is_dir()
            ):
                raise RuntimePolicyError("plugin installation backup is unavailable")
            if commit:
                current = dict(current)
                current.pop("pending_installation")
                current["pending_activation"] = pending
                previous = pending.get("previous_state") or {}
                current["enabled"] = bool(previous.get("enabled"))
                current["status"] = "stopped" if current["enabled"] else "disabled"
                state[plugin_id] = current
                self._save_state(state)
                return
            # Persist a disabled state first. If recovery fails, never expose
            # candidate code with the predecessor's still-authorized grants.
            previous_state = pending.get("previous_state")
            target = self.root / plugin_id
            if backup is not None:
                rejected = self.root / f".rejected-{plugin_id}-{operation_id}"
                target.rename(rejected)
                try:
                    backup.rename(target)
                except Exception:
                    rejected.rename(target)
                    raise
                state[plugin_id] = previous_state
                self._save_state(state)
                shutil.rmtree(rejected, ignore_errors=True)
                if (
                    isinstance(previous_state, dict)
                    and previous_state.get("enabled")
                    and previous_state.get("status") != "stopped"
                ):
                    self._transition(plugin_id, status="stopped")
                    self.start(plugin_id, user_id=previous_state.get("user_id"))
            else:
                shutil.rmtree(target)
                state.pop(plugin_id, None)
                self._save_state(state)

    def finish_activation(
        self, plugin_id: str, operation_id: str, *, commit: bool
    ) -> None:
        """Retain a predecessor only after health verification; recover on failure."""
        with self._installation_lock:
            state = self._state()
            current = state.get(plugin_id, {})
            pending = current.get("pending_activation")
            if (
                not isinstance(pending, dict)
                or pending.get("operation_id") != operation_id
            ):
                raise RuntimePolicyError("plugin activation operation does not match")
            backup_name = pending.get("backup")
            backup = self.root / backup_name if backup_name else None
            if backup is not None and (
                not re.fullmatch(r"\.backup-[A-Za-z0-9._-]+", str(backup_name))
                or not backup.is_dir()
            ):
                raise RuntimePolicyError("plugin activation backup is unavailable")
            if not commit:
                self.supervisor.stop(plugin_id)
                current.pop("pending_activation")
                current["pending_installation"] = pending
                state[plugin_id] = current
                self._save_state(state)
                self.finish_installation(plugin_id, operation_id, commit=False)
                return
            current.pop("pending_activation")
            if backup is not None:
                manifest = json.loads(
                    (backup / "manifest.json").read_text(encoding="utf-8")
                )
                history_id = str(uuid4())
                history_root = self.root / ".history" / plugin_id
                history_root.mkdir(mode=0o700, parents=True, exist_ok=True)
                backup.rename(history_root / history_id)
                history = list(current.get("history", []))
                history.insert(
                    0,
                    {
                        "id": history_id,
                        "version": manifest["version"],
                        "digest": manifest["integrity"]["sha256"],
                        "trust": (pending.get("previous_state") or {}).get("trust", {}),
                    },
                )
                current["history"] = history
            state[plugin_id] = current
            self._save_state(state)

    def package_archive(
        self, plugin_id: str, history_id: str | None = None
    ) -> dict[str, Any]:
        """Return the exact active/retained release without consulting a mutable URL."""
        package, manifest = self.package(plugin_id)
        if history_id is not None:
            UUID(history_id)
            history = self._state().get(plugin_id, {}).get("history", [])
            if not any(item["id"] == history_id for item in history):
                raise KeyError(history_id)
            package = self.root / ".history" / plugin_id / history_id
            manifest = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8")
            )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for path in self._payload_files(package):
                archive.writestr(
                    f"payload/{path.relative_to(package).as_posix()}", path.read_bytes()
                )
        return {"package": base64.b64encode(output.getvalue()).decode("ascii")}

    def prune_history(
        self, plugin_id: str, *, retain: int = 1, history_id: str | None = None
    ) -> None:
        with self._installation_lock:
            self.package(plugin_id)
            if not 1 <= retain <= 100:
                raise RuntimePolicyError("retain must be between 1 and 100")
            state = self._state()
            current = state[plugin_id]
            history = current.get("history", [])
            keep = [item for item in history if item["id"] != history_id][:retain]
            removed = [item for item in history if item not in keep]
            current["history"] = keep
            self._save_state(state)
            for item in removed:
                UUID(item["id"])
                shutil.rmtree(self.root / ".history" / plugin_id / item["id"])

    def purge_data(self, plugin_id: str) -> None:
        self.package(plugin_id)
        self.stop(plugin_id)
        self.supervisor._storage(plugin_id).uninstall()
        configuration = (
            self.supervisor.storage_root.parent / ".configuration" / f"{plugin_id}.json"
        )
        configuration.unlink(missing_ok=True)
        (self.root / plugin_id / ".settings.json").unlink(missing_ok=True)

    def list(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for package in self.packages():
            try:
                result.append(self._item(package))
            except Exception as exc:
                result.append(
                    {
                        "plugin_id": package.name,
                        "name": "Invalid plugin",
                        "version": "0.0.0",
                        "compatible": False,
                        "compatibility_reason": str(exc),
                        "permissions": [],
                        "enabled": False,
                        "status": "failed",
                        "health": "unhealthy",
                    }
                )
        return result

    def frontend(
        self, plugin_id: str, relative: str, *, native: bool = False
    ) -> dict[str, Any]:
        self._require_active(plugin_id)
        package, manifest = self.package(plugin_id)
        declaration_name = "native_frontend" if native else "frontend"
        required_prefix = "native/" if native else "frontend/"
        declaration = manifest.get(declaration_name)
        if not isinstance(declaration, dict) or not declaration.get("entry"):
            raise KeyError(relative)
        entry = str(declaration["entry"])
        relative = relative or entry
        if not relative.startswith(required_prefix):
            raise RuntimePolicyError(
                "plugin frontend asset is outside its declared root"
            )
        path = package / Path(relative)
        try:
            path.resolve(strict=True).relative_to(package.resolve())
        except (OSError, ValueError) as exc:
            raise RuntimePolicyError(
                "plugin frontend path escapes the package"
            ) from exc
        if not path.is_file():
            raise KeyError(relative)
        data = path.read_bytes()
        if len(data) > 4 * 1024 * 1024:
            raise RuntimePolicyError("plugin frontend asset exceeds 4 MiB")
        return {"path": relative, "content": base64.b64encode(data).decode("ascii")}

    def ui(self, plugin_id: str) -> dict[str, Any]:
        package, manifest = self.package(plugin_id)
        ui_path = package / "ui.json"
        if not ui_path.is_file():
            document = {
                "schema_version": "v1",
                "plugin_id": plugin_id,
                "title": manifest.get("name", plugin_id),
                "settings": [],
                "actions": [],
                "tables": [],
                "dialogs": [],
                "menus": [],
                "pages": [],
            }
        else:
            try:
                document = json.loads(ui_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimePolicyError("plugin UI document is invalid JSON") from exc
        if document.get("plugin_id") != plugin_id:
            raise RuntimePolicyError("plugin UI document has the wrong plugin_id")
        frontend = manifest.get("frontend")
        if isinstance(frontend, dict) and frontend.get("entry"):
            document["frontend"] = {"entry": str(frontend["entry"])}
            if frontend.get("inline_assets") is True:
                document["frontend"]["inline_assets"] = True
        native_frontend = manifest.get("native_frontend")
        if isinstance(native_frontend, dict) and native_frontend.get("entry"):
            document["native_frontend"] = {
                "entry": str(native_frontend["entry"]),
                "styles": [str(value) for value in native_frontend.get("styles", [])],
            }
        return document

    def _command(self, manifest: dict[str, Any]) -> tuple[str, ...]:
        module, _, function = str(manifest["entrypoint"]).partition(":")
        function = function or "main"
        script = (
            "import importlib; "
            f"m=importlib.import_module({module!r}); "
            f"f=getattr(m,{function!r}); f()"
        )
        return (sys.executable, "-c", script)

    @staticmethod
    def _action_command(handler: str) -> tuple[str, ...]:
        if not _ENTRYPOINT.fullmatch(handler):
            raise RuntimePolicyError("plugin action has an invalid handler")
        module, _, function = handler.partition(":")
        function = function or "main"
        script = (
            "import importlib,json,sys; "
            f"m=importlib.import_module({module!r}); "
            f"f=getattr(m,{function!r}); "
            "result=f(json.loads(sys.stdin.readline())); "
            "json.dump({'plugin_action_result':result if isinstance(result,dict) else {'completed':result is not False}},sys.stdout); "
            "sys.stdout.write('\\n');sys.stdout.flush(); "
            "raise SystemExit(0 if result is not False else 1)"
        )
        return (sys.executable, "-c", script)

    @staticmethod
    def _route_command(handler: str) -> tuple[str, ...]:
        if not _ENTRYPOINT.fullmatch(handler):
            raise RuntimePolicyError("plugin backend route has an invalid handler")
        module, _, function = handler.partition(":")
        function = function or "main"
        script = (
            "import importlib,json,sys; "
            f"m=importlib.import_module({module!r}); "
            f"f=getattr(m,{function!r}); "
            "result=f(json.loads(sys.stdin.readline())); "
            "json.dump({'plugin_action_result':result},sys.stdout); "
            "sys.stdout.write('\\n');sys.stdout.flush()"
        )
        return (sys.executable, "-c", script)

    def start(self, plugin_id: str, user_id: str | None = None) -> None:
        with self._operation_lock:
            package, manifest = self.package(plugin_id)
            item = self._item(package)
            if not item["compatible"]:
                raise RuntimePolicyError(item["compatibility_reason"])
            persisted = self._state().get(plugin_id)
            if not isinstance(persisted, dict) or not persisted.get("installation_id"):
                raise RuntimePolicyError("plugin installation identity is missing")
            if persisted.get("pending_installation"):
                raise RuntimePolicyError(
                    "plugin installation is awaiting its permission commit"
                )
            if persisted.get("status") == "quarantined":
                raise RuntimePolicyError(
                    "quarantined plugin must be recovered before starting"
                )
            if self.supervisor.running(plugin_id):
                raise RuntimePolicyError("plugin is already running")
            self.supervisor.stop(plugin_id)
            self.supervisor._user_ids[plugin_id] = user_id or persisted.get("user_id")
            self.supervisor._installation_ids[plugin_id] = str(
                persisted["installation_id"]
            )
            quota_mb = manifest.get("storage", {}).get("quota_mb") or 64
            self.supervisor._storage_quotas[plugin_id] = int(quota_mb) * 1024 * 1024
            self._transition(
                plugin_id,
                enabled=True,
                status="starting",
                user_id=self.supervisor._user_ids[plugin_id],
            )
            try:
                self.supervisor.start(
                    PluginSpec(plugin_id, self._command(manifest)), package
                )
            except Exception as exc:
                self._transition(
                    plugin_id,
                    status="failed",
                    last_error=self.supervisor._redact(str(exc)),
                )
                self.supervisor.stop(plugin_id)
                raise
            self._transition(plugin_id, status="running", last_error=None)
            if not self.supervisor.running(plugin_id):
                self._transition(plugin_id, status="failed")
                self.supervisor.stop(plugin_id)

    def stop(self, plugin_id: str, *, disable: bool = True) -> None:
        with self._operation_lock:
            self.package(plugin_id)
            persisted = self._state().get(plugin_id)
            quarantined = (
                isinstance(persisted, dict) and persisted.get("status") == "quarantined"
            )
            # Revoke execution before waiting for any worker to finish.
            enabled = (
                bool(isinstance(persisted, dict) and persisted.get("enabled"))
                and not disable
            )
            self._transition(plugin_id, enabled=enabled, status="stopping")
            try:
                self.supervisor.stop(plugin_id)
            except Exception:
                self._transition(
                    plugin_id, status="quarantined" if quarantined else "failed"
                )
                raise
            self._transition(
                plugin_id,
                status="quarantined"
                if quarantined
                else "stopped"
                if enabled
                else "disabled",
            )

    def quarantine(self, plugin_id: str) -> None:
        with self._operation_lock:
            self.package(plugin_id)
            self._transition(plugin_id, enabled=False, status="quarantined")
            self.supervisor.stop(plugin_id)

    def diagnostics(self, plugin_id: str) -> dict[str, Any]:
        self.package(plugin_id)
        running = self.supervisor.running(plugin_id)
        return {
            "plugin_id": plugin_id,
            "status": "running" if running else "stopped",
            "last_exit_code": self.supervisor.exit_code(plugin_id),
            "events": self.supervisor.logs(plugin_id),
            "runtime": self.supervisor.isolation,
            "process_running": running,
            "last_error": self._state().get(plugin_id, {}).get("last_error"),
        }

    def storage_put(self, plugin_id: str, key: str, value: str) -> None:
        self.package(plugin_id)
        self.supervisor._storage(plugin_id).put(key, value.encode())

    def storage_keys(self, plugin_id: str, prefix: str = "") -> list[str]:
        self.package(plugin_id)
        return list(self.supervisor._storage(plugin_id).keys(prefix))

    def health(self, plugin_id: str) -> bool:
        self.package(plugin_id)
        # Let an actual worker finish imports and initialization before committing
        # a package switch. Synthetic supervisors need no startup grace period.
        if plugin_id in self.supervisor._processes:
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                if not self.supervisor.running(plugin_id):
                    break
                time.sleep(0.05)
        healthy = self.supervisor.running(plugin_id)
        self._transition(plugin_id, last_health=healthy)
        return healthy

    def settings(self, plugin_id: str, values: dict[str, Any]) -> None:
        package, _ = self.package(plugin_id)
        secret_ids = {
            str(field.get("id"))
            for section in self.ui(plugin_id).get("settings", [])
            for field in section.get("fields", [])
            if field.get("secret") is True
        }
        if secret_ids.intersection(values):
            raise RuntimePolicyError(
                "secret settings may only be supplied to a plugin action"
            )
        self.supervisor._package_paths[plugin_id] = package
        self.supervisor._settings(plugin_id)
        path = (
            self.supervisor.storage_root.parent / ".configuration" / f"{plugin_id}.json"
        )
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        current: dict[str, Any] = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        current.update(values)
        path.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _discord_webhook(url: str, content: str) -> None:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.hostname not in {"discord.com", "discordapp.com"}
            or not parts.path.startswith("/api/webhooks/")
        ):
            raise RuntimePolicyError(
                "Discord webhook must use an HTTPS discord.com or discordapp.com webhook URL"
            )
        body = json.dumps({"content": content[:2000]}).encode("utf-8")
        request = Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urlopen(request, timeout=10) as response:
                if response.status >= 400:
                    raise RuntimePolicyError(
                        f"Discord webhook returned HTTP {response.status}"
                    )
        except OSError as exc:
            raise RuntimePolicyError("Discord webhook delivery failed") from exc

    def action(
        self,
        plugin_id: str,
        action_id: str,
        values: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_active(plugin_id)
        document = self.ui(plugin_id)
        action = next(
            (
                item
                for item in document.get("actions", [])
                if item.get("id") == action_id
            ),
            None,
        )
        if action is None:
            raise KeyError(action_id)
        capability = action.get("capability")
        if capability is not None:
            if not isinstance(capability, dict) or not isinstance(
                capability.get("name"), str
            ):
                raise RuntimePolicyError("plugin action capability is invalid")
            self.supervisor._authorize_capability(
                plugin_id,
                capability["name"],
                user_id=user_id,
                version=capability.get("version", 1),
            )
        handler = action.get("handler")
        if not isinstance(handler, str):
            raise RuntimePolicyError("plugin action does not declare a runtime handler")
        try:
            payload = json.dumps(values, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RuntimePolicyError(
                "plugin action values must be JSON-compatible"
            ) from exc
        package, manifest = self.package(plugin_id)
        output = self.supervisor.execute(
            PluginSpec(plugin_id, self._action_command(handler)),
            package,
            payload,
            user_id=user_id,
        )
        result: dict[str, Any] = {"completed": True}
        if output:
            try:
                message = json.loads(output.decode("utf-8").strip())
            except (UnicodeDecodeError, ValueError) as exc:
                raise RuntimePolicyError(
                    "plugin action returned invalid output"
                ) from exc
            if not isinstance(message, dict):
                raise RuntimePolicyError("plugin action result must be an object")
            result = message
            discord_requested = message.get("discord") is True
            if discord_requested:
                capabilities = {
                    item.get("name") for item in manifest.get("capabilities", [])
                }
                delivery_provider = "notification_providers.deliver" in capabilities
                self.supervisor._authorize_capability(
                    plugin_id,
                    "notification_providers.deliver"
                    if delivery_provider
                    else "notifications.send",
                    user_id=user_id,
                )
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimePolicyError(
                        "Discord delivery requires a non-empty message"
                    )
                webhook_bytes = self.supervisor._storage(plugin_id).get(
                    "secrets/discord_webhook"
                )
                webhook = webhook_bytes.decode("utf-8").strip() if webhook_bytes else ""
                if not webhook:
                    raise RuntimePolicyError(
                        "Discord delivery requires a configured plugin webhook"
                    )
                if (
                    os.getenv("PLUGIN_RUNTIME_DISCORD_EGRESS", "false").lower()
                    != "true"
                ):
                    raise RuntimePolicyError(
                        "Discord egress is disabled in this runtime"
                    )
                self._discord_webhook(webhook, content)
                result = (
                    {"success": True, "retryable": False, "error": None}
                    if delivery_provider
                    else {"completed": True}
                )
        return result

    def route(
        self,
        plugin_id: str,
        route_id: str,
        request: dict[str, Any],
        *,
        user_id: str,
    ) -> dict[str, Any]:
        self._require_active(plugin_id)
        package, manifest = self.package(plugin_id)
        route = next(
            (item for item in self._backend_routes(manifest) if item["id"] == route_id),
            None,
        )
        if route is None:
            raise KeyError(route_id)
        if request.get("method") not in route["methods"]:
            raise RuntimePolicyError("backend route method is not declared")
        try:
            payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RuntimePolicyError(
                "backend route request must be JSON-compatible"
            ) from exc
        output = self.supervisor.execute(
            PluginSpec(plugin_id, self._route_command(str(route["handler"]))),
            package,
            payload,
            user_id=user_id,
        )
        try:
            result = json.loads(output.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimePolicyError("backend route returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise RuntimePolicyError("backend route response must be an object")
        return result

    def delete(self, plugin_id: str) -> None:
        with self._operation_lock:
            package, manifest = self.package(plugin_id)
            self.purge_data(plugin_id)
            shutil.rmtree(self.root / ".history" / plugin_id, ignore_errors=True)
            self.stop(plugin_id)
            quota_mb = manifest.get("storage", {}).get("quota_mb") or 64
            self.supervisor._storage_quotas[plugin_id] = int(quota_mb) * 1024 * 1024
            self.supervisor._storage(plugin_id).uninstall()
            shutil.rmtree(package, ignore_errors=False)
            with self._state_lock:
                state = self._state()
                pending = state.get(plugin_id, {}).get(
                    "pending_installation"
                ) or state.get(plugin_id, {}).get("pending_activation", {})
                backup_name = (
                    pending.get("backup") if isinstance(pending, dict) else None
                )
                if backup_name and re.fullmatch(
                    r"\.backup-[A-Za-z0-9._-]+", str(backup_name)
                ):
                    shutil.rmtree(self.root / backup_name, ignore_errors=True)
                state.pop(plugin_id, None)
                self._save_state(state)

    def restore_enabled(self) -> None:
        state = self._state()
        for package in self.packages():
            try:
                plugin_id = self.package(package.name)[1]["plugin_id"]
                raw_state = state.get(plugin_id, True)
                enabled = (
                    raw_state.get("enabled", True)
                    if isinstance(raw_state, dict)
                    else bool(raw_state)
                )
                user_id = (
                    raw_state.get("user_id") if isinstance(raw_state, dict) else None
                )
                if enabled and not (
                    isinstance(raw_state, dict)
                    and (
                        raw_state.get("status") == "stopped"
                        or raw_state.get("pending_activation")
                        or raw_state.get("pending_installation")
                    )
                ):
                    self._transition(plugin_id, status="stopped")
                    try:
                        self.start(plugin_id, user_id=user_id)
                    except Exception:
                        pass
            except Exception:
                pass


class RuntimeHandler(BaseHTTPRequestHandler):
    server_version = "UnnamedTrackingPluginRuntime/1.0"

    def _authorized(self) -> bool:
        if self.path.split("?", 1)[0] == "/health":
            return True
        token = os.environ.get("PLUGIN_RUNTIME_TOKEN", "")
        return len(token) >= 32 and self.headers.get("X-Plugin-Runtime-Token") == token

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parts(self) -> list[str]:
        return [unquote(x) for x in self.path.split("?", 1)[0].split("/") if x]

    def do_GET(self) -> None:
        if not self._authorized():
            self._json(401, {"detail": "runtime authentication required"})
            return
        parts = self._parts()
        try:
            if parts == ["health"]:
                self._json(
                    200, {"status": "ok", **self.server.registry.supervisor.isolation}
                )
            elif parts == ["plugins"]:
                self._json(200, self.server.registry.list())  # type: ignore[attr-defined]
            elif len(parts) == 3 and parts[0] == "plugins" and parts[2] == "archive":
                self._json(200, self.server.registry.package_archive(parts[1]))
            elif len(parts) == 4 and parts[0] == "plugins" and parts[2] == "archive":
                self._json(
                    200, self.server.registry.package_archive(parts[1], parts[3])
                )
            elif len(parts) == 3 and parts[0] == "plugins" and parts[2] == "ui":
                self._json(200, self.server.registry.ui(parts[1]))  # type: ignore[attr-defined]
            elif len(parts) == 3 and parts[0] == "plugins" and parts[2] == "health":
                self._json(200, {"healthy": self.server.registry.health(parts[1])})  # type: ignore[attr-defined]
            elif len(parts) == 3 and parts[0] == "plugins" and parts[2] == "logs":
                self._json(200, self.server.registry.diagnostics(parts[1]))  # type: ignore[attr-defined]
            elif len(parts) >= 3 and parts[0] == "plugins" and parts[2] == "frontend":
                relative = "/".join(parts[3:])
                self._json(200, self.server.registry.frontend(parts[1], relative))  # type: ignore[attr-defined]
            elif (
                len(parts) >= 3
                and parts[0] == "plugins"
                and parts[2] == "native-frontend"
            ):
                relative = "/".join(parts[3:])
                self._json(  # type: ignore[attr-defined]
                    200,
                    self.server.registry.frontend(parts[1], relative, native=True),
                )
            else:
                self._json(404, {"detail": "not found"})
        except KeyError:
            self._json(404, {"detail": "plugin not found"})
        except RuntimePolicyError as exc:
            self._json(422, {"detail": str(exc)})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(401, {"detail": "runtime authentication required"})
            return
        parts = self._parts()
        try:
            if (
                len(parts) == 3
                and parts[0] == "plugins"
                and parts[2] in {"start", "stop", "disable", "purge"}
            ):
                payload = {}
                if parts[2] == "start":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length:
                        payload = json.loads(self.rfile.read(length))
                    self.server.registry.start(parts[1], user_id=payload.get("user_id"))  # type: ignore[attr-defined]
                elif parts[2] == "purge":
                    self.server.registry.purge_data(parts[1])
                else:
                    self.server.registry.stop(parts[1], disable=parts[2] == "disable")
                self._json(200, {"plugin_id": parts[1], "status": parts[2]})
                return
            if len(parts) == 3 and parts[0] == "plugins" and parts[2] == "storage":
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) if length else b"{}")
                self.server.registry.storage_put(
                    parts[1], str(payload.get("key", "")), str(payload.get("value", ""))
                )  # type: ignore[attr-defined]
                self._json(200, {"saved": True})
                return
            if len(parts) == 4 and parts[0] == "plugins" and parts[2] == "actions":
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) if length else b"{}")
                result = self.server.registry.action(
                    parts[1],
                    parts[3],
                    payload.get("values", {}),
                    user_id=payload.get("user_id"),
                )  # type: ignore[attr-defined]
                self._json(200, result)
                return
            if len(parts) == 4 and parts[0] == "plugins" and parts[2] == "routes":
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 64 * 1024:
                    raise RuntimePolicyError(
                        "plugin backend route payload must be between 1 byte and 64 KiB"
                    )
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("request"), dict
                ):
                    raise RuntimePolicyError("plugin backend route payload is invalid")
                user_id = payload.get("user_id")
                try:
                    UUID(str(user_id))
                except ValueError as exc:
                    raise RuntimePolicyError(
                        "plugin backend route user identity is invalid"
                    ) from exc
                result = self.server.registry.route(  # type: ignore[attr-defined]
                    parts[1], parts[3], payload["request"], user_id=str(user_id)
                )
                self._json(200, result)
                return
            self._json(404, {"detail": "not found"})
        except KeyError:
            self._json(404, {"detail": "plugin not found"})
        except (RuntimePolicyError, ValueError, json.JSONDecodeError) as exc:
            self._json(422, {"detail": str(exc)})

    def do_PUT(self) -> None:
        if not self._authorized():
            self._json(401, {"detail": "runtime authentication required"})
            return
        parts = self._parts()
        if parts in (["plugins", "install"], ["plugins", "install", "prepare"]):
            try:
                if parts[-1] == "prepare" and not self.headers.get(
                    "X-Plugin-Operation-ID"
                ):
                    raise RuntimePolicyError(
                        "prepared installation requires an operation ID"
                    )
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 64 * 1024 * 1024:
                    self._json(
                        413,
                        {"detail": "plugin package exceeds the 64 MiB upload limit"},
                    )
                    return
                package = self.rfile.read(length)

                def metadata_header(name: str) -> dict[str, Any]:
                    raw = self.headers.get(name, "")
                    if not raw:
                        return {}
                    try:
                        value = json.loads(
                            base64.urlsafe_b64decode(raw.encode("ascii"))
                        )
                    except (ValueError, UnicodeError) as exc:
                        raise RuntimePolicyError(f"{name} is invalid") from exc
                    if not isinstance(value, dict):
                        raise RuntimePolicyError(f"{name} must contain an object")
                    return value

                result = self.server.registry.install_package(  # type: ignore[attr-defined]
                    package,
                    self.headers.get("X-Plugin-Package-Name", ""),
                    installation_id=self.headers.get("X-Plugin-Installation-ID", ""),
                    replace=self.headers.get("X-Plugin-Replace", "").lower() == "true",
                    source_metadata=metadata_header("X-Plugin-Source"),
                    trust_metadata=metadata_header("X-Plugin-Trust"),
                    operation_id=self.headers.get("X-Plugin-Operation-ID") or None,
                    expected_version=self.headers.get("X-Plugin-Expected-Version")
                    or None,
                )
                self._json(201, result)
            except (RuntimePolicyError, ValueError, OSError) as exc:
                self._json(422, {"detail": str(exc)})
            return
        if (
            len(parts) == 3
            and parts[0] == "plugins"
            and parts[2] in {"installation", "activation", "history"}
        ):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 4096:
                    raise RuntimePolicyError("invalid installation completion request")
                payload = json.loads(self.rfile.read(length))
                if parts[2] == "history" and isinstance(payload, dict):
                    self.server.registry.prune_history(parts[1], **payload)
                    self._json(200, {"completed": True})
                    return
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("commit"), bool
                ):
                    raise RuntimePolicyError("invalid installation completion request")
                finish = (
                    self.server.registry.finish_activation
                    if parts[2] == "activation"
                    else self.server.registry.finish_installation
                )
                finish(
                    parts[1],
                    str(payload.get("operation_id", "")),
                    commit=payload["commit"],
                )
                self._json(200, {"completed": True})
            except KeyError:
                self._json(404, {"detail": "plugin not found"})
            except (RuntimePolicyError, ValueError, OSError) as exc:
                self._json(422, {"detail": str(exc)})
            return
        if not self._authorized():
            self._json(401, {"detail": "runtime authentication required"})
            return
        parts = self._parts()
        if len(parts) != 3 or parts[0] != "plugins" or parts[2] != "settings":
            self._json(404, {"detail": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) if length else b"{}")
            self.server.registry.settings(parts[1], payload)
            self._json(200, {"saved": True})
        except KeyError:
            self._json(404, {"detail": "plugin not found"})
        except (RuntimePolicyError, ValueError, json.JSONDecodeError) as exc:
            self._json(422, {"detail": str(exc)})

    def do_DELETE(self) -> None:
        if not self._authorized():
            self._json(401, {"detail": "runtime authentication required"})
            return
        parts = self._parts()
        if len(parts) == 2 and parts[0] == "plugins":
            try:
                self.server.registry.delete(parts[1])  # type: ignore[attr-defined]
                self._json(204, {})
            except KeyError:
                self._json(404, {"detail": "plugin not found"})
            except (RuntimePolicyError, OSError) as exc:
                self._json(422, {"detail": str(exc)})
            return
        self._json(404, {"detail": "not found"})

    def log_message(self, _format: str, *_args: object) -> None:
        return


class RuntimeServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    token = os.environ.get("PLUGIN_RUNTIME_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("PLUGIN_RUNTIME_TOKEN must contain at least 256 bits")
    root = Path(os.environ.get("PLUGIN_ROOT", "/var/lib/unnamed-tracking/plugins"))
    registry = PluginRegistry(root, PluginSupervisor())
    registry.supervisor.probe_isolation()
    server = RuntimeServer(
        (
            os.environ.get("PLUGIN_RUNTIME_HOST", "0.0.0.0"),
            int(os.environ.get("PLUGIN_RUNTIME_PORT", "8000")),
        ),
        RuntimeHandler,
    )
    server.registry = registry  # type: ignore[attr-defined]
    registry.restore_enabled()
    try:
        server.serve_forever()
    finally:
        registry.supervisor.stop_all()


if __name__ == "__main__":
    main()
