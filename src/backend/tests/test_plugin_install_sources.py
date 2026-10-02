"""Public HTTP acquisition -> real PostgreSQL grants -> real runtime package store.

Only the remote HTTP transport and process execution are substituted. Packages
are synthetic protocol data, not implementations of external reference plugins.
"""

from __future__ import annotations

import base64
import importlib
import io
import json
import socket
import stat
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.routes import plugins
from src.core.auth import hash_password
from src.core.config import settings
from src.database.models import achievement as _achievement  # noqa: F401
from src.database.models.plugin_permission_audit import PluginPermissionAudit
from src.database.models.plugin_permissions import PluginPermissionGrant, PluginPermissionRequest
from src.database.models.user import User
from src.database.session import get_db
from src.plugin_api.runtime_client import PluginRuntimeRequestError
from src.plugin_api.updates import PluginPackageVerifier, TrustedPublisher, canonical_payload_digest

SOURCES = (
    "utp",
    "zip",
    "content",
    "url",
    "catalogue",
    "update",
    "update-url",
    "update-catalogue",
)
PASSWORD = "Gate-review-password!"


def package_bytes(
    plugin_id,
    *,
    version="2.0.0",
    permissions=(),
    dependencies=(),
    trust="unsigned",
    key=None,
    broken=None,
):
    files = [("plugin.py", b"protocol fixture bytes\n")]
    digest = canonical_payload_digest(files)
    integrity = {"sha256": digest}
    if trust != "unsigned":
        signature = key.sign(b"plugin-package-v1:" + digest.encode("ascii"))
        if trust == "invalid":
            signature = b"x" * 64
        integrity.update(
            signature=base64.b64encode(signature).decode("ascii"),
            key_id="unknown" if trust == "unknown_publisher" else "known",
        )
    if broken == "malformed_signature":
        integrity.update(signature="not-base64!", key_id="unknown")
    manifest = {
        "manifest_version": 1,
        "plugin_id": plugin_id,
        "name": "Lifecycle gate candidate",
        "version": version,
        "entrypoint": "plugin:main",
        "sdk_version_range": "*",
        "application_version_range": "*",
        "capabilities": [{"name": name, "version": 1} for name in permissions],
        "permissions": [
            {"capability": {"name": name, "version": 1}, "rationale": "Gate consent coverage."}
            for name in permissions
        ],
        "dependencies": list(dependencies),
        "integrity": integrity,
    }
    if broken == "manifest":
        manifest["unexpected"] = True
    if broken == "integrity":
        manifest["integrity"]["sha256"] = "0" * 64
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, content in files:
            archive.writestr("payload/" + name, content)
        if broken == "traversal":
            archive.writestr("payload/../../escape", b"escape")
        if broken == "duplicate":
            archive.writestr("payload/plugin.py", b"duplicate")
        if broken == "symlink":
            link = zipfile.ZipInfo("payload/link")
            link.external_attr = stat.S_IFLNK << 16
            archive.writestr(link, b"../../escape")
        if broken == "alternate_stream":
            archive.writestr("payload/plugin.py:secret", b"escape")
    if broken == "unicode_name":
        malformed = bytearray(output.getvalue())
        central = malformed.index(b"PK\x01\x02")
        struct.pack_into("<H", malformed, 6, 0x800)
        struct.pack_into("<H", malformed, central + 8, 0x800)
        malformed[30] = malformed[central + 46] = 0xFF
        return bytes(malformed)
    return b"not an archive" if broken == "archive" else output.getvalue()


