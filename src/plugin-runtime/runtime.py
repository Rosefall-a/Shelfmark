"""Plugin Runtime supervisor and sandbox contract.

The runtime is deliberately small: plugin processes are children of one
unprivileged supervisor, while bubblewrap provides per-plugin Linux
namespaces and a private filesystem view. Core authentication and capability
authorization remain outside this module.
"""

from __future__ import annotations

import os
import re
import resource
import signal
import subprocess
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping

from storage import PluginStorage

_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
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
    """Per-plugin process limits enforced before exec."""

    cpu_seconds: int = 60
    address_space_bytes: int = 256 * 1024 * 1024
    open_files: int = 256
    processes: int = 32


@dataclass(frozen=True)
class OutboundNetworkPolicy:
    """Default-deny outbound policy for a plugin declaration.

    The container deliberately provides no direct external network to plugin
    sandboxes. A non-empty declaration is therefore only accepted when the
    gateway has explicitly approved the network.outbound capability and
    an egress broker is configured by a later runtime integration.
    """

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
        for host in self.allowed_hosts:
            if not host or any(char.isspace() for char in host):
                raise RuntimePolicyError("outbound hosts must be non-empty hostnames")
        if any(port < 1 or port > 65535 for port in self.allowed_ports):
            raise RuntimePolicyError("outbound ports must be between 1 and 65535")


@dataclass(frozen=True)
class PluginSpec:
    """Validated information required to launch one plugin process."""

    plugin_id: str
    command: tuple[str, ...]
    environment: Mapping[str, str] = field(default_factory=dict)
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    network: OutboundNetworkPolicy = field(default_factory=OutboundNetworkPolicy)

    def validate(self) -> None:
        if not _PLUGIN_ID.fullmatch(self.plugin_id):
            raise RuntimePolicyError("invalid plugin id")
        if not self.command or any(not part for part in self.command):
            raise RuntimePolicyError("plugin command must not be empty")
        if any(name in _RESERVED_ENV for name in self.environment):
            raise RuntimePolicyError("plugin cannot receive core or gateway secrets")
        if self.resources.cpu_seconds < 1 or self.resources.address_space_bytes < 1:
            raise RuntimePolicyError("resource limits must be positive")
        if self.resources.open_files < 16 or self.resources.processes < 1:
            raise RuntimePolicyError("resource limits are too small")
        self.network.validate()


class PluginSupervisor:
    """Launch and stop plugins with independent process/filesystem boundaries."""

    def __init__(
        self,
        root: Path = Path("/tmp/plugins"),
        storage_root: Path = Path("/var/lib/unnamed-tracking/plugins"),
    ) -> None:
        self.root = root
        self.storage_root = storage_root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._log_threads: dict[str, tuple[object, object]] = {}

    def storage(self, plugin_id: str, *, quota_bytes: int) -> PluginStorage:
        """Return storage permanently bound to one plugin identity."""
        return PluginStorage(self.storage_root, plugin_id, quota_bytes=quota_bytes)

    @staticmethod
    def _limits(limits: ResourceLimits) -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(
            resource.RLIMIT_AS,
            (limits.address_space_bytes, limits.address_space_bytes),
        )
        resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files))
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.processes, limits.processes))

    @staticmethod
    def _sandbox_command(spec: PluginSpec, workdir: Path) -> list[str]:
        # --unshare-all includes private PID, IPC, UTS and network namespaces.
        # The network namespace intentionally has only loopback: plugins cannot
        # bypass the declared/approved egress contract with raw sockets.
        return [
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/etc", "/etc",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--bind", str(workdir), "/plugin",
            "--chdir", "/plugin",
            "--",
            *spec.command,
        ]

    def start(self, spec: PluginSpec) -> subprocess.Popen[bytes]:
        """Validate and start a plugin; duplicate plugin IDs are rejected."""
        spec.validate()
        if spec.plugin_id in self._processes:
            raise RuntimePolicyError("plugin is already running")

        workdir = self.root / spec.plugin_id
        workdir.mkdir(mode=0o700, parents=True, exist_ok=False)
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/plugin",
            "TMPDIR": "/tmp",
            "PYTHONUNBUFFERED": "1",
            **spec.environment,
        }
        process = subprocess.Popen(
            self._sandbox_command(spec, workdir),
            cwd=workdir,
            env=environment,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=lambda: self._limits(spec.resources),
        )
        self._processes[spec.plugin_id] = process
        return process

    def stop(self, plugin_id: str, timeout: float = 5.0) -> None:
        """Terminate one plugin process group and clean its private directory."""
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
            for path in sorted(workdir.rglob("*"), reverse=True):
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    path.rmdir()
            workdir.rmdir()

    def stop_all(self) -> None:
        """Stop all managed plugins."""
        for plugin_id in list(self._processes):
            self.stop(plugin_id)


class RuntimeHandler(BaseHTTPRequestHandler):
    """Expose only a health endpoint; plugin processes are never HTTP-public."""

    server_version = "UnnamedTrackingPluginRuntime/0.2"

    def do_GET(self) -> None:
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    """Run the runtime gateway/bootstrap health process."""
    host = os.environ.get("PLUGIN_RUNTIME_HOST", "0.0.0.0")
    port = int(os.environ.get("PLUGIN_RUNTIME_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), RuntimeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
