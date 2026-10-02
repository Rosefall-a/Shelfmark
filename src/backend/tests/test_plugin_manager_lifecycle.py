"""Complete manager lifecycles against PostgreSQL grants and the real package store."""

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from test_plugin_install_sources import gate, package_bytes, acquire, grants, seed_update  # noqa: F401
from src.api.routes import plugins
from src.core.auth import get_current_user
from src.database.models.auth import UserApiKey
from src.database.models.plugin_permissions import PluginPermissionGrant
from src.plugin_api.grants import has_capability_grant
from src.plugin_api.manager_state import ManagerState, manager_state
from src.plugin_api.runtime_client import PluginRuntimeUnavailable
from src.plugin_api.recovery import recover_transactions
from src.plugin_api.grants import effective_capabilities
from src.plugin_api.management_auth import get_plugin_manager_admin, MANAGEMENT_SCOPES


async def install(gate, permissions=()):
    await seed_update(gate, "update", trust="trusted", permissions=permissions)
    return UUID(gate.registry.list()[0]["installation_id"])


def owned_data(gate):
    gate.registry.storage_put(gate.plugin_id, "secrets/server-token", "credentials")
    gate.registry.storage_put(gate.plugin_id, "profiles/default", "profile")
    gate.registry.storage_put(gate.plugin_id, "imports/history", "imported history")
    gate.registry.settings(
        gate.plugin_id, {"server": "https://media.example", "profile": "default"}
    )


def assert_owned_data(gate):
    storage = gate.registry.supervisor._storage(gate.plugin_id)
    assert storage.get("secrets/server-token") == b"credentials"
    assert storage.get("profiles/default") == b"profile"
    assert storage.get("imports/history") == b"imported history"
    assert gate.registry.supervisor._settings(gate.plugin_id)["server"] == "https://media.example"


@pytest.mark.asyncio
async def test_package_lifecycles_preserve_integration_data_and_identity(gate):
    installation_id = await install(gate)
    owned_data(gate)
    duplicate = await acquire(gate, "utp", package_bytes(gate.plugin_id, version="1.0.0"))
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["choices"] == ["update", "reinstall", "replace", "cancel"]
    await gate.client.post(f"/api/plugins/{gate.plugin_id}/disable")
    assert not gate.registry.list()[0]["enabled"]
    assert_owned_data(gate)
    assert (await gate.client.post(f"/api/plugins/{gate.plugin_id}/enable")).status_code == 200
    assert (await gate.client.post(f"/api/plugins/{gate.plugin_id}/stop")).status_code == 200
    assert gate.registry.list()[0]["enabled"]
    assert gate.registry.list()[0]["status"] == "stopped"
    gate.registry.restore_enabled()
    assert gate.registry.list()[0]["status"] == "stopped"
    assert (await gate.client.post(f"/api/plugins/{gate.plugin_id}/start")).status_code == 200
    # Simulate loss of live processes at a normal runtime restart.
    gate.registry.supervisor.stop(gate.plugin_id)
    gate.registry.restore_enabled()
    assert gate.registry.health(gate.plugin_id)
    update = await acquire(
        gate, "update", package_bytes(gate.plugin_id, trust="trusted", key=gate.key)
    )
    assert update.json()["status"] == "running", update.text
    assert gate.registry.list()[0]["history"][0]["version"] == "1.0.0"
    assert_owned_data(gate)
    rollback = await gate.client.post(f"/api/plugins/{gate.plugin_id}/rollback", json={})
    assert rollback.status_code == 200, rollback.text
    assert gate.registry.package(gate.plugin_id)[1]["version"] == "1.0.0"
    reinstall = await gate.client.post(f"/api/plugins/{gate.plugin_id}/reinstall", json={})
    assert reinstall.status_code == 200, reinstall.text
    assert gate.registry.package(gate.plugin_id)[1]["version"] == "1.0.0"
    assert UUID(gate.registry.list()[0]["installation_id"]) == installation_id
    assert_owned_data(gate)
    assert (await gate.client.delete(f"/api/plugins/{gate.plugin_id}")).status_code == 204
    assert gate.registry.list() == []
    assert gate.plugin_id not in manager_state().read()["plugins"]
    assert not (gate.registry.supervisor.storage_root / gate.plugin_id).exists()
    assert not (gate.registry.root / ".history" / gate.plugin_id).exists()
    assert not (
        gate.registry.supervisor.storage_root.parent / ".configuration" / f"{gate.plugin_id}.json"
    ).exists()


