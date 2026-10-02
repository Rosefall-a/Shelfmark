"""PR #241 format regressions plus persisted ownership and live-grant checks."""

import base64
import hashlib
import io
import json
import mimetypes
import zipfile
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import ARRAY
from test_plugin_authorization_http import boundary as authorization_boundary
from test_plugin_authorization_http import grant, request

from src.api.routes import games as game_routes
from src.api.routes import plugins
from src.database.models.game import Game, GameLink
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
    GameLink.__table__.create(boundary.session.bind)
    GameFileItem.__table__.create(boundary.session.bind)
    monkeypatch.setattr(gateway, "_DATA_ROOT", tmp_path)
    monkeypatch.setattr(plugins, "_DOCUMENT_DATA_ROOT", tmp_path)
    monkeypatch.setattr(game_routes, "_DATA_ROOT", tmp_path)
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
async def test_configurable_preview_limit_can_exceed_legacy_cap_and_be_unlimited(stored):
    boundary, save, _ = stored
    grant(boundary, "documents.read")
    data = b"x" * (MAX_DOCUMENT_BYTES + 1024)
    item = save(data=data)

    bounded = await read(boundary, item.id, max_bytes=MAX_DOCUMENT_BYTES)
    assert bounded.json()["payload"]["error"]["status_code"] == 413

    extended = await read(
        boundary, item.id, max_bytes=MAX_DOCUMENT_BYTES + 1024, offset=0
    )
    payload = extended.json()["payload"]
    assert payload["document"]["size_bytes"] == len(data)
    assert payload["complete"] is False

    unlimited = await read(boundary, item.id, max_bytes=0, offset=0)
    unlimited_payload = unlimited.json()["payload"]
    assert unlimited_payload["document"]["size_bytes"] == len(data)
    assert unlimited_payload["next_offset"] == 24576

async def test_invalid_chunk_request_is_explicit(stored, payload):
    boundary, save, _ = stored
    grant(boundary, "documents.read")
    item = save()
    changes = {"document_id": str(item.id), **payload}
    result = (await read(boundary, **changes)).json()["payload"]
    assert result["error"]["status_code"] in {400, 409}
    assert len(json.dumps(result)) < 1024


@pytest.mark.asyncio
async def test_scoped_download_checks_owner_grants_and_safe_attachment(stored):
    boundary, save, _ = stored
    item = save("abcdefgh_active.svg", b"<svg onload='evil()'/>")
    other = save(owner=1)
    path = f"/api/plugins/audit.plugin/capabilities/documents/{item.id}/download"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app), base_url="http://test"
    ) as client:
        assert (await client.get(path)).status_code == 401
        client.cookies.set("session", boundary.tokens[boundary.users[0].id])
        assert (await client.get(path)).status_code == 403
        permission = grant(boundary, "documents.read")
        response = await client.get(path)
        assert response.status_code == 200 and response.content == b"<svg onload='evil()'/>"
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment;")
        assert "active.svg" in response.headers["content-disposition"]
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        response = await client.head(path)
        assert response.status_code == 200 and response.content == b""
        for document_id in (other.id, uuid4()):
            assert (
                await client.get(path.replace(str(item.id), str(document_id)))
            ).status_code == 404
        unsafe = save("..%2fsecret.txt")
        assert (await client.get(path.replace(str(item.id), str(unsafe.id)))).status_code == 400
        permission.revoked_at = 1
        boundary.session.commit()
        assert (await client.get(path)).status_code == 403


@pytest.mark.asyncio
async def test_game_docs_listing_supplies_the_indexed_reader_id(stored):
    boundary, save, games = stored
    item = save()
    response = await game_routes.list_game_files(games[0].id, "doc", boundary.db, boundary.users[0])
    assert response["files"][0]["id"] == str(item.id)
    assert response["files"][0]["url"].endswith("/files/doc/abcdefgh_manual.txt")
    with pytest.raises(plugins.HTTPException) as failure:
        await game_routes.list_game_files(games[1].id, "doc", boundary.db, boundary.users[0])
    assert failure.value.status_code == 404


