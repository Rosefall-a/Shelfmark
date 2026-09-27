from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

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

    response = await games.view_game_document(
        "game-id",
        "doc",
        "manual.txt",
        db=AsyncMock(),
        current_user=user,
    )

    assert response.media_type == "text/plain"


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
