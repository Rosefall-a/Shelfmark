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
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
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
    "disable",
    "enable",
    "frontend",
    "logs",
    "native-frontend",
    "permissions",
    "retry",
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
        self._last_exit_codes: dict[str, int | None] = {}
        self._logs: dict[str, deque[dict[str, Any]]] = {}
        self._diagnostic_sequence = 0
        self._user_ids: dict[str, str | None] = {}
        self._installation_ids: dict[str, str] = {}
        self._storage_quotas: dict[str, int] = {}
        self._package_paths: dict[str, Path] = {}
        self._package_manifests: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

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
        path = package / ".settings.json"
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
        self, plugin_id: str, capability: str, *, user_id: str | None = None, version: int = 1
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
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
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
        if process is None:
            return
        self._log(plugin_id, "Stopping plugin process.", event="runtime.stopping")
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=timeout)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        finally:
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

    def running(self, plugin_id: str) -> bool:
        exited_code: int | None = None
        with self._lock:
            process = self._processes.get(plugin_id)
            if process is None:
                return False
            if process.poll() is not None:
                self._last_exit_codes[plugin_id] = process.returncode
                exited_code = process.returncode
                self._processes.pop(plugin_id, None)
                self._package_paths.pop(plugin_id, None)
                self._package_manifests.pop(plugin_id, None)
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
        for plugin_id in list(self._processes):
            self.stop(plugin_id)


