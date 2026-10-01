"""HTTP authorization regressions using persisted rows and the real grant resolver.

Only the isolated runtime transport is replaced. SQLite executes the production
SQLAlchemy grant/domain queries; the adapter supplies the async session interface.
No permission decision or grant lookup is mocked.
"""

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from src.api.routes import plugin_permissions, plugins
from src.core.auth import hash_token
from src.database.models.achievement import Achievement  # noqa: F401
from src.database.models.auth import UserSession
from src.database.models.notification import Notification
from src.database.models.notification_delivery import NotificationDelivery
from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.plugin_notification_provider import PluginNotificationProviderRegistration
from src.database.models.plugin_permissions import PluginPermissionGrant, PluginPermissionRequest
from src.database.models.user import User
from src.database.session import get_db
from src.features.notification_providers.base import NotificationMessage
from src.features.notification_providers.plugin import PluginNotificationProvider
from src.plugin_api.grants import has_capability_grant


class PersistedDb:
    """Execute actual SQL with a synchronous test driver behind async methods."""

    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    def add(self, row):
        self.session.add(row)

    async def commit(self):
        self.session.commit()

    async def refresh(self, row):
        self.session.refresh(row)

    async def flush(self):
        self.session.flush()


@pytest.fixture
def boundary(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (
        User,
        PluginPermissionGrant,
        PluginPermissionRequest,
        UserSession,
        PluginNotificationProviderRegistration,
        Notification,
        NotificationDelivery,
        NotificationProviderSetting,
    ):
        model.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as session:
        users = [
            User(
                id=uuid4(),
                username=name,
                email=f"{name}@example.test",
                password_hash="unused",
                is_admin=True,
            )
            for name in ("alice", "bob")
        ]
        session.add_all(users)
        tokens = {user.id: str(uuid4()) for user in users}
        sessions = [
            UserSession(
                id=uuid4(),
                user_id=user.id,
                token_hash=hash_token(tokens[user.id]),
                expires_at=9999999999,
                created_at=1,
            )
            for user in users
        ]
        session.add_all(sessions)
        session.commit()
        installation_id = uuid4()
        plugin = {
            "plugin_id": "audit.plugin",
            "installation_id": str(installation_id),
            "enabled": True,
            "compatible": True,
            "status": "running",
            "health": "healthy",
            "permissions": ["sessions.read", "frontend.native", "backend.routes"],
            "capabilities": [{"name": "api.full", "version": 1}],
            "backend_routes": [
                {
                    "id": "probe",
                    "scope": "plugin",
                    "path": "probe",
                    "methods": ["POST"],
                    "handler": "entry:probe",
                },
                {
                    "id": "host",
                    "scope": "host",
                    "path": "/api/audit-probe",
                    "methods": ["POST"],
                    "handler": "entry:probe",
                },
            ],
        }
        document = {
            "plugin_id": "audit.plugin",
            "title": "Audit",
            "pages": [{"id": "page", "title": "Audit"}],
            "actions": [
                {
                    "id": "read",
                    "label": "Read",
                    "capability": {"name": "sessions.read", "version": 1},
                }
            ],
            "native_frontend": {"entry": "native/index.js"},
            "page_replacements": [
                {"id": "home", "page": "home", "page_id": "page"},
                {"id": "settings", "page": "settings", "page_id": "page"},
            ],
        }
        runtime = SimpleNamespace(
            plugins=AsyncMock(return_value=[plugin]),
            plugin_ui=AsyncMock(return_value=document),
            action=AsyncMock(return_value={"completed": True}),
            route=AsyncMock(return_value={"body": {"ok": True}}),
            native_frontend_asset=AsyncMock(return_value=b"export default {}"),
        )
        current = {"user": users[0]}

        db = PersistedDb(session)

        async def database():
            yield db

        monkeypatch.setattr(plugins, "_client", runtime)
        monkeypatch.setenv("PLUGIN_RUNTIME_TOKEN", "x" * 32)
        app = FastAPI()
        app.include_router(plugins.router)
        app.include_router(plugin_permissions.router)
        app.include_router(plugins.host_router)
        app.dependency_overrides[get_db] = database
        yield SimpleNamespace(
            app=app,
            session=session,
            db=db,
            users=users,
            sessions=sessions,
            current=current,
            plugin=plugin,
            installation_id=installation_id,
            runtime=runtime,
            tokens=tokens,
        )
    engine.dispose()


def grant(boundary, capability="sessions.read", **changes):
    values = {
        "plugin_id": "audit.plugin",
        "installation_id": boundary.installation_id,
        "capability": capability,
        "capability_version": 1,
    }
    values.update(changes)
    row = PluginPermissionGrant(**values)
    boundary.session.add(row)
    boundary.session.commit()
    return row


async def request(boundary, path="/api/plugins/runtime/gateway", **changes):
    body = {
        "plugin_id": "audit.plugin",
        "installation_id": str(boundary.installation_id),
        "request_id": str(uuid4()),
        "user_id": str(boundary.current["user"].id),
        "method": "sessions.list",
        "capability": "sessions.read",
    }
    if path != "/api/plugins/runtime/gateway":
        body = {}
    body.update(changes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app),
        base_url="http://test",
        cookies={"session": boundary.tokens[boundary.current["user"].id]},
    ) as client:
        return await client.post(path, json=body, headers={"X-Plugin-Runtime-Token": "x" * 32})


