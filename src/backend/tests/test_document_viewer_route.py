from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile

from src.api.routes import games
from src.helpers.document_viewer import document_view_response


@pytest.mark.asyncio
async def test_document_view_endpoint_uses_current_user_game_scope(
    monkeypatch, tmp_path: Path
) -> None:
    game = SimpleNamespace(
        id="game-id",
        user_id="owner-id",
        folder_location="Library",
    )
    user = SimpleNamespace(id="owner-id")
    monkeypatch.setattr(games, "_get_game_or_404", AsyncMock(return_value=game))
    monkeypatch.setattr(games, "_DATA_ROOT", tmp_path)

    document = tmp_path / "owner-id" / "games" / "Library" / "docs" / "manual.txt"
    document.parent.mkdir(parents=True)
    document.write_text("safe", encoding="utf-8")

    db = AsyncMock()
    response = await games.view_game_document(
        "game-id",
        "doc",
        "manual.txt",
        db=db,
        current_user=user,
    )

    assert response.media_type == "text/plain"
    games._get_game_or_404.assert_awaited_once_with("game-id", db, "owner-id")


@pytest.mark.asyncio
async def test_document_view_endpoint_rejects_non_document_kind(monkeypatch) -> None:
    with pytest.raises(HTTPException) as exc:
        await games.view_game_document(
            "game-id",
            "modpack",
            "archive.zip",
            db=AsyncMock(),
            current_user=SimpleNamespace(id="owner-id"),
        )

    assert exc.value.status_code == 415


def test_document_view_helper_rejects_missing_and_traversal(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as missing:
        document_view_response(tmp_path / "missing.txt", "missing.txt")
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as traversal:
        document_view_response(tmp_path / "secret.txt", "../secret.txt")
    assert traversal.value.status_code == 400


@pytest.mark.asyncio
async def test_game_file_upload_accepts_singular_file_field(monkeypatch, tmp_path: Path) -> None:
    game = SimpleNamespace(id="game-id", user_id="owner-id", folder_location="Library")
    user = SimpleNamespace(id="owner-id")
    monkeypatch.setattr(games, "_get_game_or_404", AsyncMock(return_value=game))
    monkeypatch.setattr(games, "_DATA_ROOT", tmp_path)
    monkeypatch.setattr(
        games, "save_media_bytes", lambda data, dest_dir, filename: dest_dir / filename
    )

    db = AsyncMock()
    upload = UploadFile(file=BytesIO(b"manual"), filename="manual.txt")
    result = await games.upload_game_files(
        "game-id", "doc", file=upload, db=db, current_user=user
    )

    assert result["results"] == [{"filename": "manual.txt", "status": "saved", "size": 6}]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_media_upload_accepts_singular_file_field(monkeypatch, tmp_path: Path) -> None:
    game = SimpleNamespace(id="game-id", user_id="owner-id", folder_location="Library")
    user = SimpleNamespace(id="owner-id")
    monkeypatch.setattr(games, "_get_game_or_404", AsyncMock(return_value=game))
    monkeypatch.setattr(games, "_DATA_ROOT", tmp_path)
    monkeypatch.setattr(
        games, "save_media_bytes", lambda data, dest_dir, filename: dest_dir / filename
    )
    db = AsyncMock()
    upload = UploadFile(file=BytesIO(b"image"), filename="image.png")
    result = await games.upload_game_screenshots(
        "game-id", file=upload, db=db, current_user=user
    )
    assert result["results"] == [
        {"filename": "image.png", "status": "saved", "kind": "screenshot"}
    ]
    db.commit.assert_awaited_once()