class PluginRegistry:
    def __init__(self, root: Path, supervisor: PluginSupervisor) -> None:
        self.root = root
        self.supervisor = supervisor
        self.state_path = root / ".runtime-state.json"
        self.root.mkdir(mode=0o750, parents=True, exist_ok=True)

    def _state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)

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
            if scope == "plugin" and path.split("/", 1)[0] in _RESERVED_PLUGIN_ROUTE_ROOTS:
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
        return {
            "plugin_id": plugin_id,
            "name": data.get("name", plugin_id),
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
            "health": "healthy"
            if running
            else (
                "unhealthy"
                if self.supervisor.exit_code(plugin_id) not in (None, 0)
                else "unknown"
            ),
            "logs_available": bool(self.supervisor.logs(plugin_id)),
            "last_exit_code": self.supervisor.exit_code(plugin_id),
            "status": "running"
            if running
            else (
                "failed"
                if self.supervisor.exit_code(plugin_id) not in (None, 0)
                else (
                    "completed"
                    if enabled and self.supervisor.exit_code(plugin_id) == 0
                    else ("stopped" if enabled else "disabled")
                )
            ),
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
    ) -> dict[str, Any]:
        # The archive contents, not a user-controlled filename, define the format.
        del filename
        if not package:
            raise RuntimePolicyError("plugin package is empty")
        if len(package) > _MAX_PACKAGE_BYTES:
            raise RuntimePolicyError("plugin package exceeds the 64 MiB upload limit")
        try:
            UUID(installation_id)
        except ValueError as exc:
            raise RuntimePolicyError("plugin installation ID is invalid") from exc

        try:
            archive = zipfile.ZipFile(io.BytesIO(package))
        except (OSError, zipfile.BadZipFile) as exc:
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
                        not part or part in {".", ".."} or part.endswith(":")
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
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
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
        previous_state = self._state().get(plugin_id)
        if target.exists() and not replace:
            raise RuntimePolicyError("plugin is already installed")
        if target.exists():
            self.supervisor.stop(plugin_id)
        staging = (
            self.root / f".install-{plugin_id}-{os.getpid()}-{threading.get_ident()}"
        )
        if staging.exists():
            raise RuntimePolicyError("plugin installation is already in progress")
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
                shutil.rmtree(backup, ignore_errors=True)
            else:
                staging.rename(target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        state = self._state()
        if replace and isinstance(previous_state, dict):
            previous_state["installation_id"] = previous_state.get(
                "installation_id", installation_id
            )
            if source_metadata:
                previous_state["source"] = source_metadata
            if trust_metadata:
                previous_state["trust"] = trust_metadata
            state[plugin_id] = previous_state
        else:
            state[plugin_id] = {
                "enabled": False,
                "user_id": None,
                "installation_id": installation_id,
                "source": source_metadata or {"type": "upload"},
                "trust": trust_metadata or {},
            }
        self._save_state(state)
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
        }

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
        package, manifest = self.package(plugin_id)
        item = self._item(package)
        if not item["compatible"]:
            raise RuntimePolicyError(item["compatibility_reason"])
        if user_id is not None:
            self.supervisor._user_ids[plugin_id] = user_id
        persisted = self._state().get(plugin_id)
        if user_id is None and isinstance(persisted, dict):
            self.supervisor._user_ids[plugin_id] = persisted.get("user_id")
        if not isinstance(persisted, dict) or not persisted.get("installation_id"):
            raise RuntimePolicyError("plugin installation identity is missing")
        self.supervisor._installation_ids[plugin_id] = str(persisted["installation_id"])
        quota_mb = manifest.get("storage", {}).get("quota_mb") or 64
        self.supervisor._storage_quotas[plugin_id] = int(quota_mb) * 1024 * 1024
        self.supervisor.start(PluginSpec(plugin_id, self._command(manifest)), package)
        state = self._state()
        state[plugin_id] = {
            "enabled": True,
            "user_id": self.supervisor._user_ids.get(plugin_id),
            "installation_id": self.supervisor._installation_ids[plugin_id],
        }
        self._save_state(state)

    def stop(self, plugin_id: str) -> None:
        self.package(plugin_id)
        self.supervisor.stop(plugin_id)
        state = self._state()
        previous = state.get(plugin_id)
        state[plugin_id] = {
            "enabled": False,
            "user_id": previous.get("user_id")
            if isinstance(previous, dict)
            else self.supervisor._user_ids.get(plugin_id),
            "installation_id": previous.get("installation_id")
            if isinstance(previous, dict)
            else self.supervisor._installation_ids.get(plugin_id),
        }
        self._save_state(state)

    def diagnostics(self, plugin_id: str) -> dict[str, Any]:
        self.package(plugin_id)
        running = self.supervisor.running(plugin_id)
        return {
            "plugin_id": plugin_id,
            "status": "running" if running else "stopped",
            "last_exit_code": self.supervisor.exit_code(plugin_id),
            "events": self.supervisor.logs(plugin_id),
        }

    def storage_put(self, plugin_id: str, key: str, value: str) -> None:
        self.package(plugin_id)
        self.supervisor._storage(plugin_id).put(key, value.encode())

    def storage_keys(self, plugin_id: str, prefix: str = "") -> list[str]:
        self.package(plugin_id)
        return list(self.supervisor._storage(plugin_id).keys(prefix))

    def health(self, plugin_id: str) -> bool:
        self.package(plugin_id)
        return self.supervisor.running(plugin_id)

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
        path = package / ".settings.json"
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
        self, plugin_id: str, action_id: str, values: dict[str, Any], *, user_id: str | None = None
    ) -> dict[str, Any]:
        persisted = self._state().get(plugin_id)
        if not isinstance(persisted, dict) or not persisted.get("enabled", False):
            raise RuntimePolicyError("plugin must be enabled before actions can run")
        if self.supervisor.exit_code(plugin_id) not in (None, 0):
            raise RuntimePolicyError("failed plugin cannot run actions")
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
            if not isinstance(capability, dict) or not isinstance(capability.get("name"), str):
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
            PluginSpec(plugin_id, self._action_command(handler)), package, payload, user_id=user_id
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
                    "notification_providers.deliver" if delivery_provider else "notifications.send",
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
        persisted = self._state().get(plugin_id)
        if not isinstance(persisted, dict) or not persisted.get("enabled", False):
            raise RuntimePolicyError(
                "plugin must be enabled before backend routes can run"
            )
        if self.supervisor.exit_code(plugin_id) not in (None, 0):
            raise RuntimePolicyError("failed plugin cannot serve backend routes")
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
        package, manifest = self.package(plugin_id)
        self.supervisor.stop(plugin_id)
        quota_mb = manifest.get("storage", {}).get("quota_mb") or 64
        self.supervisor._storage_quotas[plugin_id] = int(quota_mb) * 1024 * 1024
        self.supervisor._storage(plugin_id).uninstall()
        shutil.rmtree(package, ignore_errors=False)
        state = self._state()
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
                if enabled:
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
                self._json(200, {"status": "ok"})
            elif parts == ["plugins"]:
                self._json(200, self.server.registry.list())  # type: ignore[attr-defined]
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
                and parts[2] in {"start", "stop"}
            ):
                payload = {}
                if parts[2] == "start":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length:
                        payload = json.loads(self.rfile.read(length))
                    self.server.registry.start(parts[1], user_id=payload.get("user_id"))  # type: ignore[attr-defined]
                else:
                    self.server.registry.stop(parts[1])  # type: ignore[attr-defined]
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
                    parts[1], parts[3], payload.get("values", {}), user_id=payload.get("user_id")
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
        if parts == ["plugins", "install"]:
            try:
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
                )
                self._json(201, result)
            except (RuntimePolicyError, ValueError) as exc:
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
