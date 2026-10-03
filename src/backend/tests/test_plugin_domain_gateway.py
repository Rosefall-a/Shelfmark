from __future__ import annotations

import asyncio
import base64
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.database.models.auth import UserSession
from src.database.models.game import Game
from src.database.models.game_file_item import GameFileItem
from src.plugin_api import gateway


class FakeResult:
    def __init__(self, *, rows=None, scalar_rows=None, one=None, rowcount=0):
        self._rows = rows or []
        self._scalar_rows = scalar_rows or []
        self._one = one
        self.rowcount = rowcount

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._one

    def scalars(self):
        return SimpleNamespace(all=lambda: self._scalar_rows)


class FakeDb:
    def __init__(self, *, scalar_results=None, execute_results=None):
        self.scalar_results = list(scalar_results or [object()])
        self.execute_results = list(execute_results or [])
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.scalar_results.pop(0)

    async def execute(self, _statement):
        return self.execute_results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


def dispatch(db, *, method, capability, payload=None, user_id=None, installation_id=None):
    return asyncio.run(
        gateway.dispatch_gateway_request(
            db,
            plugin_id="example.plugin",
            installation_id=installation_id or uuid4(),
            user_id=user_id or uuid4(),
            method=method,
            capability=capability,
            payload=payload or {},
        )
    )


def test_gateway_rejects_capability_confusion_before_dispatch() -> None:
    with pytest.raises(PermissionError, match="requires capability games.read"):
        dispatch(FakeDb(), method="games.list", capability="documents.read")


def test_gateway_rejects_missing_installation_grant() -> None:
    with pytest.raises(PermissionError, match="has not been granted"):
        dispatch(
            FakeDb(scalar_results=[None, None, None]),
            method="sessions.list",
            capability="sessions.read",
        )


def test_documents_read_returns_bounded_safe_content(tmp_path, monkeypatch) -> None:
    user_id = uuid4()
    game_id = uuid4()
    document_id = uuid4()
    document_root = tmp_path / str(user_id) / "games" / "example" / "docs"
    document_root.mkdir(parents=True)
    (document_root / "manual.txt").write_text("safe text", encoding="utf-8")
    game = Game(
        id=game_id,
        user_id=user_id,
        folder_location="example",
        title="Example",
        sort_title="Example",
    )
    item = GameFileItem(
        id=document_id,
        game_id=game_id,
        kind="doc",
        filename="manual.txt",
        created_at=1,
    )
    monkeypatch.setattr(gateway, "_DATA_ROOT", tmp_path)
    db = FakeDb(execute_results=[FakeResult(one=(item, game))])

    result = dispatch(
        db,
        method="documents.read",
        capability="documents.read",
        payload={"document_id": str(document_id)},
        user_id=user_id,
    )

    assert result["document"]["id"] == str(document_id)
    assert result["document"]["media_type"] == "text/plain"
    assert base64.b64decode(result["content"]) == b"safe text"
    assert str(tmp_path) not in str(result)


def test_documents_read_supports_html_representation(tmp_path, monkeypatch) -> None:
    user_id = uuid4()
    game_id = uuid4()
    document_id = uuid4()
    document_root = tmp_path / str(user_id) / "games" / "example" / "docs"
    document_root.mkdir(parents=True)
    (document_root / "page.html").write_text(
        "<h1>Safe</h1><script>alert(1)</script>", encoding="utf-8"
    )
    game = Game(
        id=game_id,
        user_id=user_id,
        folder_location="example",
        title="Example",
        sort_title="Example",
    )
    item = GameFileItem(
        id=document_id,
        game_id=game_id,
        kind="doc",
        filename="page.html",
        created_at=1,
    )
    monkeypatch.setattr(gateway, "_DATA_ROOT", tmp_path)
    db = FakeDb(execute_results=[FakeResult(one=(item, game))])

    result = dispatch(
        db,
        method="documents.read",
        capability="documents.read",
        payload={"document_id": str(document_id)},
        user_id=user_id,
    )
    assert result["document"]["media_type"] == "text/html"
    assert base64.b64decode(result["content"]) == b"<h1>Safe</h1><script>alert(1)</script>"


def test_session_access_exposes_no_credentials_and_revoke_is_user_scoped() -> None:
    user_id = uuid4()
    session_id = uuid4()
    session = UserSession(
        id=session_id,
        user_id=user_id,
        token_hash="a" * 64,
        created_at=1,
        expires_at=int(time.time()) + 60,
    )
    listed = dispatch(
        FakeDb(execute_results=[FakeResult(rows=[(session, "owner")])]),
        method="sessions.list",
        capability="sessions.read",
        user_id=user_id,
    )
    assert listed["sessions"][0]["id"] == str(session_id)
    assert "token" not in str(listed).lower()

    db = FakeDb(execute_results=[FakeResult(rowcount=1)])
    revoked = dispatch(
        db,
        method="sessions.revoke",
        capability="sessions.revoke",
        payload={"session_id": str(session_id), "confirmed": True},
        user_id=user_id,
    )
    assert revoked == {"revoked": True, "session_id": str(session_id)}
    assert db.commits == 1


def test_notification_provider_registration_is_namespaced_and_durable() -> None:
    installation_id = uuid4()
    db = FakeDb(scalar_results=[object(), None])
    result = dispatch(
        db,
        method="notification_providers.register",
        capability="notification_providers.register",
        installation_id=installation_id,
        payload={
            "provider_id": "example.plugin.webhook",
            "name": "Example webhook",
            "action_id": "deliver",
        },
    )
    assert result["registered"] is True
    assert db.added[0].installation_id == installation_id
    assert db.commits == 1

    with pytest.raises(ValueError, match="must start"):
        dispatch(
            FakeDb(scalar_results=[object()]),
            method="notification_providers.register",
            capability="notification_providers.register",
            installation_id=installation_id,
            payload={
                "provider_id": "someone-else.webhook",
                "name": "Wrong namespace",
                "action_id": "deliver",
            },
        )


def test_notification_provider_registration_rejects_secret_configuration() -> None:
    with pytest.raises(ValueError, match="registration is invalid"):
        dispatch(
            FakeDb(scalar_results=[object()]),
            method="notification_providers.register",
            capability="notification_providers.register",
            payload={
                "provider_id": "example.plugin.webhook",
                "name": "Example webhook",
                "action_id": "deliver",
                "webhook_url": "https://example.invalid/secret",
            },
        )
