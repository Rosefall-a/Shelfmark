"""Durable host inventory and staged packages, independent of runtime discovery."""

from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any


class ManagerState:
    """Atomic host state using the same persistent volume as catalogue configuration."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        with self.lock:
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {
                    "version": 1,
                    "plugins": {},
                    "settings": {
                        "automatic_updates": False,
                        "retained_versions": 1,
                    },
                }
            if state.get("version") != 1:
                raise ValueError("Unsupported plugin manager state schema")
            return state

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)

    def patch(self, plugin_id: str, /, **changes: Any) -> dict[str, Any]:
        with self.lock:
            state = self.read()
            record = state["plugins"].setdefault(plugin_id, {"plugin_id": plugin_id})
            record.update(changes)
            self._save(state)
            return dict(record)

    def reconcile(self, plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Runtime reports health; an unavailable runtime never erases installations."""
        with self.lock:
            state = self.read()
            seen = {plugin["plugin_id"] for plugin in plugins}
            for plugin_id, record in state["plugins"].items():
                if plugin_id not in seen:
                    record.update(
                        runtime_available=True,
                        status="failed",
                        health="unhealthy",
                        runtime_error="Installed package is missing from the runtime registry.",
                    )
            for plugin in plugins:
                record = state["plugins"].setdefault(plugin["plugin_id"], {})
                record.update(plugin)
                record["runtime_available"] = True
                record.pop("runtime_error", None)
            self._save(state)
            return [dict(item) for item in state["plugins"].values()]

    def settings(self, changes: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.lock:
            state = self.read()
            if changes is not None:
                state["settings"].update(changes)
                self._save(state)
            return dict(state["settings"])

    def remove(self, plugin_id: str) -> None:
        with self.lock:
            state = self.read()
            state["plugins"].pop(plugin_id, None)
            self._save(state)
            self.stage_path(plugin_id).unlink(missing_ok=True)

    def stage_path(self, plugin_id: str) -> Path:
        # IDs originate in validated manifests, but don't trust API input paths.
        import hashlib

        name = hashlib.sha256(plugin_id.encode()).hexdigest()
        return self.path.parent / "plugin-staging" / f"{name}.utp"

    def stage(self, plugin_id: str, package: bytes, metadata: dict[str, Any]) -> None:
        with self.lock:
            path = self.stage_path(plugin_id)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(package)
            temporary.replace(path)
            self.patch(plugin_id, staged_update=metadata)


@lru_cache
def _store(path: str) -> ManagerState:
    return ManagerState(Path(path))


def manager_state() -> ManagerState:
    """Resolve configuration at use time, including isolated test deployments."""
    return _store(os.getenv("PLUGIN_MANAGER_STATE_PATH", "/data/plugin-manager.json"))