@pytest.fixture
async def gate(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGIN_MANAGER_STATE_PATH", str(tmp_path / "manager.json"))
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "plugin-runtime"))
    runtime_module = importlib.import_module("runtime")
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    key = Ed25519PrivateKey.generate()
    plugin_id = "example.gate-" + uuid4().hex[:10]
    events = []
    supervisor = runtime_module.PluginSupervisor(tmp_path / "work", tmp_path / "storage")
    running = set()
    monkeypatch.setattr(supervisor, "start", lambda spec, path: running.add(spec.plugin_id))
    monkeypatch.setattr(supervisor, "stop", lambda plugin_id: running.discard(plugin_id))
    monkeypatch.setattr(supervisor, "running", lambda plugin_id: plugin_id in running)
    registry = runtime_module.PluginRegistry(tmp_path / "plugins", supervisor)

    class Runtime:
        fail_install = False
        fail_start = False
        healthy = True
        fail_finish = False
        fail_commit = False
        ambiguous_commit = False
        changed_version = False

        async def plugins(self):
            return registry.list()

        async def install_package(self, package, filename, **kwargs):
            events.append("install")
            if self.fail_install:
                raise PluginRuntimeRequestError("injected atomic installation failure")
            if self.changed_version:
                manifest_path = registry.root / plugin_id / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["version"] = "1.5.0"
                manifest_path.write_text(json.dumps(manifest))
            try:
                return registry.install_package(package, filename, **kwargs)
            except runtime_module.RuntimePolicyError as exc:
                raise PluginRuntimeRequestError(str(exc)) from exc

        async def finish_installation(self, plugin_id, operation_id, *, commit):
            if self.fail_finish:
                raise PluginRuntimeRequestError("injected finalization failure")
            events.append("finalize" if commit else "abort")
            registry.finish_installation(plugin_id, operation_id, commit=commit)

        async def finish_activation(self, plugin_id, operation_id, *, commit):
            registry.finish_activation(plugin_id, operation_id, commit=commit)

        async def prune_history(self, plugin_id, retain, history_id=None):
            registry.prune_history(plugin_id, retain=retain, history_id=history_id)

        async def stop(self, plugin_id):
            registry.stop(plugin_id)

        async def stop_runtime(self, plugin_id):
            registry.stop(plugin_id, disable=False)

        async def package_archive(self, plugin_id, history_id=None):
            return base64.b64decode(registry.package_archive(plugin_id, history_id)["package"])

        async def purge_data(self, plugin_id):
            registry.purge_data(plugin_id)

        async def delete(self, plugin_id):
            registry.delete(plugin_id)

        async def start(self, plugin_id, user_id=None):
            events.append("start")
            if registry._state().get(plugin_id, {}).get("pending_activation"):
                assert "commit" in events
            if self.fail_start:
                raise PluginRuntimeRequestError("injected activation failure")
            registry.start(plugin_id, user_id)

        async def plugin_health(self, plugin_id):
            events.append("health")
            return (
                self.healthy or registry.package(plugin_id)[1]["version"] == "1.0.0"
            ) and registry.health(plugin_id)

    class Session(AsyncSession):
        async def commit(self):
            if runtime.fail_commit:
                self.add(
                    PluginPermissionGrant(
                        plugin_id=plugin_id,
                        installation_id=None,
                        capability="games.read",
                        capability_version=1,
                    )
                )
            await super().commit()
            if runtime.ambiguous_commit:
                raise OperationalError(
                    "COMMIT",
                    {},
                    ConnectionError("lost commit acknowledgement"),
                    connection_invalidated=True,
                )
            events.append("commit")

    remote = {"package": b""}

    async def http_transport(request):
        events.append("acquire")
        if request.url.host == "catalogue.example":
            with zipfile.ZipFile(io.BytesIO(remote["package"])) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            return httpx.Response(
                200,
                json={
                    "version": 1,
                    "plugins": [
                        {
                            "plugin_id": manifest["plugin_id"],
                            "name": manifest["name"],
                            "version": manifest["version"],
                            "url": "https://packages.example/download",
                            "sha256": manifest["integrity"]["sha256"],
                        }
                    ],
                },
            )
        return httpx.Response(200, content=remote["package"])

    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        plugins.httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(
            transport=httpx.MockTransport(http_transport), **kwargs
        ),
    )
    original_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(
        plugins.socket,
        "getaddrinfo",
        lambda host, *args, **kwargs: (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
            if host in {"packages.example", "catalogue.example"}
            else original_getaddrinfo(host, *args, **kwargs)
        ),
    )
    runtime = Runtime()
    monkeypatch.setattr(plugins, "_client", runtime)
    verifier = PluginPackageVerifier(
        {"known": TrustedPublisher("known", key.public_key().public_bytes_raw(), "Gate publisher")},
        require_signature=False,
    )
    monkeypatch.setattr(plugins, "_plugin_package_verifier", lambda: verifier)
    app = FastAPI()
    app.include_router(plugins.router)
    async with Session(engine, expire_on_commit=False) as db:
        admin = User(
            username="gate-" + uuid4().hex,
            email=uuid4().hex + "@example.test",
            password_hash=hash_password(PASSWORD),
            is_admin=True,
        )
        db.add(admin)
        await db.commit()
        admin_id = admin.id
        authenticated_admin = SimpleNamespace(
            id=admin_id, password_hash=admin.password_hash, is_admin=True
        )
        app.dependency_overrides[plugins.get_plugin_manager_admin] = lambda: authenticated_admin
        app.dependency_overrides[get_db] = lambda: db
        async with original_async_client(
            transport=httpx.ASGITransport(app=app), base_url="http://gate.test"
        ) as client:
            harness = SimpleNamespace(
                client=client,
                admin=authenticated_admin,
                db=db,
                runtime=runtime,
                registry=registry,
                key=key,
                plugin_id=plugin_id,
                remote=remote,
                events=events,
                verifier=verifier,
            )
            try:
                yield harness
            finally:
                runtime.fail_commit = False
                runtime.ambiguous_commit = False
                await db.rollback()
                for model in (
                    PluginPermissionGrant,
                    PluginPermissionRequest,
                    PluginPermissionAudit,
                ):
                    await db.execute(delete(model).where(model.plugin_id.like(plugin_id + "%")))
                await db.execute(delete(User).where(User.id == admin_id))
                await db.commit()
    await engine.dispose()


