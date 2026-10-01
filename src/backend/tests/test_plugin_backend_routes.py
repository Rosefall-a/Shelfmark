"""Security and lifecycle coverage for host-mediated plugin backend routes."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api.routes import plugins
from src.plugin_api.backend_routes import (
    BackendRouteConflictError,
    resolve_backend_route,
    validate_host_route_ownership,
)
from src.plugin_api.contracts import BackendRouteScope


def route_declaration(
    *,
    route_id: str = "hello",
    scope: str = "plugin",
    path: str = "hello/{item_id}",
    authorization: str = "authenticated",
) -> dict:
    return {
        "id": route_id,
        "scope": scope,
        "path": path,
        "methods": ["POST"],
        "handler": "plugin:handle",
        "authorization": authorization,
    }


def installed_plugin(**changes) -> dict:
    plugin = {
        "plugin_id": "example.routes",
        "installation_id": str(uuid4()),
        "enabled": True,
        "compatible": True,
        "status": "running",
        "health": "healthy",
        "backend_routes": [route_declaration()],
    }
    plugin.update(changes)
    return plugin


def request_for(path: str, *, body: bytes = b"{}") -> Request:
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"view=summary",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"authorization", b"Bearer must-not-reach-plugin"),
            ],
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
        },
        receive,
    )


@pytest.mark.asyncio
async def test_plugin_routes_authenticate_after_a_declared_route_matches(monkeypatch) -> None:
    plugin = installed_plugin()
    user = SimpleNamespace(id=uuid4(), username="alice", is_admin=False)
    client = SimpleNamespace(
        plugins=AsyncMock(return_value=[plugin]),
        route=AsyncMock(return_value={"status_code": 200, "body": {"ok": True}}),
    )
    authenticate = AsyncMock(return_value=user)
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(plugins, "get_current_user", authenticate)
    monkeypatch.setattr(plugins, "has_capability_grant", AsyncMock(return_value=True))

    request = request_for("/api/plugins/example.routes/hello/42")
    response = await plugins._dispatch_backend_route(
        request,
        scope=BackendRouteScope.PLUGIN,
        route_path="hello/42",
        plugin_id="example.routes",
        db=ANY,
    )

    assert response.status_code == 200
    authenticate.assert_awaited_once_with(ANY, "Bearer must-not-reach-plugin", None)


@pytest.mark.asyncio
async def test_unknown_host_route_remains_a_not_found_without_authentication(monkeypatch) -> None:
    authenticate = AsyncMock()
    monkeypatch.setattr(
        plugins,
        "_client",
        SimpleNamespace(plugins=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(plugins, "get_current_user", authenticate)

    with pytest.raises(HTTPException) as missing:
        await plugins._dispatch_backend_route(
            request_for("/api/not-owned-by-a-plugin"),
            scope=BackendRouteScope.HOST,
            route_path="/api/not-owned-by-a-plugin",
            db=ANY,
        )

    assert missing.value.status_code == 404
    authenticate.assert_not_awaited()


@pytest.mark.asyncio
async def test_namespaced_route_uses_authenticated_user_and_installation_grant(monkeypatch) -> None:
    plugin = installed_plugin()
    client = SimpleNamespace(
        plugins=AsyncMock(return_value=[plugin]),
        route=AsyncMock(return_value={"status_code": 200, "body": {"ok": True}}),
    )
    grant = AsyncMock(return_value=True)
    user = SimpleNamespace(id=uuid4(), username="alice", is_admin=False)
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(plugins, "has_capability_grant", grant)

    response = await plugins._dispatch_backend_route(
        request_for("/api/plugins/example.routes/hello/42"),
        scope=BackendRouteScope.PLUGIN,
        route_path="hello/42",
        plugin_id="example.routes",
        db=ANY,
        user=user,
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"ok": True}
    grant.assert_awaited_once_with(
        ANY,
        plugin_id="example.routes",
        installation_id=UUID(plugin["installation_id"]),
        capability="backend.routes.plugin",
        user_id=user.id,
    )
    route_request = client.route.await_args.args[2]
    assert route_request["path_parameters"] == {"item_id": "42"}
    assert route_request["user"] == {
        "id": str(user.id),
        "username": "alice",
        "is_admin": False,
    }
    assert "authorization" not in route_request["headers"]
    assert client.route.await_args.kwargs["user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_route_capability_denial_never_executes_plugin(monkeypatch) -> None:
    client = SimpleNamespace(
        plugins=AsyncMock(return_value=[installed_plugin()]),
        route=AsyncMock(),
    )
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(plugins, "has_capability_grant", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as denied:
        await plugins._dispatch_backend_route(
            request_for("/api/plugins/example.routes/hello/42"),
            scope=BackendRouteScope.PLUGIN,
            route_path="hello/42",
            plugin_id="example.routes",
            db=ANY,
            user=SimpleNamespace(id=uuid4(), username="alice", is_admin=False),
        )

    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "forbidden"
    client.route.assert_not_awaited()


@pytest.mark.asyncio
async def test_privileged_host_route_requires_admin_and_host_capability(monkeypatch) -> None:
    plugin = installed_plugin(
        backend_routes=[
            route_declaration(
                route_id="audit",
                scope="host",
                path="/api/plugin-audit/{item_id}",
                authorization="admin",
            )
        ]
    )
    client = SimpleNamespace(
        plugins=AsyncMock(return_value=[plugin]),
        route=AsyncMock(return_value={"status_code": 200, "body": {"audited": True}}),
    )
    grant = AsyncMock(return_value=True)
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(plugins, "has_capability_grant", grant)

    with pytest.raises(HTTPException) as denied:
        await plugins._dispatch_backend_route(
            request_for("/api/plugin-audit/42"),
            scope=BackendRouteScope.HOST,
            route_path="/api/plugin-audit/42",
            db=ANY,
            user=SimpleNamespace(id=uuid4(), username="alice", is_admin=False),
        )
    assert denied.value.status_code == 403
    grant.assert_not_awaited()

    admin = SimpleNamespace(id=uuid4(), username="admin", is_admin=True)
    response = await plugins._dispatch_backend_route(
        request_for("/api/plugin-audit/42"),
        scope=BackendRouteScope.HOST,
        route_path="/api/plugin-audit/42",
        db=ANY,
        user=admin,
    )
    assert response.status_code == 200
    assert grant.await_args.kwargs["capability"] == "backend.routes.host"


def test_conflicting_host_route_ownership_is_rejected() -> None:
    first = installed_plugin(
        plugin_id="example.first",
        backend_routes=[route_declaration(scope="host", path="/api/reports/{report_id}")],
    )
    second = installed_plugin(
        plugin_id="example.second",
        backend_routes=[route_declaration(scope="host", path="/api/reports/current")],
    )
    with pytest.raises(BackendRouteConflictError):
        validate_host_route_ownership([first, second])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False, "status": "disabled"},
        {"status": "failed", "health": "unhealthy"},
    ],
)
async def test_disabled_or_failed_plugin_cannot_serve_routes(monkeypatch, changes) -> None:
    client = SimpleNamespace(
        plugins=AsyncMock(return_value=[installed_plugin(**changes)]),
        route=AsyncMock(),
    )
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(plugins, "has_capability_grant", AsyncMock(return_value=True))

    with pytest.raises(HTTPException) as unavailable:
        await plugins._dispatch_backend_route(
            request_for("/api/plugins/example.routes/hello/42"),
            scope=BackendRouteScope.PLUGIN,
            route_path="hello/42",
            plugin_id="example.routes",
            db=ANY,
            user=SimpleNamespace(id=uuid4(), username="alice", is_admin=False),
        )
    assert unavailable.value.status_code == 409
    client.route.assert_not_awaited()


def test_uninstall_and_update_change_the_live_route_set() -> None:
    old = installed_plugin()
    assert (
        resolve_backend_route(
            [old],
            scope=BackendRouteScope.PLUGIN,
            path="hello/42",
            method="POST",
            plugin_id="example.routes",
        )
        is not None
    )
    assert (
        resolve_backend_route(
            [],
            scope=BackendRouteScope.PLUGIN,
            path="hello/42",
            method="POST",
            plugin_id="example.routes",
        )
        is None
    )
    updated = installed_plugin(
        backend_routes=[route_declaration(route_id="new", path="new/{item_id}")]
    )
    assert (
        resolve_backend_route(
            [updated],
            scope=BackendRouteScope.PLUGIN,
            path="hello/42",
            method="POST",
            plugin_id="example.routes",
        )
        is None
    )
    assert (
        resolve_backend_route(
            [updated],
            scope=BackendRouteScope.PLUGIN,
            path="new/42",
            method="POST",
            plugin_id="example.routes",
        ).route.id
        == "new"
    )


@pytest.mark.asyncio
async def test_malformed_plugin_request_is_rejected_before_execution() -> None:
    with pytest.raises(HTTPException) as malformed:
        await plugins._backend_route_request(
            request_for("/api/plugins/example.routes/hello/42", body=b"not-json"),
            {},
        )
    assert malformed.value.status_code == 400
    assert malformed.value.detail["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_non_json_safe_plugin_response_is_rejected(monkeypatch) -> None:
    client = SimpleNamespace(
        plugins=AsyncMock(return_value=[installed_plugin()]),
        route=AsyncMock(return_value={"status_code": 200, "body": {"value": float("nan")}}),
    )
    monkeypatch.setattr(plugins, "_client", client)
    monkeypatch.setattr(plugins, "has_capability_grant", AsyncMock(return_value=True))

    with pytest.raises(HTTPException) as invalid:
        await plugins._dispatch_backend_route(
            request_for("/api/plugins/example.routes/hello/42"),
            scope=BackendRouteScope.PLUGIN,
            route_path="hello/42",
            plugin_id="example.routes",
            db=ANY,
            user=SimpleNamespace(id=uuid4(), username="alice", is_admin=False),
        )

    assert invalid.value.status_code == 502
    assert invalid.value.detail["message"] == "Plugin returned an invalid route response."