@pytest.mark.asyncio
async def test_authenticated_frontend_inlines_verified_css_and_scripts(stored):
    boundary, _, _ = stored
    ui = boundary.runtime.plugin_ui.return_value
    ui["frontend"] = {"entry": "frontend/index.html", "inline_assets": True}
    assets = {
        "frontend/index.html": b'<link rel="stylesheet" href="./style.css"><script src="./app.js"></script>',
        "frontend/style.css": b"body {margin: 0}",
        "frontend/app.js": b"window.started=true;",
    }
    boundary.runtime.frontend_asset = AsyncMock(side_effect=lambda _plugin, path: assets[path])
    path = "/api/plugins/audit.plugin/frontend/frontend/index.html"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app), base_url="http://test"
    ) as client:
        assert (await client.get(path)).status_code == 401
        client.cookies.set("session", boundary.tokens[boundary.users[0].id])
        response = await client.get(path)
        assert response.status_code == 200
        assert "body {margin: 0}" in response.text and "window.started=true" in response.text
        assert " src=" not in response.text and " href=" not in response.text
        nonce = response.text.split('nonce="')[1].split('"')[0]
        assert f"'nonce-{nonce}'" in response.headers["content-security-policy"]
        assert "'unsafe-eval'" not in response.headers["content-security-policy"]
        assert "script-src 'unsafe-inline'" not in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "private, no-store"
        assert (
            (await client.get(path.replace("index.html", "style.css")))
            .headers["content-type"]
            .startswith("text/css")
        )


@pytest.mark.asyncio
async def test_oversized_preview_still_allows_scoped_original_download(stored):
    boundary, save, _ = stored
    item = save("abcdefgh_big.pdf", b"%PDF-" + b"x" * MAX_DOCUMENT_BYTES)
    grant(boundary, "documents.read")
    assert (await read(boundary, item.id)).json()["payload"]["error"]["status_code"] == 413
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app),
        base_url="http://test",
        cookies={"session": boundary.tokens[boundary.users[0].id]},
    ) as client:
        response = await client.head(
            f"/api/plugins/audit.plugin/capabilities/documents/{item.id}/download"
        )
        assert response.status_code == 200
        assert int(response.headers["content-length"]) > MAX_DOCUMENT_BYTES


def office_archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.parametrize("suffix", ["docx", "pptx", "odt", "odp"])
def test_office_previews_validate_safe_containers(tmp_path, suffix):
    from src.plugin_api.documents import OFFICE_TYPES

    files = {"[Content_Types].xml": b"<Types/>"}
    if suffix in {"docx", "pptx"}:
        files["word/document.xml" if suffix == "docx" else "ppt/presentation.xml"] = b"<document/>"
    else:
        files.update(
            {"content.xml": b"<document-content/>", "mimetype": OFFICE_TYPES["." + suffix].encode()}
        )
    path = tmp_path / ("manual." + suffix)
    path.write_bytes(office_archive(files))
    assert read_representation(path)[1:3] == (OFFICE_TYPES["." + suffix], suffix)
    for name, value in (
        ("../secret.xml", b"<evil/>"),
        ("word/vbaProject.bin", b"macro"),
        (
            "word/document.xml",
            b'<!DOCTYPE doc [<!ENTITY evil SYSTEM "file:///etc/passwd">]><doc>&evil;</doc>',
        ),
        ("invalid.xml", b"<malformed"),
    ):
        malicious = {**files, name: value}
        path.write_bytes(office_archive(malicious))
        with pytest.raises(DocumentAccessError):
            read_representation(path)


def test_office_xml_entities_cannot_hide_in_utf16(tmp_path):
    path = tmp_path / "manual.docx"
    path.write_bytes(
        office_archive(
            {
                "[Content_Types].xml": b"<Types/>",
                "word/document.xml": '<!DOCTYPE doc [<!ENTITY x "evil">]><doc>&x;</doc>'.encode(
                    "utf-16"
                ),
            }
        )
    )
    with pytest.raises(DocumentAccessError):
        read_representation(path)


def test_office_zip_bombs_and_macros_are_rejected(tmp_path):
    path = tmp_path / "manual.docx"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * (2 * 1024 * 1024 + 1))
    path.write_bytes(buffer.getvalue())
    with pytest.raises(DocumentAccessError):
        read_representation(path)
    path.write_bytes(
        office_archive(
            {
                "[Content_Types].xml": b'<Types><Override ContentType="macroEnabled"/></Types>',
                "word/document.xml": b"<document/>",
            }
        )
    )
    with pytest.raises(DocumentAccessError):
        read_representation(path)