async def seed_update(gate, source, *, trust="unsigned", permissions=()):
    if source.startswith("update"):
        payload = package_bytes(
            gate.plugin_id, version="1.0.0", trust=trust, key=gate.key, permissions=permissions
        )
        response = await gate.client.post(
            "/api/plugins/install",
            params={
                "allow_untrusted": "true",
                "approved_permissions": [name + ":v1" for name in permissions],
                "confirm_dangerous": True,
                "admin_password": PASSWORD,
            },
            files={"file": ("original.utp", payload)},
        )
        assert response.status_code == 201, response.text
    gate.events.clear()


async def acquire(gate, source, payload, **consent):
    params = {"allow_untrusted": "true", **consent}
    update = source.startswith("update")
    if source in {"url", "catalogue", "update-url", "update-catalogue"}:
        gate.remote["package"] = payload
        body = {
            "url": "https://packages.example/download",
            "source_type": "catalogue" if "catalogue" in source else "url",
        }
        if "catalogue" in source:
            body["catalogue_url"] = "https://catalogue.example/list.json"
        for field in ("admin_password", "confirm_dangerous", "expected_digest"):
            if field in params:
                body[field] = params.pop(field)
        path = f"/{gate.plugin_id}/update/url" if update else "/install/url"
        return await gate.client.post("/api/plugins" + path, params=params, json=body)
    filename = (
        "candidate.zip"
        if source == "zip"
        else "candidate.bin"
        if source == "content"
        else "candidate.utp"
    )
    path = f"/api/plugins/{gate.plugin_id}/update" if update else "/api/plugins/install"
    method = gate.client.put if update else gate.client.post
    return await method(
        path, params=params, files={"file": (filename, payload, "application/octet-stream")}
    )