@pytest.mark.asyncio
async def test_declarations_and_pending_request_never_grant_access(boundary):
    boundary.session.add(
        PluginPermissionRequest(
            plugin_id="audit.plugin",
            installation_id=boundary.installation_id,
            capability="sessions.read",
            capability_version=1,
            rationale="Declared and requested",
        )
    )
    boundary.session.commit()
    assert (await request(boundary)).status_code == 403
    assert (
        await request(boundary, "/api/plugins/audit.plugin/actions/read", values={})
    ).status_code == 403
    assert (await request(boundary, "/api/plugins/audit.plugin/probe")).status_code == 403
    boundary.runtime.action.assert_not_awaited()
    boundary.runtime.route.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"installation_id": uuid4()},
        {"plugin_id": "other.plugin"},
        {"user_id": uuid4()},
        {"device_id": uuid4()},
        {"revoked_at": 1},
        {"capability_version": 2},
    ],
)
async def test_persisted_grant_identity_scope_revocation_and_version(boundary, changes):
    grant(boundary, **changes)
    assert (await request(boundary)).status_code == 403


@pytest.mark.asyncio
async def test_live_installation_rejects_old_request_even_with_old_grant(boundary):
    grant(boundary)
    boundary.plugin["installation_id"] = str(uuid4())
    assert (await request(boundary)).status_code == 409


@pytest.mark.asyncio
async def test_parent_child_and_explicit_full_api(boundary):
    row = grant(boundary, "sessions")
    response = await request(boundary)
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["payload"]["sessions"]] == [
        str(boundary.sessions[0].id)
    ]
    row.capability = "sessions.read"
    boundary.session.commit()
    assert (await request(boundary, capability="sessions")).status_code == 403
    assert (await request(boundary, capability="api.full")).status_code == 403
    grant(boundary, "api.full")
    assert (await request(boundary, capability="api.full")).status_code == 200


@pytest.mark.asyncio
async def test_users_cannot_share_scoped_grants_or_domain_rows(boundary):
    grant(boundary, user_id=boundary.users[0].id)
    assert (await request(boundary)).status_code == 200
    boundary.current["user"] = boundary.users[1]
    assert (await request(boundary)).status_code == 403
    grant(boundary, user_id=boundary.users[1].id)
    response = await request(boundary)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["payload"]["sessions"]] == [
        str(boundary.sessions[1].id)
    ]


@pytest.mark.asyncio
async def test_untrusted_device_claims_cannot_use_device_grants(boundary):
    device_id = uuid4()
    grant(boundary, device_id=device_id)
    # The runtime transport has no authenticated device identity. A caller's
    # matching device_id must not manufacture one.
    for claimed in (device_id, uuid4()):
        assert (await request(boundary, device_id=str(claimed))).status_code == 422


