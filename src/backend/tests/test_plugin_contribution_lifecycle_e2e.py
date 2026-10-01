"""Exercise host HTTP boundaries against the actual runtime service and registry."""

from __future__ import annotations

import importlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.api.routes import plugins
from src.features.notification_providers import registry as providers
from src.plugin_api.runtime_client import PluginRuntimeClient


@pytest.mark.asyncio
async def test_lifecycle_revokes_all_host_execution_boundaries(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "plugin-runtime"))
    runtime = importlib.import_module("runtime")
    plugin_id = "contract.lifecycle"
    installation_id = uuid4()
    user = SimpleNamespace(id=uuid4(), username="admin", is_admin=True)
    token = "lifecycle-contract-token-" + "x" * 40
    monkeypatch.setenv("PLUGIN_RUNTIME_TOKEN", token)
    package = tmp_path / "packages" / plugin_id
    (package / "native").mkdir(parents=True)
    (package / "native" / "index.js").write_text("// contract asset", encoding="utf-8")
    document = {
        "plugin_id": plugin_id,
        "title": "Lifecycle contract",
        "pages": [{"id": "dashboard", "title": "Dashboard"}],
        "actions": [{"id": "run", "label": "Run", "handler": "contract:run"}],
        "navigation": [
            {"id": "nav", "location": "main.sidebar", "label": "Contract", "page_id": "dashboard"}
        ],
        "settings_sections": [{"id": "settings", "label": "Contract", "page_id": "dashboard"}],
        "extensions": [{"id": "extension", "slot": "home.after-widgets", "page_id": "dashboard"}],
        "overlays": [{"id": "overlay", "page_id": "dashboard"}],
        "contextual_actions": [
            {"id": "context", "location": "game", "label": "Run", "action_id": "run"}
        ],
        "page_replacements": [{"id": "replacement", "page": "home", "page_id": "dashboard"}],
    }
    (package / "ui.json").write_text(json.dumps(document), encoding="utf-8")
    manifest = {
        "plugin_id": plugin_id,
        "entrypoint": "contract:main",
        "version": "1.0.0",
        "native_frontend": {"entry": "native/index.js"},
        "backend_routes": [
            {
                "id": "route",
                "scope": "host",
                "path": "/api/contract-lifecycle",
                "methods": ["POST"],
                "handler": "contract:route",
            }
        ],
        "integrity": {"sha256": runtime.PluginRegistry.digest(package)},
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    supervisor = runtime.PluginSupervisor(root=tmp_path / "work", storage_root=tmp_path / "storage")
    registry = runtime.PluginRegistry(package.parent, supervisor)
    registry._transition(plugin_id, enabled=False, installation_id=str(installation_id))
    live = {"running": False}
    observed = []

    def start(_spec, _package):
        observed.append(registry.list()[0]["status"])
        live["running"] = True

    def stop(_plugin_id):
        observed.append(registry.list()[0]["status"])
        live["running"] = False

    monkeypatch.setattr(supervisor, "start", start)
    monkeypatch.setattr(supervisor, "stop", stop)
    monkeypatch.setattr(supervisor, "running", lambda _: live["running"])
    execute = Mock(return_value=b'{"status_code":200,"body":{"ok":true}}')
    monkeypatch.setattr(supervisor, "execute", execute)
    server = runtime.RuntimeServer(("127.0.0.1", 0), runtime.RuntimeHandler)
    server.registry = registry
    server.token = token
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    runtime_client = PluginRuntimeClient(f"http://127.0.0.1:{server.server_port}", token)
    monkeypatch.setattr(plugins, "_client", runtime_client)
    monkeypatch.setattr(providers, "PluginRuntimeClient", lambda: runtime_client)
    monkeypatch.setattr(plugins, "has_capability_grant", AsyncMock(return_value=True))
    dispatch = AsyncMock(return_value={"events": []})
    monkeypatch.setattr(plugins, "dispatch_gateway_request", dispatch)
    registration = SimpleNamespace(
        plugin_id=plugin_id,
        installation_id=installation_id,
        provider_id=f"{plugin_id}.provider",
        name="Contract",
        action_id="run",
    )
    db = AsyncMock()
    db.execute.return_value = [
        (capability, 1)
        for capability in (
            "frontend.navigation",
            "frontend.page.extend",
            "frontend.settings",
            "frontend.overlay",
            "frontend.context.game",
            "frontend.page.replace.home",
            "frontend.native",
        )
    ]
    db.scalars.return_value = SimpleNamespace(all=lambda: [registration])
    app = FastAPI()
    app.include_router(plugins.router)
    app.include_router(plugins.host_router)
    app.dependency_overrides[plugins.get_db] = lambda: db
    app.dependency_overrides[plugins.get_current_user] = lambda: user
    app.dependency_overrides[plugins.get_current_admin] = lambda: user
    monkeypatch.setattr(plugins, "get_current_user", AsyncMock(return_value=user))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://host"
        ) as client:
            for status in (
                "enabled",
                "disabled",
                "starting",
                "running",
                "stopping",
                "failed",
                "quarantined",
                "running",
            ):
                registry._transition(plugin_id, enabled=status != "disabled", status=status)
                live["running"] = status == "running"
                execute.reset_mock()
                dispatch.reset_mock()
                expected = 200 if status == "running" else 409
                assert (await client.get(f"/api/plugins/{plugin_id}/ui")).status_code == expected
                assert (
                    await client.get(f"/api/plugins/{plugin_id}/native-frontend/native/index.js")
                ).status_code == expected
                assert (
                    await client.post(f"/api/plugins/{plugin_id}/actions/run", json={"values": {}})
                ).status_code == expected
                assert (
                    await client.post("/api/contract-lifecycle", json={})
                ).status_code == expected
                gateway_request = {
                    "plugin_id": plugin_id,
                    "installation_id": str(installation_id),
                    "request_id": str(uuid4()),
                    "user_id": str(user.id),
                    "method": "events.poll",
                    "capability": "events.subscribe",
                    "payload": {},
                }
                for method, capability in (
                    ("events.poll", "events.subscribe"),
                    ("notification_providers.register", "notification_providers.register"),
                ):
                    gateway_request.update(method=method, capability=capability)
                    response = await client.post(
                        "/api/plugins/runtime/gateway",
                        json=gateway_request,
                        headers={"X-Plugin-Runtime-Token": token},
                    )
                    assert response.status_code == expected
                active_providers = await providers.get_notification_providers(db)
                assert bool(active_providers) == (status == "running")
                # The disabled/quarantined owner still reserves its backend declaration.
                summary = (await client.get("/api/plugins")).json()[0]
                assert summary["backend_routes"][0]["path"] == "/api/contract-lifecycle"
                if status != "running":
                    execute.assert_not_called()
                    dispatch.assert_not_awaited()
            registry.stop(plugin_id)
            assert observed[-1] == "stopping"
            registry.start(plugin_id, user_id=str(user.id))
            assert observed[-1] == "starting"
            registry.quarantine(plugin_id)
            await client.post(f"/api/plugins/{plugin_id}/disable")
            assert registry.list()[0]["status"] == "quarantined"
            with pytest.raises(runtime.RuntimePolicyError, match="recovered"):
                registry.start(plugin_id)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
