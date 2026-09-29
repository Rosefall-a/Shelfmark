"""Isolated Plugin Runtime service.

The runtime is the only component that loads plugin code. The host talks to
this service over an authenticated container-network boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote

_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ENTRYPOINT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*(?::[A-Za-z_][A-Za-z0-9_]*)?$")
_RESERVED_ENV = {
    "DATABASE_URL", "SECRET_KEY", "PRIMARY_USER_PASSWORD", "POSTGRES_PASSWORD",
    "DOCKER_HOST", "PLUGIN_GATEWAY_BOOTSTRAP_TOKEN", "PLUGIN_GATEWAY_SESSION_TOKEN",
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
            raise RuntimePolicyError("outbound network requires an approved network.outbound capability")
        if any(not host or any(char.isspace() for char in host) for host in self.allowed_hosts):
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
    ) -> None:
        self.root = root
        self.storage_root = storage_root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _limits(limits: ResourceLimits) -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (limits.address_space_bytes, limits.address_space_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files))
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.processes, limits.processes))

    @staticmethod
    def _sandbox_command(spec: PluginSpec, workdir: Path, package_dir: Path) -> list[str]:
        return [
            "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib", "--ro-bind", "/etc", "/etc",
            "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
            "--ro-bind", str(package_dir), "/plugin",
            "--bind", str(workdir), "/plugin-data", "--chdir", "/plugin", "--",
            *spec.command,
        ]

    def start(self, spec: PluginSpec, package_dir: Path) -> None:
        spec.validate()
        if not package_dir.is_dir():
            raise RuntimePolicyError("plugin package directory does not exist")
        with self._lock:
            if spec.plugin_id in self._processes and self._processes[spec.plugin_id].poll() is None:
                raise RuntimePolicyError("plugin is already running")
            workdir = self.root / spec.plugin_id
            if workdir.exists():
                for path in sorted(workdir.rglob("*"), reverse=True):
                    if path.is_file() or path.is_symlink():
                        path.unlink(missing_ok=True)
                    elif path.is_dir():
                        path.rmdir()
                workdir.rmdir()
            workdir.mkdir(mode=0o700, parents=True, exist_ok=False)
            environment = {
                "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/plugin-data",
                "TMPDIR": "/tmp", "PYTHONUNBUFFERED": "1",
                "PLUGIN_DATA_DIR": "/plugin-data", **spec.environment,
            }
            process = subprocess.Popen(
                self._sandbox_command(spec, workdir, package_dir),
                cwd=workdir, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                preexec_fn=lambda: self._limits(spec.resources),
            )
            self._processes[spec.plugin_id] = process

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
                self._processes.pop(plugin_id, None)
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
        return sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith("."))

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
            raise RuntimePolicyError("manifest plugin_id does not match package directory")
        if not _ENTRYPOINT.fullmatch(str(data.get("entrypoint", ""))):
            raise RuntimePolicyError("manifest has invalid entrypoint")
        return package, data

    @staticmethod
    def digest(package: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(p for p in package.rglob("*") if p.is_file() and not p.name.startswith(".runtime-state")):
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
        compatible = bool(expected) and self.digest(package).lower() == str(expected).lower()
        state = self._state()
        enabled = state.get(plugin_id, bool(data.get("enabled", True)))
        running = self.supervisor.running(plugin_id)
        return {
            "plugin_id": plugin_id, "name": data.get("name", plugin_id),
            "version": data.get("version", "0.0.0"), "compatible": compatible,
            "compatibility_reason": "" if compatible else "package integrity verification failed",
            "permissions": [p.get("capability", {}).get("name") for p in data.get("permissions", [])],
            "enabled": enabled, "status": "running" if running else ("stopped" if enabled else "disabled"),
            "health": "healthy" if running else "unknown",
        }

    def list(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for package in self.packages():
            try:
                result.append(self._item(package))
            except Exception as exc:
                result.append({
                    "plugin_id": package.name, "name": "Invalid plugin", "version": "0.0.0",
                    "compatible": False, "compatibility_reason": str(exc), "permissions": [],
                    "enabled": False, "status": "failed", "health": "unhealthy",
                })
        return result

    def ui(self, plugin_id: str) -> dict[str, Any]:
        package, manifest = self.package(plugin_id)
        ui_path = package / "ui.json"
        if not ui_path.is_file():
            return {
                "schema_version": "v1", "plugin_id": plugin_id, "title": manifest.get("name", plugin_id),
                "settings": [], "actions": [], "tables": [], "dialogs": [], "menus": [], "pages": [],
            }
        try:
            document = json.loads(ui_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimePolicyError("plugin UI document is invalid JSON") from exc
        if document.get("plugin_id") != plugin_id:
            raise RuntimePolicyError("plugin UI document has the wrong plugin_id")
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

    def start(self, plugin_id: str) -> None:
        package, manifest = self.package(plugin_id)
        item = self._item(package)
        if not item["compatible"]:
            raise RuntimePolicyError(item["compatibility_reason"])
        self.supervisor.start(PluginSpec(plugin_id, self._command(manifest)), package)
        state = self._state()
        state[plugin_id] = True
        self._save_state(state)

    def stop(self, plugin_id: str) -> None:
        self.package(plugin_id)
        self.supervisor.stop(plugin_id)
        state = self._state()
        state[plugin_id] = False
        self._save_state(state)

    def health(self, plugin_id: str) -> bool:
        self.package(plugin_id)
        return self.supervisor.running(plugin_id)

    def settings(self, plugin_id: str, values: dict[str, Any]) -> None:
        package, _ = self.package(plugin_id)
        path = package / ".settings.json"
        current: dict[str, Any] = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        current.update(values)
        path.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")

    def action(self, plugin_id: str, action_id: str, values: dict[str, Any]) -> None:
        document = self.ui(plugin_id)
        if action_id not in {action["id"] for action in document.get("actions", [])}:
            raise KeyError(action_id)
        del values

    def restore_enabled(self) -> None:
        state = self._state()
        for package in self.packages():
            try:
                plugin_id = self.package(package.name)[1]["plugin_id"]
                if state.get(plugin_id, True):
                    try:
                        self.start(plugin_id)
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
            self._json(401, {"detail": "runtime authentication required"}); return
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
            else:
                self._json(404, {"detail": "not found"})
        except KeyError:
            self._json(404, {"detail": "plugin not found"})
        except RuntimePolicyError as exc:
            self._json(422, {"detail": str(exc)})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(401, {"detail": "runtime authentication required"}); return
        parts = self._parts()
        try:
            if len(parts) == 3 and parts[0] == "plugins" and parts[2] in {"start", "stop"}:
                if parts[2] == "start": self.server.registry.start(parts[1])  # type: ignore[attr-defined]
                else: self.server.registry.stop(parts[1])  # type: ignore[attr-defined]
                self._json(200, {"plugin_id": parts[1], "status": parts[2]}); return
            if len(parts) == 4 and parts[0] == "plugins" and parts[2] == "actions":
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) if length else b"{}")
                self.server.registry.action(parts[1], parts[3], payload.get("values", {}))  # type: ignore[attr-defined]
                self._json(200, {"accepted": True}); return
            self._json(404, {"detail": "not found"})
        except KeyError:
            self._json(404, {"detail": "plugin not found"})
        except (RuntimePolicyError, ValueError, json.JSONDecodeError) as exc:
            self._json(422, {"detail": str(exc)})

    def do_PUT(self) -> None:
        if not self._authorized():
            self._json(401, {"detail": "runtime authentication required"}); return
        parts = self._parts()
        if len(parts) != 3 or parts[0] != "plugins" or parts[2] != "settings":
            self._json(404, {"detail": "not found"}); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) if length else b"{}")
            self.server.registry.settings(parts[1], payload)
            self._json(200, {"saved": True})
        except KeyError:
            self._json(404, {"detail": "plugin not found"})
        except (RuntimePolicyError, ValueError, json.JSONDecodeError) as exc:
            self._json(422, {"detail": str(exc)})

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
        (os.environ.get("PLUGIN_RUNTIME_HOST", "0.0.0.0"), int(os.environ.get("PLUGIN_RUNTIME_PORT", "8000"))),
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