@pytest.mark.asyncio
async def test_staged_permissions_denial_approval_revocation_and_regrant(gate):
    installation_id = await install(gate, ("games.read",))
    owned_data(gate)
    response = await acquire(
        gate,
        "update",
        package_bytes(
            gate.plugin_id,
            trust="trusted",
            key=gate.key,
            permissions=("games.read", "media.import"),
        ),
    )
    assert response.json()["status"] == "awaiting_permissions"
    assert gate.registry.package(gate.plugin_id)[1]["version"] == "1.0.0"
    assert [row.capability for row in await grants(gate)] == ["games.read"]
    assert gate.registry.health(gate.plugin_id)
    deny = await gate.client.post(
        f"/api/plugins/{gate.plugin_id}/update/staged", json={"confirmed": True}
    )
    assert deny.json()["status"] == "denied"
    assert gate.registry.health(gate.plugin_id)
    stale = await gate.client.post(
        f"/api/plugins/{gate.plugin_id}/update/staged",
        json={"approved_permissions": ["media.import:v1"], "expected_digest": "0" * 64},
    )
    assert stale.status_code == 409
    assert gate.registry.package(gate.plugin_id)[1]["version"] == "1.0.0"
    approve = await gate.client.post(
        f"/api/plugins/{gate.plugin_id}/update/staged",
        json={"approved_permissions": ["media.import:v1"]},
    )
    assert approve.json()["status"] == "running", approve.text
    media = next(row for row in await grants(gate) if row.capability == "media.import")
    media.revoked_at = 1
    await gate.db.commit()
    user_id = gate.admin.id
    assert not await has_capability_grant(
        gate.db,
        plugin_id=gate.plugin_id,
        installation_id=installation_id,
        capability="media.import",
        user_id=user_id,
    )
    await gate.client.post(f"/api/plugins/{gate.plugin_id}/disable")
    await gate.client.post(f"/api/plugins/{gate.plugin_id}/enable")
    await gate.client.post(f"/api/plugins/{gate.plugin_id}/reinstall", json={})
    assert "media.import" not in {row.capability for row in await grants(gate)}
    regrant = await gate.client.post(
        f"/api/plugins/{gate.plugin_id}/permissions/grant",
        json={"approved_permissions": ["media.import:v1"]},
    )
    assert regrant.status_code == 200, regrant.text
    assert "media.import" in {row.capability for row in await grants(gate)}
    assert_owned_data(gate)


@pytest.mark.asyncio
async def test_fresh_installation_recovers_administrator_context(gate):
    gate.runtime.fail_finish = True
    result = await acquire(
        gate, "utp", package_bytes(gate.plugin_id, trust="trusted", key=gate.key)
    )
    assert result.status_code == 422
    gate.runtime.fail_finish = False
    await recover_transactions(gate.runtime, gate.db)
    assert gate.registry.list()[0]["pending_transaction"] is None
    assert gate.registry._state()[gate.plugin_id]["user_id"] == str(gate.admin.id)
    assert gate.registry.health(gate.plugin_id)


@pytest.mark.asyncio
async def test_recovery_waits_for_an_in_flight_installation(gate, monkeypatch):
    prepared = asyncio.Event()
    resume = asyncio.Event()
    original = gate.runtime.install_package

    async def paused_install(*args, **kwargs):
        result = await original(*args, **kwargs)
        prepared.set()
        await resume.wait()
        return result

    monkeypatch.setattr(gate.runtime, "install_package", paused_install)
    installation = asyncio.create_task(
        acquire(gate, "utp", package_bytes(gate.plugin_id, trust="trusted", key=gate.key))
    )
    await asyncio.wait_for(prepared.wait(), 5)
    recovery = asyncio.create_task(recover_transactions(gate.runtime, gate.db))
    await asyncio.sleep(0)
    assert not recovery.done()
    resume.set()
    response, _ = await asyncio.gather(installation, recovery)
    assert response.status_code == 201, response.text
    assert gate.registry.health(gate.plugin_id)
    assert gate.registry.list()[0]["pending_transaction"] is None