async def grants(gate):
    gate.db.expire_all()
    return list(
        await gate.db.scalars(
            select(PluginPermissionGrant).where(
                PluginPermissionGrant.plugin_id == gate.plugin_id,
                PluginPermissionGrant.revoked_at.is_(None),
            )
        )
    )


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("trust", ("unsigned", "unknown_publisher", "trusted"))
async def test_every_source_uses_the_complete_lifecycle(gate, source, trust):
    await seed_update(gate, source, trust="trusted" if trust == "trusted" else "unsigned")
    payload = package_bytes(gate.plugin_id, permissions=("games.read",), trust=trust, key=gate.key)
    response = await acquire(gate, source, payload, approved_permissions=["games.read:v1"])
    assert response.status_code == (200 if source.startswith("update") else 201), response.text
    assert response.json()["trust_status"] == trust
    assert response.json()["status"] == "running"
    assert response.json()["healthy"] is True
    assert gate.events[-6:] == ["install", "commit", "finalize", "start", "health", "commit"]
    assert (
        gate.registry.root / gate.plugin_id / "plugin.py"
    ).read_bytes() == b"protocol fixture bytes\n"
    active_grants = await grants(gate)
    assert [row.capability for row in active_grants] == ["games.read"]
    assert str(active_grants[0].installation_id) == gate.registry.list()[0]["installation_id"]
    state = gate.registry.list()[0]
    assert state["trust"]["status"] == trust
    assert state["source"]["type"] == (
        "catalogue" if "catalogue" in source else "url" if "url" in source else "upload"
    )


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize(
    "broken",
    (
        "archive",
        "traversal",
        "duplicate",
        "manifest",
        "integrity",
        "malformed_signature",
        "signature",
        "symlink",
        "alternate_stream",
        "unicode_name",
    ),
)
async def test_invalid_packages_are_hard_failures_from_every_source(gate, source, broken):
    await seed_update(gate, source)
    payload = package_bytes(
        gate.plugin_id,
        key=gate.key,
        broken=broken,
        trust="invalid" if broken == "signature" else "unsigned",
    )
    response = await acquire(gate, source, payload, admin_password=PASSWORD, confirm_dangerous=True)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == (
        "invalid_signature" if broken in {"signature", "malformed_signature"} else "invalid_package"
    )
    assert "install" not in gate.events and "start" not in gate.events
    assert await grants(gate) == []


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("trust", ("unsigned", "unknown_publisher"))
async def test_dangerous_permissions_always_require_password_and_confirmation(gate, source, trust):
    await seed_update(gate, source)
    payload = package_bytes(gate.plugin_id, permissions=("api.full",), trust=trust, key=gate.key)
    for consent, status, code in (
        ({}, 409, "dangerous_permissions_confirmation_required"),
        ({"confirm_dangerous": True}, 401, "administrator_reauthentication_failed"),
        (
            {"confirm_dangerous": True, "admin_password": "wrong"},
            401,
            "administrator_reauthentication_failed",
        ),
    ):
        response = await acquire(
            gate, source, payload, approved_permissions=["api.full:v1"], **consent
        )
        assert response.status_code == status, response.text
        assert response.json()["detail"]["code"] == code
        assert "install" not in gate.events
        assert await grants(gate) == []
    response = await acquire(
        gate,
        source,
        payload,
        approved_permissions=["api.full:v1"],
        confirm_dangerous=True,
        admin_password=PASSWORD,
    )
    assert response.json()["dangerous_permissions_reauthenticated"] == ["api.full:v1"]
    assert [row.capability for row in await grants(gate)] == ["api.full"]


@pytest.mark.parametrize("source", SOURCES)
async def test_missing_dependencies_and_dependency_grant_inheritance_are_blocked(gate, source):
    await seed_update(gate, source)
    dependency_id = gate.plugin_id + ".dependency"
    payload = package_bytes(
        gate.plugin_id, dependencies=({"plugin_id": dependency_id, "version_range": "^1.0.0"},)
    )
    response = await acquire(gate, source, payload)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dependency_resolution_failed"
    assert "install" not in gate.events
    dependency_installation = uuid4()
    gate.registry.install_package(
        package_bytes(dependency_id, version="1.0.0", permissions=("api.full",)),
        "dependency.utp",
        installation_id=str(dependency_installation),
    )
    gate.db.add(
        PluginPermissionGrant(
            plugin_id=dependency_id,
            installation_id=dependency_installation,
            capability="api.full",
            capability_version=1,
        )
    )
    await gate.db.commit()
    response = await acquire(gate, source, payload, approved_permissions=["api.full:v1"])
    assert response.status_code == 400
    assert "install" not in gate.events
    response = await acquire(gate, source, payload)
    assert response.json()["status"] == "running"
    assert await grants(gate) == []


@pytest.mark.parametrize("source", SOURCES)
async def test_unverified_consent_and_bounded_acquisition_cannot_be_bypassed(
    gate, source, monkeypatch
):
    await seed_update(gate, source)
    payload = package_bytes(gate.plugin_id)
    response = await acquire(gate, source, payload, allow_untrusted="false")
    assert response.status_code == 409
    assert response.json()["detail"]["trust_status"] == "unsigned"
    assert "install" not in gate.events
    monkeypatch.setattr(plugins, "_MAX_PLUGIN_PACKAGE_BYTES", len(payload) - 1)
    response = await acquire(gate, source, payload)
    assert response.status_code == 413
    assert "install" not in gate.events


@pytest.mark.parametrize("source", SOURCES)
async def test_failed_atomic_install_rolls_back_grants_and_never_activates(gate, source):
    await seed_update(gate, source)
    gate.runtime.fail_install = True
    response = await acquire(
        gate,
        source,
        package_bytes(gate.plugin_id, permissions=("games.read",)),
        approved_permissions=["games.read:v1"],
    )
    assert response.status_code == 422
    assert "commit" not in gate.events and "start" not in gate.events
    assert await grants(gate) == []


