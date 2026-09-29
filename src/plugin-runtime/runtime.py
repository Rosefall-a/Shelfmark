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
import re
import resource
import signal
import shutil
import stat
import subprocess
import threading
import zipfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from storage import PluginStorage, StorageError
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import unquote

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
        self._logs: dict[str, deque[str]] = {}
        self._user_ids: dict[str, str | None] = {}
        self._storage_quotas: dict[str, int] = {}
        self._package_paths: dict[str, Path] = {}
        self._package_manifests: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _log(self, plugin_id: str, message: str) -> None:
        with self._lock:
            self._logs.setdefault(plugin_id, deque(maxlen=200)).append(message[:4000])

    def logs(self, plugin_id: str) -> list[str]:
        with self._lock:
            return list(self._logs.get(plugin_id, ()))

    def exit_code(self, plugin_id: str) -> int | None:
        with self._lock:
            return self._last_exit_codes.get(plugin_id)

    def _serve_stdout(self, plugin_id: str, process: subprocess.Popen[bytes]) -> None:
        if process.stdout is None:
            return
        for raw in iter(process.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("gateway request must be an object")
                response = self._handle_gateway_request(plugin_id, request)
            except Exception as exc:
                self._log(plugin_id, f"[gateway] request failed: {exc}")
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
                self._log(plugin_id, f"[stderr] {line}")

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
        self, plugin_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        method = str(request.get("method", ""))
        capability = str(request.get("capability", ""))
        payload = request.get("payload", {})
        if not isinstance(payload, dict):
            raise RuntimePolicyError("gateway payload must be an object")
        if method.startswith("storage."):
            manifest = self._manifest(plugin_id)
            permissions = {
                str(item.get("capability", {}).get("name"))
                for item in manifest.get("permissions", [])
                if isinstance(item, dict)
            }
            if "plugin.storage" not in permissions:
                raise RuntimePolicyError("plugin.storage permission is required")
        if method == "lifecycle.ready":
            self._log(
                plugin_id, f"[lifecycle] ready {json.dumps(payload, sort_keys=True)}"
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
        user_id = self._user_ids.get(plugin_id)
        if not user_id:
            raise RuntimePolicyError(
                "plugin has no user context; enable it from the Plugin Manager first"
            )
        body = json.dumps(
            {
                "plugin_id": plugin_id,
                "user_id": user_id,
                "method": method,
                "capability": capability,
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

    @staticmethod
    def _limits(limits: ResourceLimits) -> None:
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
            "1", "true", "yes", "on"
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
            "--bind",
            str(workdir),
            "/plugin-work",
            "--bind",
            str(self._storage(spec.plugin_id).root),
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
                "PLUGIN_DATA_DIR": str(self._storage(spec.plugin_id).root),
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
                    env=environment | {"HOME": str(package_dir) if self._nonbubble_enabled() else "/plugin"},
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
            return process

    def execute(
        self, spec: PluginSpec, package_dir: Path, payload: bytes, timeout: float = 30.0
    ) -> bytes:
        """Run a bounded, one-shot action handler in an isolated sandbox."""
        spec.validate()
        if len(payload) > 64 * 1024:
            raise RuntimePolicyError("plugin action payload exceeds 64 KiB")
        workdir = (
            self.root / f"{spec.plugin_id}.action-{os.getpid()}-{threading.get_ident()}"
        )
        workdir.mkdir(mode=0o700, parents=True, exist_ok=False)
        try:
            self._storage(spec.plugin_id)
            result = subprocess.run(
                self._sandbox_command(spec, workdir, package_dir),
                cwd=package_dir if self._nonbubble_enabled() else workdir,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "HOME": str(package_dir) if self._nonbubble_enabled() else "/plugin",
                    "PLUGIN_DATA_DIR": str(self._storage(spec.plugin_id).root),
                    "TMPDIR": "/tmp",
                    "PYTHONUNBUFFERED": "1",
                    **spec.environment,
                },
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                timeout=timeout,
                check=False,
                preexec_fn=lambda: self._limits(spec.resources),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimePolicyError("plugin action timed out") from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if result.returncode:
            raise RuntimePolicyError("plugin action handler failed")
        output = result.stdout or b""
        if len(output) > 64 * 1024:
            raise RuntimePolicyError("plugin action output exceeds 64 KiB")
        return output

    def stop(self, plugin_id: str, timeout: float = 5.0) -> None:
        with self._lock:
            process = self._processes.pop(plugin_id, None)
        if process is None:
            return
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
        with self._lock:
            process = self._processes.get(plugin_id)
            if process is None:
                return False
            if process.poll() is not None:
                self._last_exit_codes[plugin_id] = process.returncode
                self._processes.pop(plugin_id, None)
                self._package_paths.pop(plugin_id, None)
                self._package_manifests.pop(plugin_id, None)
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

    def _state(self) -> dict[str, bool]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict[str, bool]) -> None:
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
            "compatible": compatible,
            "compatibility_reason": ""
            if compatible
            else "package integrity verification failed",
            "permissions": [
                p.get("capability", {}).get("name") for p in data.get("permissions", [])
            ],
            "enabled": enabled,
            "status": "running" if running else ("stopped" if enabled else "disabled"),
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

    def install_package(self, package: bytes, filename: str, *, replace: bool = False) -> dict[str, Any]:
        if not filename.lower().endswith(".utp"):
            raise RuntimePolicyError("plugin packages must use the .utp extension")
        if not package:
            raise RuntimePolicyError("plugin package is empty")
        if len(package) > 64 * 1024 * 1024:
            raise RuntimePolicyError("plugin package exceeds the 64 MiB upload limit")

        try:
            archive = zipfile.ZipFile(io.BytesIO(package))
        except (OSError, zipfile.BadZipFile) as exc:
            raise RuntimePolicyError("invalid plugin package archive") from exc

        try:
            names: set[str] = set()
            manifest_data: bytes | None = None
            payload: list[tuple[str, bytes]] = []
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                if (
                    not info.filename
                    or path.is_absolute()
                    or ".." in path.parts
                    or "." in path.parts
                    or "\\" in info.filename
                ):
                    raise RuntimePolicyError("plugin package contains an unsafe path")
                if info.filename in names:
                    raise RuntimePolicyError("plugin package contains duplicate paths")
                names.add(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise RuntimePolicyError("plugin package contains a symbolic link")
                if info.is_dir():
                    if info.filename != "payload/" and not info.filename.startswith(
                        "payload/"
                    ):
                        raise RuntimePolicyError(
                            "plugin package contains an unsupported directory"
                        )
                    continue
                if info.filename == "manifest.json":
                    manifest_data = archive.read(info)
                elif info.filename.startswith("payload/"):
                    relative = info.filename[len("payload/") :]
                    if not relative:
                        raise RuntimePolicyError("payload entry must have a filename")
                    data = archive.read(info)
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
                backup = self.root / f".backup-{plugin_id}-{os.getpid()}-{threading.get_ident()}"
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
        if replace and isinstance(previous_state, dict):
            state = self._state()
            state[plugin_id] = previous_state
            self._save_state(state)
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

    def frontend(self, plugin_id: str, relative: str) -> dict[str, Any]:
        package, manifest = self.package(plugin_id)
        entry = str(manifest.get("frontend", {}).get("entry", "frontend/index.html"))
        relative = relative or entry
        path = package / Path(relative)
        try:
            path.resolve(strict=True).relative_to(package.resolve())
        except (OSError, ValueError) as exc:
            raise RuntimePolicyError("plugin frontend path escapes the package") from exc
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
            return {
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
        try:
            document = json.loads(ui_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimePolicyError("plugin UI document is invalid JSON") from exc
        if document.get("plugin_id") != plugin_id:
            raise RuntimePolicyError("plugin UI document has the wrong plugin_id")
        frontend = manifest.get("frontend")
        if isinstance(frontend, dict) and frontend.get("entry"):
            document["frontend"] = {"entry": str(frontend["entry"])}
        return document

    def _command(self, manifest: dict[str, Any]) -> tuple[str, ...]:
        module, _, function = str(manifest["entrypoint"]).partition(":")
        function = function or "main"
        script = (
            "import importlib; "
            f"m=importlib.import_module({module!r}); "
            f"f=getattr(m,{function!r}); f()"
        )
        return ("python", "-c", script)

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
            "result=f(json.load(sys.stdin)); "
            "raise SystemExit(0 if result is not False else 1)"
        )
        return ("python", "-c", script)

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
        quota_mb = manifest.get("storage", {}).get("quota_mb") or 64
        self.supervisor._storage_quotas[plugin_id] = int(quota_mb) * 1024 * 1024
        self.supervisor.start(PluginSpec(plugin_id, self._command(manifest)), package)
        state = self._state()
        state[plugin_id] = {
            "enabled": True,
            "user_id": self.supervisor._user_ids.get(plugin_id),
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
        }
        self._save_state(state)

    def logs(self, plugin_id: str) -> list[str]:
        self.package(plugin_id)
        return self.supervisor.logs(plugin_id)

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
        self, plugin_id: str, action_id: str, values: dict[str, Any]
    ) -> dict[str, bool]:
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
            PluginSpec(plugin_id, self._action_command(handler)), package, payload
        )
        if output:
            try:
                message = json.loads(output.decode("utf-8").strip())
            except (UnicodeDecodeError, ValueError) as exc:
                raise RuntimePolicyError(
                    "plugin action returned invalid output"
                ) from exc
            webhook = (
                message.get("discord_webhook") if isinstance(message, dict) else None
            )
            if webhook is not None:
                capabilities = {
                    item.get("name") for item in manifest.get("capabilities", [])
                }
                if "notifications.send" not in capabilities:
                    raise RuntimePolicyError(
                        "plugin action requested Discord delivery without notifications.send"
                    )
                content = message.get("content")
                if (
                    not isinstance(webhook, str)
                    or not isinstance(content, str)
                    or not content.strip()
                ):
                    raise RuntimePolicyError(
                        "Discord delivery requires a webhook URL and message"
                    )
                if (
                    os.getenv("PLUGIN_RUNTIME_DISCORD_EGRESS", "false").lower()
                    != "true"
                ):
                    raise RuntimePolicyError(
                        "Discord egress is disabled in this runtime"
                    )
                self._discord_webhook(webhook, content)
        return {"completed": True}

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
                self._json(200, {"logs": self.server.registry.logs(parts[1])})  # type: ignore[attr-defined]
            elif len(parts) >= 3 and parts[0] == "plugins" and parts[2] == "frontend":
                relative = "/".join(parts[3:])
                self._json(200, self.server.registry.frontend(parts[1], relative))  # type: ignore[attr-defined]
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
                self.server.registry.storage_put(parts[1], str(payload.get("key", "")), str(payload.get("value", "")))  # type: ignore[attr-defined]
                self._json(200, {"saved": True})
                return
            if len(parts) == 4 and parts[0] == "plugins" and parts[2] == "actions":
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) if length else b"{}")
                result = self.server.registry.action(
                    parts[1], parts[3], payload.get("values", {})
                )  # type: ignore[attr-defined]
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
                result = self.server.registry.install_package(  # type: ignore[attr-defined]
                    package,
                    self.headers.get("X-Plugin-Package-Name", ""),
                    replace=self.headers.get("X-Plugin-Replace", "").lower() == "true",
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