@pytest.mark.asyncio
async def test_denied_staged_release_remains_denied_during_scheduled_checks(gate, monkeypatch):
    await install(gate, ("games.read",))
    source = {"type": "catalogue", "catalogue_url": "https://catalogue.example/list.json"}
    gate.registry._transition(gate.plugin_id, source=source)
    store = manager_state()
    store.reconcile(gate.registry.list())
    store.settings({"automatic_updates": True})
    payload = package_bytes(
        gate.plugin_id, trust="trusted", key=gate.key, permissions=("games.read", "media.import")
    )
    response = await acquire(gate, "update", payload)
    assert response.json()["status"] == "awaiting_permissions"
    await gate.client.post(f"/api/plugins/{gate.plugin_id}/update/staged", json={"confirmed": True})

    async def download(*args, **kwargs):
        path = store.path.parent / "denied-release.utp"
        path.write_bytes(payload)
        return path, "denied-release.utp", len(payload)

    async def check(plugin, admin):
        return {
            "plugin_id": gate.plugin_id,
            "current_version": "1.0.0",
            "available_version": "2.0.0",
            "update_available": True,
            "url": "https://packages.example/update.utp",
            "automatic_update": True,
            "source": source,
        }

    monkeypatch.setattr(plugins, "_check_plugin_update", check)
    monkeypatch.setattr(plugins, "_download_remote_file", download)
    monkeypatch.setattr(
        plugins,
        "_catalogue_store",
        lambda: SimpleNamespace(list=lambda: [{"url": source["catalogue_url"], "enabled": True}]),
    )
    result = await plugins.run_automatic_plugin_updates(gate.db, gate.admin)
    assert result["installed"] == 0
    assert store.read()["plugins"][gate.plugin_id]["staged_update"]["status"] == "denied"
    assert gate.registry.package(gate.plugin_id)[1]["version"] == "1.0.0"
    assert gate.registry.health(gate.plugin_id)


@pytest.mark.asyncio
async def test_purge_reinstall_is_confirmed_and_removes_all_owned_state(gate):
    await install(gate, ("games.read",))
    owned_data(gate)
    denied = await gate.client.post(
        f"/api/plugins/{gate.plugin_id}/reinstall", json={"purge": True}
    )
    assert denied.status_code == 409
    assert_owned_data(gate)
    result = await gate.client.post(
        f"/api/plugins/{gate.plugin_id}/reinstall", json={"purge": True, "confirmed": True}
    )
    assert result.status_code == 200, result.text
    assert await grants(gate) == []
    assert gate.registry.supervisor._storage(gate.plugin_id).get("secrets/server-token") is None
    assert gate.registry.supervisor._settings(gate.plugin_id) == {}
    assert gate.registry.package(gate.plugin_id)[1]["version"] == "1.0.0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "global_enabled,override,release_auto,package_auto,install_update,healthy",
    [
        (False, "follow", True, True, False, True),
        (True, "follow", True, True, True, True),
        (False, "enabled", True, True, True, True),
        (True, "disabled", True, True, False, True),
        (True, "enabled", False, True, False, True),
        (True, "enabled", True, False, False, True),
        (True, "follow", True, True, False, False),
    ],
)
async def test_automatic_update_policy_downloads_without_unauthorized_activation(
    gate, monkeypatch, global_enabled, override, release_auto, package_auto, install_update, healthy
):
    await install(gate)
    owned_data(gate)
    source = {"type": "catalogue", "catalogue_url": "https://catalogue.example/list.json"}
    gate.registry._transition(gate.plugin_id, source=source)
    store = manager_state()
    store.reconcile(gate.registry.list())
    store.settings({"automatic_updates": global_enabled})
    store.patch(gate.plugin_id, automatic_updates=override)
    payload = package_bytes(gate.plugin_id, trust="trusted", key=gate.key)
    if not package_auto:
        import io, zipfile

        output = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(payload)) as original,
            zipfile.ZipFile(output, "w") as archive,
        ):
            for name in original.namelist():
                value = original.read(name)
                if name == "manifest.json":
                    manifest = json.loads(value)
                    manifest["automatic_update"] = False
                    value = json.dumps(manifest).encode()
                archive.writestr(name, value)
        payload = output.getvalue()
    path = store.path.parent / "remote.utp"
    path.write_bytes(payload)

    async def download(*args, **kwargs):
        return path, "package.utp", len(payload)

    async def check(plugin, admin):
        return {
            "plugin_id": gate.plugin_id,
            "current_version": "1.0.0",
            "available_version": "2.0.0",
            "update_available": True,
            "url": "https://packages.example/update.utp",
            "automatic_update": release_auto,
            "source": source,
        }

    monkeypatch.setattr(plugins, "_check_plugin_update", check)
    monkeypatch.setattr(plugins, "_download_remote_file", download)
    monkeypatch.setattr(
        plugins,
        "_catalogue_store",
        lambda: SimpleNamespace(list=lambda: [{"url": source["catalogue_url"], "enabled": True}]),
    )
    admin = gate.admin
    gate.runtime.healthy = healthy
    result = await plugins.run_automatic_plugin_updates(gate.db, admin)
    assert result["installed"] == int(install_update), result
    assert gate.registry.package(gate.plugin_id)[1]["version"] == (
        "2.0.0" if install_update else "1.0.0"
    )
    if not install_update:
        assert store.read()["plugins"][gate.plugin_id]["staged_update"]["status"] == "downloaded"
        assert store.stage_path(gate.plugin_id).exists()
    assert_owned_data(gate)
    if not healthy:
        from src.database.models.notification import Notification

        assert result["failed"] == 1
        assert gate.registry.health(gate.plugin_id)
        notifications = await gate.db.scalars(
            select(Notification).where(
                Notification.dedupe_key.like(f"plugin-update:{gate.plugin_id}:%:failed")
            )
        )
        assert any("failed" in item.title for item in notifications)


