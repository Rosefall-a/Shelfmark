"""Regression tests for game-note title validation and conflict-safe operations."""

from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException

from src.api.routes import games


USER_ID = UUID("00000000-0000-0000-0000-000000000001")
GAME_ID = UUID("00000000-0000-0000-0000-000000000002")


class FakeGame:
    id = GAME_ID
    user_id = USER_ID
    folder_location = "test-game"


class FakeUser:
    id = USER_ID


class FakeDB:
    async def scalar(self, _statement):
        return FakeGame()


@pytest.fixture
def note_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(games, "_DATA_ROOT", tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "title",
    [
        "what is this for",
        "Quest Log - Main Story",
        "Build #2 (final!)",
        "A.B.C",
        "100% complete",
        "Bob's notes & plans",
    ],
)
def test_note_title_accepts_human_readable_names(title: str) -> None:
    assert games._normalize_note_name(title) == title


@pytest.mark.parametrize(
    "title",
    [
        "",
        ".",
        "..",
        "../outside",
        r"..\\outside",
        "/absolute/path",
        r"C:\\outside",
        "bad\x00title",
        "bad\ntitle",
        ".hidden",
        "trailing.",
        "trailing.",
        "CON",
        "NUL",
    ],
)
def test_note_title_rejects_path_like_or_unsafe_names(title: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        games._normalize_note_name(title)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_duplicate_creation_returns_conflict_without_overwriting(note_storage: Path):
    db = FakeDB()
    user = FakeUser()
    await games.create_game_note(
        GAME_ID, "what is this for", games.NoteWrite(content="original"), db, user
    )

    with pytest.raises(HTTPException) as exc_info:
        await games.create_game_note(
            GAME_ID, "what is this for", games.NoteWrite(content="replacement"), db, user
        )

    assert exc_info.value.status_code == 409
    path = note_storage / str(USER_ID) / "games" / "test-game" / "notes" / "what is this for.md"
    assert path.read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_successful_rename_preserves_content(note_storage: Path):
    db = FakeDB()
    user = FakeUser()
    await games.create_game_note(
        GAME_ID, "Original note", games.NoteWrite(content="# Keep me"), db, user
    )

    result = await games.rename_game_note(
        GAME_ID, "Original note", games.NoteRename(new_name="Renamed note"), db, user
    )

    assert result["note_name"] == "Renamed note"
    old_path = note_storage / str(USER_ID) / "games" / "test-game" / "notes" / "Original note.md"
    new_path = note_storage / str(USER_ID) / "games" / "test-game" / "notes" / "Renamed note.md"
    assert not old_path.exists()
    assert new_path.read_text(encoding="utf-8") == "# Keep me"


@pytest.mark.asyncio
async def test_duplicate_rename_returns_conflict_and_keeps_both_notes(note_storage: Path):
    db = FakeDB()
    user = FakeUser()
    await games.create_game_note(GAME_ID, "First note", games.NoteWrite(content="first"), db, user)
    await games.create_game_note(GAME_ID, "Second note", games.NoteWrite(content="second"), db, user)

    with pytest.raises(HTTPException) as exc_info:
        await games.rename_game_note(
            GAME_ID, "First note", games.NoteRename(new_name="Second note"), db, user
        )

    assert exc_info.value.status_code == 409
    notes = note_storage / str(USER_ID) / "games" / "test-game" / "notes"
    assert (notes / "First note.md").read_text(encoding="utf-8") == "first"
    assert (notes / "Second note.md").read_text(encoding="utf-8") == "second"


@pytest.mark.asyncio
async def test_same_name_rename_is_a_no_op(note_storage: Path):
    db = FakeDB()
    user = FakeUser()
    await games.create_game_note(GAME_ID, "Same note", games.NoteWrite(content="content"), db, user)

    result = await games.rename_game_note(
        GAME_ID, "Same note", games.NoteRename(new_name="Same note"), db, user
    )

    assert result["note_name"] == "Same note"
    path = note_storage / str(USER_ID) / "games" / "test-game" / "notes" / "Same note.md"
    assert path.read_text(encoding="utf-8") == "content"


@pytest.mark.asyncio
async def test_rename_failure_does_not_remove_source(note_storage: Path, monkeypatch):
    db = FakeDB()
    user = FakeUser()
    await games.create_game_note(
        GAME_ID, "Source note", games.NoteWrite(content="safe"), db, user
    )

    def fail_link(_source, _destination):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(games.os, "link", fail_link)

    with pytest.raises(HTTPException) as exc_info:
        await games.rename_game_note(
            GAME_ID, "Source note", games.NoteRename(new_name="New note"), db, user
        )

    assert exc_info.value.status_code == 500
    notes = note_storage / str(USER_ID) / "games" / "test-game" / "notes"
    assert (notes / "Source note.md").read_text(encoding="utf-8") == "safe"
    assert not (notes / "New note.md").exists()


@pytest.mark.asyncio
async def test_update_existing_note_is_not_a_create_operation(note_storage: Path):
    db = FakeDB()
    user = FakeUser()
    await games.create_game_note(
        GAME_ID, "Editable note", games.NoteWrite(content="before"), db, user
    )
    await games.update_game_note(
        GAME_ID, "Editable note", games.NoteWrite(content="after"), db, user
    )

    path = note_storage / str(USER_ID) / "games" / "test-game" / "notes" / "Editable note.md"
    assert path.read_text(encoding="utf-8") == "after"
