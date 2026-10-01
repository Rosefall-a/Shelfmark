"""PR #241 format regressions plus persisted ownership and live-grant checks."""

import base64
import hashlib
import json
import mimetypes
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import ARRAY
from test_plugin_authorization_http import boundary as authorization_boundary
from test_plugin_authorization_http import grant, request

from src.database.models.game import Game
from src.database.models.game_file_item import GameFileItem
from src.plugin_api import gateway
from src.plugin_api.documents import (
    MAX_DOCUMENT_BYTES,
    DocumentAccessError,
    document_path,
    read_representation,
)

boundary = authorization_boundary


@pytest.fixture
def stored(boundary, tmp_path, monkeypatch):
    # SQLite executes the actual ownership queries; only PG array storage is adapted.
    for column in Game.__table__.columns:
        if isinstance(column.type, ARRAY):
            monkeypatch.setattr(column, "type", JSON())
    Game.__table__.create(boundary.session.bind)
    GameFileItem.__table__.create(boundary.session.bind)
    monkeypatch.setattr(gateway, "_DATA_ROOT", tmp_path)
    games = []
    for user in boundary.users:
        game = Game(
            id=uuid4(), user_id=user.id, folder_location="Library", title="Game", sort_title="Game"
        )
        boundary.session.add(game)
        games.append(game)
    boundary.session.commit()

    def save(name="abcdefgh_manual.txt", data=b"safe", owner=0, kind="doc", **changes):
        game = games[owner]
        root = tmp_path / str(game.user_id) / "games" / game.folder_location / "docs"
        root.mkdir(parents=True, exist_ok=True)
        if "/" not in name and "\\" not in name:
            (root / name).write_bytes(data)
        item = GameFileItem(
            id=uuid4(), game_id=game.id, kind=kind, filename=name, created_at=1, **changes
        )
        boundary.session.add(item)
        boundary.session.commit()
        return item

    return boundary, save, games


async def read(boundary, document_id, **changes):
    return await request(
        boundary,
        method="documents.read",
        capability="documents.read",
        payload={"document_id": str(document_id), "chunk_bytes": 24576, **changes},
    )


@pytest.mark.asyncio
async def test_persisted_document_ownership_missing_deleted_and_kind(stored):
    boundary, save, games = stored
    grant(boundary, "documents.read")
    own = save()
    other = save(owner=1)
    trashed = save("trashed.txt", deleted_at=1)
    modpack = save("archive.txt", kind="modpack")
    for item_id in (other.id, trashed.id, modpack.id, uuid4()):
        response = await read(boundary, item_id)
        assert response.status_code == 200  # Explicit domain error inside the gateway payload.
        assert response.json()["payload"]["error"] == {
            "kind": "missing",
            "message": "Document not found.",
            "status_code": 404,
        }
        assert "safe" not in response.text
    response = await read(boundary, own.id)
    assert base64.b64decode(response.json()["payload"]["content"]) == b"safe"
    games[0].deleted_at = 1
    boundary.session.commit()
    assert (await read(boundary, own.id)).json()["payload"]["error"]["kind"] == "missing"


@pytest.mark.asyncio
async def test_documents_require_live_grants_on_every_chunk(stored):
    boundary, save, _ = stored
    item = save(data=b"x" * 50000)
    assert (await read(boundary, item.id)).status_code == 403
    permission = grant(boundary, "documents.read")
    first = (await read(boundary, item.id)).json()["payload"]
    permission.revoked_at = 1
    boundary.session.commit()
    assert (
        await read(boundary, item.id, offset=24576, content_sha256=first["content_sha256"])
    ).status_code == 403


@pytest.mark.asyncio
async def test_document_entrypoints_require_authentication(stored):
    boundary, save, _ = stored
    save()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app), base_url="http://test"
    ) as client:
        for path in ("/api/plugins/audit.plugin/actions/read", "/api/plugins/audit.plugin/probe"):
            response = await client.post(path, json={})
            assert response.status_code == 401
        response = await client.post(
            "/api/plugins/runtime/gateway",
            json={
                "plugin_id": "audit.plugin",
                "installation_id": str(boundary.installation_id),
                "request_id": str(uuid4()),
                "user_id": str(boundary.users[0].id),
                "method": "documents.list",
                "capability": "documents.read",
            },
        )
        assert response.status_code == 503  # Runtime trust token is required, even with a user ID.


@pytest.mark.asyncio
async def test_stored_traversal_and_bounded_paginated_listing(stored):
    boundary, save, games = stored
    grant(boundary, "documents.read")
    for name in ("../secret.txt", r"..\secret.txt", "..%2fsecret.txt", "..%5csecret.txt"):
        item = save(name)
        result = (await read(boundary, item.id)).json()["payload"]
        assert result["error"]["status_code"] == 400
    games[0].title = "😀" * 500
    boundary.session.commit()
    expected = {str(save(f"file-{number:02}.txt").id) for number in range(20)}
    save("other-user.txt", owner=1)
    seen, offset = set(), 0
    while offset is not None:
        response = await request(
            boundary,
            method="documents.list",
            capability="documents.read",
            payload={"limit": 32, "offset": offset},
        )
        result = response.json()["payload"]
        assert len(json.dumps(result).encode()) < 64 * 1024
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        seen.update(item["id"] for item in result["documents"])
        offset = result["next_offset"]
    assert seen == expected