@pytest.mark.asyncio
@pytest.mark.parametrize("healthy", [True, False])
async def test_restart_recovers_committed_update_and_preserves_grants_and_data(gate, healthy):
    await install(gate, ("games.read",))
    owned_data(gate)
    gate.runtime.fail_finish = True
    result = await acquire(
        gate, "update", package_bytes(gate.plugin_id, trust="trusted", key=gate.key)
    )
    assert result.status_code == 422, result.text
    assert "finalization failure" in result.text
    assert gate.registry.list()[0]["pending_transaction"]["phase"] == "prepared"
    assert await grants(gate) == []  # candidate removed a permission
    gate.runtime.fail_finish = False
    gate.runtime.healthy = healthy
    gate.registry.restore_enabled()
    assert not gate.registry.health(gate.plugin_id)
    await recover_transactions(gate.runtime, gate.db)
    assert gate.registry.list()[0]["pending_transaction"] is None
    assert gate.registry.package(gate.plugin_id)[1]["version"] == ("2.0.0" if healthy else "1.0.0")
    assert gate.registry.health(gate.plugin_id)
    assert {row.capability for row in await grants(gate)} == (set() if healthy else {"games.read"})
    assert_owned_data(gate)


@pytest.mark.asyncio
async def test_revoked_child_scope_blocks_broad_parent_grants_until_explicit_regrant(gate):
    identity = await install(gate, ("games.read",))
    existing = (await grants(gate))[0]
    existing.revoked_at = 1
    gate.db.add(
        PluginPermissionGrant(
            plugin_id=gate.plugin_id,
            installation_id=identity,
            capability="api.full",
            capability_version=1,
        )
    )
    await gate.db.commit()
    assert not await has_capability_grant(
        gate.db,
        plugin_id=gate.plugin_id,
        installation_id=identity,
        capability="games.read",
        user_id=gate.admin.id,
    )
    effective = await effective_capabilities(
        gate.db, gate.plugin_id, identity, gate.admin.id, ["api.full"]
    )
    assert "games.read" not in effective
    response = await gate.client.post(
        f"/api/plugins/{gate.plugin_id}/permissions/grant",
        json={"approved_permissions": ["games.read:v1"]},
    )
    assert response.status_code == 200
    assert await has_capability_grant(
        gate.db,
        plugin_id=gate.plugin_id,
        installation_id=identity,
        capability="games.read",
        user_id=gate.admin.id,
    )