@pytest.mark.asyncio
async def test_http_revocation_immediately_stops_next_request(boundary):
    row = grant(boundary)
    assert (await request(boundary)).status_code == 200
    response = await request(boundary, f"/api/plugin-permissions/grants/{row.id}/revoke")
    assert response.status_code == 200
    assert (await request(boundary)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        {"enabled": False},
        {"compatible": False},
        {"status": "quarantined"},
        {"status": "failed"},
        {"health": "unhealthy"},
        {"status": "unknown"},
    ],
)
async def test_unavailable_installations_cannot_execute_any_entrypoint(boundary, state):
    for capability in ("sessions.read", "backend.routes.plugin", "frontend.native"):
        grant(boundary, capability)
    boundary.plugin.update(state)
    for path in (
        "/api/plugins/runtime/gateway",
        "/api/plugins/audit.plugin/actions/read",
        "/api/plugins/audit.plugin/probe",
    ):
        assert (await request(boundary, path)).status_code == 409
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app),
        base_url="http://test",
        cookies={"session": boundary.tokens[boundary.current["user"].id]},
    ) as client:
        assert (
            await client.get("/api/plugins/audit.plugin/native-frontend/native/index.js")
        ).status_code == 409
        assert (await client.get("/api/plugins/audit.plugin/ui")).status_code == 409
    boundary.runtime.action.assert_not_awaited()
    boundary.runtime.route.assert_not_awaited()
    boundary.runtime.native_frontend_asset.assert_not_awaited()


@pytest.mark.asyncio
async def test_backend_route_scopes_require_the_correct_capability(boundary):
    grant(boundary, "sessions.read")
    assert (await request(boundary, "/api/plugins/audit.plugin/probe")).status_code == 403
    grant(boundary, "backend.routes.plugin")
    assert (await request(boundary, "/api/plugins/audit.plugin/probe")).status_code == 200
    assert (await request(boundary, "/api/audit-probe")).status_code == 403
    grant(boundary, "backend.routes.host")
    assert (await request(boundary, "/api/audit-probe")).status_code == 200


@pytest.mark.asyncio
async def test_frontend_native_and_page_replacement_grants_are_specific(boundary):
    grant(boundary, "api.full")
    grant(boundary, "frontend.page.extend")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app),
        base_url="http://test",
        cookies={"session": boundary.tokens[boundary.current["user"].id]},
    ) as client:
        path = "/api/plugins/audit.plugin/native-frontend/native/index.js"
        assert (await client.get(path)).status_code == 403

        document = (await client.get("/api/plugins/audit.plugin/ui")).json()
        assert document["native_frontend"] is None
        assert document["page_replacements"] == []
        grant(boundary, "frontend.page.replace.home")
        document = (await client.get("/api/plugins/audit.plugin/ui")).json()
        assert [item["page"] for item in document["page_replacements"]] == ["home"]
        grant(boundary, "frontend.page.replace.settings")
        native = grant(boundary, "frontend.native")
        assert (await client.get(path)).status_code == 200
        document = (await client.get("/api/plugins/audit.plugin/ui")).json()
        assert {item["page"] for item in document["page_replacements"]} == {"home", "settings"}
        assert document["native_frontend"] is not None
        native.revoked_at = 1
        boundary.session.commit()
        assert (await client.get(path)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["installation", "user", "device", "version"])
async def test_frontend_activation_does_not_accept_stale_or_scoped_grants(boundary, scope):
    changes = {
        "installation": {"installation_id": uuid4()},
        "user": {"user_id": boundary.users[1].id},
        "device": {"device_id": uuid4()},
        "version": {"capability_version": 2},
    }[scope]
    grant(boundary, "frontend.native", **changes)
    grant(boundary, "frontend.page.replace.home", **changes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app),
        base_url="http://test",
        cookies={"session": boundary.tokens[boundary.users[0].id]},
    ) as client:
        listing = (await client.get("/api/plugins")).json()
        assert listing[0]["effective_capabilities"] == []
        assert (
            await client.get("/api/plugins/audit.plugin/native-frontend/native/index.js")
        ).status_code == 403
        document = (await client.get("/api/plugins/audit.plugin/ui")).json()
        assert document["native_frontend"] is None
        assert document["page_replacements"] == []
    boundary.runtime.native_frontend_asset.assert_not_awaited()