@pytest.mark.parametrize("source", ("url", "catalogue", "update-url", "update-catalogue"))
async def test_remote_preview_digest_is_checked_in_the_canonical_lifecycle(gate, source):
    await seed_update(gate, source)
    response = await acquire(gate, source, package_bytes(gate.plugin_id), expected_digest="0" * 64)
    assert response.status_code == 409
    assert "install" not in gate.events


@pytest.mark.parametrize("source", ("update", "update-url", "update-catalogue"))
async def test_update_cannot_break_an_installed_dependents_version_constraint(gate, source):
    await seed_update(gate, source)
    gate.registry.install_package(
        package_bytes(
            gate.plugin_id + ".dependent",
            dependencies=({"plugin_id": gate.plugin_id, "version_range": "^1.0.0"},),
        ),
        "dependent.utp",
        installation_id=str(uuid4()),
    )
    response = await acquire(gate, source, package_bytes(gate.plugin_id))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dependency_resolution_failed"
    assert "install" not in gate.events


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize(
    "limit", ("max_entries", "max_file_bytes", "max_uncompressed_bytes", "max_compression_ratio")
)
async def test_archive_limits_are_enforced_before_any_grant_or_activation(gate, source, limit):
    await seed_update(gate, source)
    payload = package_bytes(gate.plugin_id)
    if limit == "max_compression_ratio":
        # Preserve the payload digest while recompressing the same package data.
        output = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(payload)) as original,
            zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive,
        ):
            for name in original.namelist():
                archive.writestr(name, original.read(name))
        payload = output.getvalue()
    setattr(gate.verifier, limit, 1)
    response = await acquire(gate, source, payload)
    assert response.status_code == 400, response.text
    assert "install" not in gate.events and "start" not in gate.events
    assert await grants(gate) == []


@pytest.mark.parametrize("source", ("update", "update-url", "update-catalogue"))
async def test_verified_update_retains_only_same_installation_grants_and_revokes_removals(
    gate, source
):
    await seed_update(gate, source, trust="trusted", permissions=("games.read", "media.read"))
    old_grants = await grants(gate)
    installation_id = old_grants[0].installation_id
    response = await acquire(
        gate,
        source,
        package_bytes(
            gate.plugin_id,
            trust="trusted",
            key=gate.key,
            permissions=("games.read", "notifications.send"),
        ),
        approved_permissions=["notifications.send:v1"],
    )
    assert response.status_code == 200, response.text
    delta = response.json()["permission_delta"]
    assert [ref["name"] for ref in delta["newly_requested_grants"]] == ["notifications.send"]
    active = await grants(gate)
    assert {row.capability for row in active} == {"games.read", "notifications.send"}
    assert {row.installation_id for row in active} == {installation_id}