@pytest.mark.asyncio
async def test_stopped_update_and_configurable_history_preserve_owned_data(gate):
    await install(gate)
    owned_data(gate)
    await gate.client.post(f"/api/plugins/{gate.plugin_id}/stop")
    await gate.client.put(
        "/api/plugins/manager-settings", json={"automatic_updates": False, "retained_versions": 2}
    )
    for version in ("2.0.0", "3.0.0"):
        response = await acquire(
            gate,
            "update",
            package_bytes(gate.plugin_id, version=version, trust="trusted", key=gate.key),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "stopped"
        assert gate.registry.list()[0]["enabled"]
    history = gate.registry.list()[0]["history"]
    assert [item["version"] for item in history] == ["2.0.0", "1.0.0"]
    response = await gate.client.delete(f"/api/plugins/{gate.plugin_id}/history/{history[1]['id']}")
    assert response.status_code == 200, response.text
    assert [item["version"] for item in gate.registry.list()[0]["history"]] == ["2.0.0"]
    assert_owned_data(gate)


@pytest.mark.asyncio
async def test_host_inventory_survives_runtime_unavailability(gate, monkeypatch):
    await install(gate)
    before = manager_state().read()["plugins"][gate.plugin_id]

    async def unavailable():
        raise PluginRuntimeUnavailable("offline")

    monkeypatch.setattr(gate.runtime, "plugins", unavailable)
    result = await plugins._installed_plugins()
    assert result[0]["plugin_id"] == gate.plugin_id
    assert result[0]["version"] == before["version"]
    assert result[0]["runtime_available"] is False
    assert result[0]["status"] == "unknown"
    assert (
        ManagerState(manager_state().path).read()["plugins"][gate.plugin_id]["installation_id"]
        == before["installation_id"]
    )


@pytest.mark.asyncio
async def test_management_tokens_are_granular_and_cannot_access_application_data(gate):
    admin = gate.admin
    issued = await plugins.create_management_token(
        plugins.ManagementTokenIn(name="Control plane", scopes=["plugins.read"]), gate.db, admin
    )
    app = FastAPI()
    app.include_router(plugins.router)
    app.dependency_overrides[plugins.get_db] = lambda: gate.db

    @app.get("/api/private")
    async def private(user=Depends(get_current_user)):
        return {"username": user.username}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://manager.test",
        headers={"Authorization": "Bearer " + issued["token"]},
    ) as client:
        assert (await client.get("/api/plugins")).status_code == 200
        assert (await client.post("/api/plugins/updates/check")).status_code == 403
        assert (await client.post("/api/plugins/example/enable")).status_code == 403
        assert (await client.get("/api/private")).status_code == 403
        assert (await client.get("/api/plugins/example/ui")).status_code in {401, 403}
    row = await gate.db.scalar(select(UserApiKey).where(UserApiKey.id == UUID(issued["id"])))
    assert row.key_hash != issued["token"]
    await plugins.revoke_management_token(UUID(issued["id"]), gate.db, admin)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://manager.test",
        headers={"Authorization": "Bearer " + issued["token"]},
    ) as client:
        assert (await client.get("/api/plugins")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,method,path",
    [
        ("plugins.read", "GET", "/api/plugins"),
        ("plugins.install", "POST", "/api/plugins/install/preview"),
        ("plugins.update", "POST", "/api/plugins/example/update/staged"),
        ("plugins.lifecycle", "POST", "/api/plugins/example/disable"),
        ("plugins.permissions", "POST", "/api/plugins/example/permissions/grant"),
    ],
)
async def test_each_management_scope_authorizes_only_its_operation_family(
    gate, scope, method, path
):
    app = FastAPI()
    app.dependency_overrides[plugins.get_db] = lambda: gate.db

    async def operation(admin=Depends(get_plugin_manager_admin)):
        return {"authorized": True}

    app.add_api_route(path, operation, methods=[method])
    for granted_scope in MANAGEMENT_SCOPES:
        issued = await plugins.create_management_token(
            plugins.ManagementTokenIn(name="Scope test", scopes=[granted_scope]),
            gate.db,
            gate.admin,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://manager.test",
            headers={"Authorization": "Bearer " + issued["token"]},
        ) as client:
            response = await client.request(method, path)
            assert response.status_code == (200 if granted_scope == scope else 403)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,path,approval",
    [
        (
            "plugins.install",
            "/api/plugins/install/url?approved_permissions=games.read:v1",
            {},
        ),
        (
            "plugins.update",
            "/api/plugins/example/update/staged",
            {"approved_permissions": ["games.read:v1"]},
        ),
    ],
)
async def test_operation_tokens_need_permission_scope_to_approve_grants(
    gate, scope, path, approval
):
    app = FastAPI()
    app.dependency_overrides[plugins.get_db] = lambda: gate.db

    async def operation(admin=Depends(get_plugin_manager_admin)):
        return {"authorized": True}

    app.add_api_route(path.split("?", 1)[0], operation, methods=["POST"])
    for scopes, expected in [([scope], 403), ([scope, "plugins.permissions"], 200)]:
        issued = await plugins.create_management_token(
            plugins.ManagementTokenIn(name="Grant approval test", scopes=scopes),
            gate.db,
            gate.admin,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://manager.test",
            headers={"Authorization": "Bearer " + issued["token"]},
        ) as client:
            assert (await client.post(path, json=approval)).status_code == expected
            assert (await client.post(path.split("?", 1)[0], json={})).status_code == 200