@pytest.mark.asyncio
async def test_notification_provider_operations_require_their_own_grant(boundary):
    grant(boundary, "notifications.send")
    payload = {"provider_id": "audit.plugin.provider", "name": "Audit", "action_id": "deliver"}
    assert (
        await request(
            boundary,
            method="notification_providers.register",
            capability="notification_providers.register",
            payload=payload,
        )
    ).status_code == 403
    assert (
        await request(
            boundary,
            method="notification_providers.register",
            capability="notifications.send",
            payload=payload,
        )
    ).status_code == 403
    assert boundary.session.scalar(select(PluginNotificationProviderRegistration)) is None
    grant(boundary, "notification_providers.register")
    assert (
        await request(
            boundary,
            method="notification_providers.register",
            capability="notification_providers.register",
            payload=payload,
        )
    ).status_code == 200
    assert (
        boundary.session.scalar(select(PluginNotificationProviderRegistration)).installation_id
        == boundary.installation_id
    )
    assert (
        await request(
            boundary,
            method="notifications.send",
            capability="notification_providers.register",
            payload={"title": "Denied", "body": "Denied"},
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_notifications_send_requires_grant_before_persisting_notification(boundary):
    body = {
        "method": "notifications.send",
        "capability": "notifications.send",
        "payload": {"title": "Notice", "body": "Body", "user_id": str(boundary.users[1].id)},
    }
    assert (await request(boundary, **body)).status_code == 403
    assert boundary.session.scalar(select(Notification)) is None
    grant(boundary, "notifications.send", user_id=boundary.users[0].id)
    assert (await request(boundary, **body)).status_code == 200
    assert boundary.session.scalar(select(Notification)).user_id == boundary.users[0].id


@pytest.mark.asyncio
async def test_device_resolver_requires_matching_authenticated_device(boundary):
    device_id = uuid4()
    grant(boundary, device_id=device_id)
    identity = {
        "plugin_id": "audit.plugin",
        "installation_id": boundary.installation_id,
        "capability": "sessions.read",
        "user_id": boundary.users[0].id,
    }
    assert await has_capability_grant(boundary.db, **identity, device_id=device_id)
    assert not await has_capability_grant(boundary.db, **identity, device_id=uuid4())
    assert not await has_capability_grant(boundary.db, **identity)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["grant", "registration", "installation", "disabled", "failed", "quarantined"]
)
async def test_provider_rechecks_authorization_after_destination_lookup(boundary, change):
    row = grant(boundary, "notification_providers.deliver")
    registration = PluginNotificationProviderRegistration(
        plugin_id="audit.plugin",
        installation_id=boundary.installation_id,
        provider_id="audit.plugin.provider",
        name="Audit",
        action_id="deliver",
    )
    boundary.session.add(registration)
    boundary.session.commit()
    provider = PluginNotificationProvider(registration, runtime=boundary.runtime)
    setting = NotificationProviderSetting(
        user_id=boundary.users[0].id, provider_id=registration.provider_id, enabled=True
    )
    destination = await provider.lookup_destination(boundary.db, boundary.users[0], setting)
    assert destination is not None
    if change == "grant":
        assert (
            await request(boundary, f"/api/plugin-permissions/grants/{row.id}/revoke")
        ).status_code == 200
    elif change == "registration":
        registration.revoked_at = 1
        boundary.session.commit()
    elif change == "installation":
        boundary.plugin["installation_id"] = str(uuid4())
    elif change == "disabled":
        boundary.plugin["enabled"] = False
    else:
        boundary.plugin["status"] = change
    message = NotificationMessage(
        id=uuid4(),
        kind="plugin",
        title="Notice",
        body="Body",
        media_type="plugin",
        media_id=uuid4(),
        event_at=1,
    )
    result = await provider.deliver(boundary.db, destination, message)
    assert not result.success
    boundary.runtime.action.assert_not_awaited()


@pytest.fixture
def broker(boundary, tmp_path, monkeypatch):
    """Bridge real runtime requests into the real host HTTP gateway."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "plugin-runtime"))
    import runtime

    supervisor = runtime.PluginSupervisor(
        root=tmp_path / "work",
        storage_root=tmp_path / "storage",
        gateway_url="http://test",
        gateway_token="x" * 32,
    )
    supervisor._installation_ids["audit.plugin"] = str(boundary.installation_id)
    supervisor._user_ids["audit.plugin"] = str(boundary.users[0].id)
    supervisor._package_manifests["audit.plugin"] = {
        "permissions": [{"capability": {"name": "plugin.storage", "version": 1}}]
    }
    package = tmp_path / "package"
    package.mkdir()
    (package / ".settings.json").write_text(json.dumps({"mode": "dark"}), encoding="utf-8")
    supervisor._package_paths["audit.plugin"] = package
    loop = None

    async def http_request(req):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=boundary.app), base_url="http://test"
        ) as client:
            return await client.post(
                req.full_url, content=req.data, headers=dict(req.header_items())
            )

    def send(req, **_kwargs):
        response = asyncio.run_coroutine_threadsafe(http_request(req), loop).result(timeout=10)
        response.raise_for_status()
        return io.BytesIO(response.content)

    monkeypatch.setattr(runtime, "urlopen", send)

    async def dispatch(method, capability, payload=None, **identity):
        nonlocal loop
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(
            supervisor._handle_gateway_request,
            "audit.plugin",
            {"method": method, "capability": capability, "payload": payload or {}},
            **identity,
        )

    async def run(operation, *args, **kwargs):
        nonlocal loop
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(operation, *args, **kwargs)

    return SimpleNamespace(dispatch=dispatch, run=run, supervisor=supervisor, runtime=runtime)


@pytest.mark.asyncio
async def test_frontend_action_uses_host_user_for_runtime_domain_access(boundary, broker):
    grant(boundary, "sessions.read", user_id=boundary.users[0].id)

    async def execute(_plugin_id, _action_id, _values, *, user_id):
        return (await broker.dispatch("sessions.list", "sessions.read", user_id=user_id))["payload"]

    boundary.runtime.action.side_effect = execute
    response = await request(
        boundary,
        "/api/plugins/audit.plugin/actions/read",
        values={
            "user_id": str(boundary.users[1].id),
            "_plugin_context": {"user_id": str(boundary.users[1].id)},
        },
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["sessions"]] == [str(boundary.sessions[0].id)]
    assert boundary.runtime.action.await_args.kwargs["user_id"] == str(boundary.users[0].id)
    assert boundary.runtime.action.await_args.args[2]["_plugin_context"]["user_id"] == str(
        boundary.users[0].id
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["notifications.send", "notification_providers.deliver"])
async def test_runtime_egress_requires_persisted_operation_grant(
    boundary, broker, monkeypatch, tmp_path, capability
):
    registry = broker.runtime.PluginRegistry(tmp_path / "registry", broker.supervisor)
    registry._transition("audit.plugin", enabled=True, status="running")
    monkeypatch.setattr(registry, "_item", lambda _package: boundary.plugin)
    monkeypatch.setattr(broker.supervisor, "running", lambda _id: True)
    monkeypatch.setattr(
        registry, "ui", lambda _id: {"actions": [{"id": "deliver", "handler": "entry:deliver"}]}
    )
    monkeypatch.setattr(
        registry, "package", lambda _id: (tmp_path, {"capabilities": [{"name": capability}]})
    )
    execute = SimpleNamespace(calls=0)

    def process(*_args, **_kwargs):
        execute.calls += 1
        return b'{"discord":true,"content":"Notice"}'

    monkeypatch.setattr(broker.supervisor, "execute", process)
    sent = []
    monkeypatch.setattr(registry, "_discord_webhook", lambda *args: sent.append(args))
    monkeypatch.setenv("PLUGIN_RUNTIME_DISCORD_EGRESS", "true")
    broker.supervisor._storage("audit.plugin").put(
        "secrets/discord_webhook", b"https://discord.com/api/webhooks/audit/secret"
    )
    with pytest.raises(broker.runtime.RuntimePolicyError, match="gateway request failed"):
        await broker.run(
            registry.action, "audit.plugin", "deliver", {}, user_id=str(boundary.users[0].id)
        )
    assert sent == []
    wrong = (
        "notifications.send"
        if capability == "notification_providers.deliver"
        else "notification_providers.deliver"
    )
    grant(boundary, wrong)
    with pytest.raises(broker.runtime.RuntimePolicyError, match="gateway request failed"):
        await broker.run(
            registry.action, "audit.plugin", "deliver", {}, user_id=str(boundary.users[0].id)
        )
    assert sent == []
    row = grant(boundary, capability, user_id=boundary.users[0].id)
    await broker.run(
        registry.action, "audit.plugin", "deliver", {}, user_id=str(boundary.users[0].id)
    )
    assert len(sent) == 1
    assert (
        await request(boundary, f"/api/plugin-permissions/grants/{row.id}/revoke")
    ).status_code == 200
    with pytest.raises(broker.runtime.RuntimePolicyError, match="gateway request failed"):
        await broker.run(
            registry.action, "audit.plugin", "deliver", {}, user_id=str(boundary.users[0].id)
        )
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_action_capability_version_cannot_fall_back_to_version_one(boundary):
    grant(boundary)
    boundary.runtime.plugin_ui.return_value["actions"][0]["capability"]["version"] = 2
    assert (await request(boundary, "/api/plugins/audit.plugin/actions/read")).status_code == 403
    boundary.runtime.action.assert_not_awaited()


@pytest.mark.asyncio
async def test_inactive_user_and_unknown_operation_fail_closed(boundary):
    grant(boundary, "api.full")
    assert (
        await request(boundary, method="unknown.operation", capability="api.full")
    ).status_code == 422
    assert (
        await request(boundary, method="sessions.list", capability="unknown.capability")
    ).status_code == 403
    boundary.users[0].is_active = False
    boundary.session.commit()
    assert (await request(boundary)).status_code == 403


@pytest.mark.asyncio
async def test_actual_runtime_request_reaches_user_scoped_domain_operation(boundary, broker):
    row = grant(boundary, "sessions", user_id=boundary.users[0].id)
    result = await broker.dispatch("sessions.list", "sessions.read")
    assert [item["id"] for item in result["payload"]["sessions"]] == [str(boundary.sessions[0].id)]
    with pytest.raises(broker.runtime.RuntimePolicyError, match="gateway request failed"):
        await broker.dispatch("sessions.list", "sessions.read", user_id=str(boundary.users[1].id))
    assert (
        await request(boundary, f"/api/plugin-permissions/grants/{row.id}/revoke")
    ).status_code == 200
    with pytest.raises(broker.runtime.RuntimePolicyError, match="gateway request failed"):
        await broker.dispatch("sessions.list", "sessions.read")


@pytest.mark.asyncio
async def test_runtime_local_storage_and_settings_require_live_host_grants(boundary, broker):
    for method, capability, payload in [
        ("storage.put", "plugin.storage", {"key": "data", "value": "saved"}),
        ("settings.get", "plugin.settings", {"key": "mode"}),
    ]:
        with pytest.raises(broker.runtime.RuntimePolicyError, match="gateway request failed"):
            await broker.dispatch(method, capability, payload)
    assert broker.supervisor._storage("audit.plugin").get("data") is None
    storage_grant = grant(boundary, "plugin.storage")
    assert await broker.dispatch(
        "storage.put", "sessions.read", {"key": "data", "value": "saved"}
    ) == {"payload": {"saved": True}}
    assert await broker.dispatch("storage.get", "plugin.storage", {"key": "data"}) == {
        "payload": {"value": "saved"}
    }
    grant(boundary, "plugin.settings")
    assert await broker.dispatch("settings.get", "plugin.settings", {"key": "mode"}) == {
        "payload": {"value": "dark"}
    }
    assert (
        await request(boundary, f"/api/plugin-permissions/grants/{storage_grant.id}/revoke")
    ).status_code == 200
    for method in ("storage.get", "storage.keys", "storage.delete", "storage.put"):
        with pytest.raises(broker.runtime.RuntimePolicyError, match="gateway request failed"):
            await broker.dispatch(method, "plugin.storage", {"key": "data", "value": "overwrite"})
    assert broker.supervisor._storage("audit.plugin").get("data") == b"saved"