@pytest.mark.asyncio
async def test_bounded_chunks_reassemble_exact_limit_and_detect_replacement(stored, tmp_path):
    boundary, save, games = stored
    grant(boundary, "documents.read")
    data = ("café\n" * (MAX_DOCUMENT_BYTES // 6)).encode()
    data += b"x" * (MAX_DOCUMENT_BYTES - len(data))
    item = save(data=data)
    pieces = []
    offset, digest = 0, None
    while True:
        response = await read(boundary, item.id, offset=offset, content_sha256=digest)
        result = response.json()["payload"]
        assert len(response.content) < 64 * 1024
        assert result["document"]["media_type"] == "text/plain"
        assert result["offset"] == offset
        pieces.append(base64.b64decode(result["content"]))
        offset, digest = result["next_offset"], result["content_sha256"]
        if result["complete"]:
            break
    assert b"".join(pieces) == data
    assert digest == hashlib.sha256(data).hexdigest()
    root = tmp_path / str(games[0].user_id) / "games/Library/docs"
    (root / item.filename).write_bytes(b"y" * len(data))
    changed = (await read(boundary, item.id, offset=24576, content_sha256=digest)).json()["payload"]
    assert changed["error"]["status_code"] == 409


@pytest.mark.parametrize(
    "name",
    [
        "../secret.txt",
        r"..\secret.txt",
        "a/b.txt",
        "..%2fsecret.txt",
        "..%5csecret.txt",
        "%2e%2e",
        "C:secret.txt",
        "",
        ".",
        "..",
    ],
)
def test_traversal_rejected_without_normalization(tmp_path, name):
    with pytest.raises(DocumentAccessError) as error:
        document_path(tmp_path, uuid4(), "Library", name)
    assert error.value.status_code == 400


def test_folder_traversal_and_symlink_escape(tmp_path):
    user_id = uuid4()
    with pytest.raises(DocumentAccessError):
        document_path(tmp_path, user_id, "../../other", "secret.txt")
    root = tmp_path / str(user_id) / "games/Library/docs"
    root.mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("OS symlink privilege unavailable")
    with pytest.raises(DocumentAccessError) as error:
        document_path(tmp_path, user_id, "Library", "link.txt")
    assert error.value.status_code == 404


@pytest.mark.parametrize(
    "extension",
    [
        "cfg",
        "conf",
        "csv",
        "ini",
        "json",
        "log",
        "md",
        "nfo",
        "properties",
        "toml",
        "txt",
        "xml",
        "yaml",
        "yml",
        "jsonld",
    ],
)
def test_pr241_utf8_allowlist_and_literal_text(tmp_path, monkeypatch, extension):
    if extension == "jsonld":
        mimetypes.init()
        monkeypatch.setitem(mimetypes.types_map, ".jsonld", "application/ld+json")
    path = tmp_path / f"abcdefgh_notes.{extension}"
    data = "<script>alert(1)</script> café\n".encode()
    path.write_bytes(data)
    result = read_representation(path)
    assert result[:3] == (data, "text/plain", "text")


@pytest.mark.parametrize("extension", ["html", "htm", "xhtml"])
def test_pr241_html_is_plain_text_transport_with_format_hint(tmp_path, extension):
    path = tmp_path / f"page.{extension}"
    path.write_bytes(b"<script>alert(1)</script><h1>Hello</h1>")
    assert read_representation(path)[1:3] == ("text/plain", "html")


@pytest.mark.parametrize(
    ("name", "data", "status"),
    [
        ("evil.svg", b"<svg onload='alert(1)'/>", 415),
        ("bad.pdf", b"broken PDF", 415),
        ("binary.txt", b"hello\x00world", 415),
        ("latin.txt", b"caf\xe9", 415),
        ("unsupported.docx", b"PK zip", 415),
        ("large.txt", b"x" * (MAX_DOCUMENT_BYTES + 1), 413),
    ],
    ids=["svg", "malformed-pdf", "binary", "latin1", "unsupported", "oversized"],
)
def test_pr241_rejections(tmp_path, name, data, status):
    path = tmp_path / name
    path.write_bytes(data)
    with pytest.raises(DocumentAccessError) as error:
        read_representation(path)
    assert error.value.status_code == status


@pytest.mark.parametrize("name", ["manual.pdf", "manual.bin"])
def test_pr241_pdf_signature_overrides_extension(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.7\n% fixture")
    assert read_representation(path)[1:3] == ("application/pdf", "pdf")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"document_id": "../secret.txt"},
        {"offset": -1},
        {"chunk_bytes": 24577},
        {"offset": True},
        {"offset": 1},
    ],
)
async def test_invalid_chunk_request_is_explicit(stored, payload):
    boundary, save, _ = stored
    grant(boundary, "documents.read")
    item = save()
    changes = {"document_id": str(item.id), **payload}
    result = (await read(boundary, **changes)).json()["payload"]
    assert result["error"]["status_code"] in {400, 409}
    assert len(json.dumps(result)) < 1024