@pytest.mark.parametrize("source", ("update", "update-url", "update-catalogue"))
async def test_becoming_trusted_does_not_retain_unverified_grants(gate, source):
    publisher = gate.verifier.publishers.pop("known")
    await seed_update(gate, source, trust="trusted", permissions=("games.read",))
    gate.verifier.publishers["known"] = publisher
    response = await acquire(
        gate,
        source,
        package_bytes(gate.plugin_id, trust="trusted", key=gate.key, permissions=("games.read",)),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaiting_permissions"
    assert gate.registry.package(gate.plugin_id)[1]["version"] == "1.0.0"
    assert gate.registry.health(gate.plugin_id)
    assert [row.capability for row in await grants(gate)] == ["games.read"]
    assert "install" not in gate.events


@pytest.mark.parametrize("source", ("update", "update-url", "update-catalogue"))
async def test_unverified_update_reauthenticates_even_unchanged_dangerous_grants(gate, source):
    await seed_update(gate, source, permissions=("api.full",))
    response = await acquire(
        gate,
        source,
        package_bytes(gate.plugin_id, permissions=("api.full",)),
        approved_permissions=["api.full:v1"],
        confirm_dangerous=True,
    )
    assert response.status_code == 401, response.text
    assert "install" not in gate.events
    assert [row.capability for row in await grants(gate)] == ["api.full"]


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("failure", ("start", "health"))
async def test_activation_failure_is_reported_after_a_successful_commit(gate, source, failure):
    await seed_update(gate, source)
    gate.runtime.fail_start = failure == "start"
    gate.runtime.healthy = failure != "health"
    response = await acquire(gate, source, package_bytes(gate.plugin_id))
    assert response.status_code == (200 if source.startswith("update") else 201), response.text
    if source.startswith("update"):
        assert response.json()["status"] == "rolled_back"
        assert response.json()["healthy"] is True
        assert gate.registry.package(gate.plugin_id)[1]["version"] == "1.0.0"
        assert gate.registry.health(gate.plugin_id)
    else:
        assert response.json()["status"] == (
            "failed_activation" if failure == "start" else "unhealthy"
        )
        assert response.json()["healthy"] is False
    assert gate.events.index("install") < gate.events.index("commit") < gate.events.index("start")


@pytest.mark.parametrize("source", SOURCES)
async def test_database_commit_failure_aborts_the_candidate_and_restores_old_grants(gate, source):
    await seed_update(gate, source, permissions=("games.read",))
    previous = gate.registry.list()
    gate.runtime.fail_commit = True
    with pytest.raises(IntegrityError):
        await acquire(
            gate,
            source,
            package_bytes(gate.plugin_id, permissions=("notifications.send",)),
            approved_permissions=["notifications.send:v1"],
        )
    gate.runtime.fail_commit = False
    assert "abort" in gate.events
    assert "finalize" not in gate.events and "start" not in gate.events
    assert gate.registry.list() == previous
    assert {row.capability for row in await grants(gate)} == (
        {"games.read"} if source.startswith("update") else set()
    )
    assert not list(gate.registry.root.glob(".backup-*"))


@pytest.mark.parametrize("source", SOURCES)
async def test_incomplete_finalization_cannot_activate_through_restart_or_enable(gate, source):
    await seed_update(gate, source)
    gate.runtime.fail_finish = True
    response = await acquire(gate, source, package_bytes(gate.plugin_id))
    assert response.status_code == 422
    assert "commit" in gate.events and "start" not in gate.events
    assert gate.registry.list()[0]["enabled"] is False
    with pytest.raises(ValueError, match="permission commit"):
        gate.registry.start(gate.plugin_id)
    gate.registry.restore_enabled()
    assert gate.registry.health(gate.plugin_id) is False


@pytest.mark.parametrize("source", SOURCES)
async def test_lost_database_commit_acknowledgement_keeps_candidate_disabled(gate, source):
    await seed_update(gate, source)
    gate.runtime.ambiguous_commit = True
    with pytest.raises(OperationalError, match="lost commit acknowledgement"):
        await acquire(
            gate,
            source,
            package_bytes(gate.plugin_id, trust="trusted", key=gate.key, permissions=("api.full",)),
            approved_permissions=["api.full:v1"],
        )
    gate.runtime.ambiguous_commit = False
    # The database did commit. Starting the old unverified package would now
    # expose it to this grant without password reauthentication.
    assert [row.capability for row in await grants(gate)] == ["api.full"]
    assert "abort" not in gate.events and "start" not in gate.events
    assert gate.registry.list()[0]["enabled"] is False
    with pytest.raises(ValueError, match="permission commit"):
        gate.registry.start(gate.plugin_id)
    gate.registry.restore_enabled()
    assert gate.registry.health(gate.plugin_id) is False


@pytest.mark.parametrize("source", ("update", "update-url", "update-catalogue"))
async def test_concurrent_update_cannot_apply_a_stale_plan(gate, source):
    await seed_update(gate, source)
    gate.runtime.changed_version = True
    response = await acquire(gate, source, package_bytes(gate.plugin_id))
    assert response.status_code == 422, response.text
    assert "version changed" in response.json()["detail"]
    assert "commit" not in gate.events and "start" not in gate.events
    assert gate.registry.list()[0]["version"] == "1.5.0"
    assert await grants(gate) == []


@pytest.mark.parametrize("source", ("update", "update-url", "update-catalogue"))
async def test_trusted_installation_cannot_be_taken_over_by_unverified_publisher(gate, source):
    await seed_update(gate, source, trust="trusted", permissions=("games.read",))
    response = await acquire(
        gate,
        source,
        package_bytes(gate.plugin_id, trust="unknown_publisher", key=gate.key),
        admin_password=PASSWORD,
        confirm_dangerous=True,
    )
    assert response.status_code == 409
    assert "publisher" in response.json()["detail"]
    assert "install" not in gate.events
    assert [row.capability for row in await grants(gate)] == ["games.read"]
