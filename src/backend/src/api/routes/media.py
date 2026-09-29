"""Two things live here: the media inbox (bulk-uploaded screenshots/clips/
soundtrack not yet assigned to a game — upload once, sort out later) and a
library-wide, read-only media gallery across every game's already-assigned
media. Per-game upload/list/patch/delete routes are in games.py
(prefix /api/game/{id}/...); this file never touches those directly except
when assigning an inbox file into a game."""

import shutil
import time
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_integrations import get_max_upload_size_mb
from src.core.auth import get_current_user
from src.core.config import settings
from src.database.models.game import Game
from src.database.models.inbox_item import InboxItem
from src.database.models.media_item import MediaItem
from src.database.models.user import User
from src.database.session import get_db
from src.features.trash.inbox_trash import (
    move_inbox_file_to_trash,
    restore_inbox_file_from_trash,
)
from src.features.trash.sweep import RETENTION_SECONDS
from src.helpers.media import MediaKind, classify_media, list_media, media_subdir, save_media_bytes
from src.helpers.save_game_asset import DATA_ROOT as GAMES_DATA_ROOT
from src.helpers.save_game_asset import create_game_folder

router = APIRouter(prefix="/api/media", tags=["media"], dependencies=[Depends(get_current_user)])

_USER_DATA_ROOT = Path("/data/user")
_INBOX_KINDS: tuple[MediaKind, ...] = ("screenshot", "clip", "soundtrack")


class AssignMediaRequest(BaseModel):
    game_id: UUID


def _inbox_dir(user_id: UUID) -> Path:
    return _USER_DATA_ROOT / str(user_id) / "inbox"


async def _sync_inbox_items(user_id: UUID, db: AsyncSession) -> None:
    """Inbox files used to be tracked only on disk, with no DB row at all —
    this backfills a row (created_at from the file's mtime) for anything
    already sitting in the active folder that doesn't have one yet, so
    existing files from before this migration still show up with a real
    date instead of needing a one-time manual migration script."""
    existing = await db.execute(
        select(InboxItem.kind, InboxItem.filename).where(
            InboxItem.user_id == user_id, InboxItem.deleted_at.is_(None)
        )
    )
    known = {(kind, filename) for kind, filename in existing.all()}
    inbox_dir = _inbox_dir(user_id)
    added = False
    for kind in _INBOX_KINDS:
        for filename in list_media(inbox_dir / media_subdir(kind)):
            if (kind, filename) in known:
                continue
            path = inbox_dir / media_subdir(kind) / filename
            try:
                mtime = int(path.stat().st_mtime)
            except OSError:
                mtime = int(time.time())
            db.add(InboxItem(user_id=user_id, kind=kind, filename=filename, created_at=mtime))
            added = True
    if added:
        await db.commit()


@router.post("/inbox")
async def upload_to_inbox(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict]]:
    """Bulk upload with no game attached yet — sorted into
    screenshots/clips/soundtrack by file type, to be grouped and assigned
    to games later."""
    results: list[dict] = []
    for file in files:
        kind = classify_media(file.content_type, file.filename or "")
        if kind is None:
            results.append(
                {
                    "filename": file.filename,
                    "status": "rejected",
                    "reason": "Unsupported file type.",
                }
            )
            continue

        # clips/soundtrack get a much larger cap than images — a real video
        # clip routinely exceeds a cover-art-sized limit (see games.py's
        # upload_game_screenshots, same fix)
        limit_mb = (
            settings.MAX_CLIP_SIZE_MB
            if kind in ("clip", "soundtrack")
            else await get_max_upload_size_mb(db)
        )
        max_bytes = limit_mb * 1024 * 1024

        data = await file.read()
        if len(data) > max_bytes:
            results.append(
                {
                    "filename": file.filename,
                    "status": "rejected",
                    "reason": f"Larger than {limit_mb} MB.",
                }
            )
            continue

        dest_dir = _inbox_dir(current_user.id) / media_subdir(kind)
        saved_path = save_media_bytes(data, dest_dir, file.filename or "file")
        db.add(InboxItem(user_id=current_user.id, kind=kind, filename=saved_path.name))
        results.append({"filename": saved_path.name, "status": "saved", "kind": kind})

    await db.commit()
    return {"results": results}


@router.get("/inbox")
async def list_inbox(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict]]:
    await _sync_inbox_items(current_user.id, db)
    result = await db.execute(
        select(InboxItem)
        .where(InboxItem.user_id == current_user.id, InboxItem.deleted_at.is_(None))
        .order_by(InboxItem.created_at.desc())
    )
    return {
        "media": [
            {
                "filename": item.filename,
                "kind": item.kind,
                "url": f"/api/media/inbox/{item.kind}/{item.filename}",
                "created_at": item.created_at,
            }
            for item in result.scalars().all()
        ]
    }


@router.get("/inbox/trash")
async def list_inbox_trash(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict]]:
    result = await db.execute(
        select(InboxItem)
        .where(InboxItem.user_id == current_user.id, InboxItem.deleted_at.is_not(None))
        .order_by(InboxItem.deleted_at.desc())
    )
    items = result.scalars().all()
    media = []
    for item in items:
        assert item.deleted_at is not None  # guaranteed by the deleted_at.is_not(None) filter above
        media.append(
            {
                "filename": item.filename,
                "kind": item.kind,
                "created_at": item.created_at,
                "deleted_at": item.deleted_at,
                "purge_at": item.deleted_at + RETENTION_SECONDS,
            }
        )
    return {"media": media}


@router.get("/inbox/{kind}/{filename}", response_class=FileResponse)
async def get_inbox_media(
    kind: MediaKind,
    filename: str,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    path = _inbox_dir(current_user.id) / media_subdir(kind) / Path(filename).name
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found.")
    return FileResponse(path)


@router.delete("/inbox/{kind}/{filename}")
async def delete_inbox_media(
    kind: MediaKind,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Soft-delete: moves the file to trash and marks its row deleted
    rather than removing it — restorable for 7 days (features/trash/
    sweep.py does the eventual real deletion), same as game archives."""
    await _sync_inbox_items(current_user.id, db)
    name = Path(filename).name
    item = await db.scalar(
        select(InboxItem).where(
            InboxItem.user_id == current_user.id,
            InboxItem.kind == kind,
            InboxItem.filename == name,
            InboxItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found.")
    inbox_dir = _inbox_dir(current_user.id)
    move_inbox_file_to_trash(inbox_dir / media_subdir(kind) / name, inbox_dir, kind)
    item.deleted_at = int(time.time())
    await db.commit()
    return {"status": "trashed", "filename": name}


@router.post("/inbox/{kind}/{filename}/restore")
async def restore_inbox_media(
    kind: MediaKind,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    name = Path(filename).name
    item = await db.scalar(
        select(InboxItem).where(
            InboxItem.user_id == current_user.id,
            InboxItem.kind == kind,
            InboxItem.filename == name,
            InboxItem.deleted_at.is_not(None),
        )
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deleted media not found."
        )
    inbox_dir = _inbox_dir(current_user.id)
    restore_inbox_file_from_trash(name, inbox_dir / media_subdir(kind), inbox_dir, kind)
    item.deleted_at = None
    await db.commit()
    return {"status": "restored", "filename": name}


@router.post("/inbox/{kind}/{filename}/assign")
async def assign_inbox_media(
    kind: MediaKind,
    filename: str,
    payload: AssignMediaRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Move a bulk-uploaded file out of the inbox and into a specific
    game's screenshots/clips/soundtrack folder, registering it as a real
    MediaItem so it's taggable/note-able/linkable from that point on."""
    source_path = _inbox_dir(current_user.id) / media_subdir(kind) / Path(filename).name
    if not source_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found.")

    game = await db.scalar(
        select(Game).where(
            Game.id == payload.game_id, Game.user_id == current_user.id, Game.deleted_at.is_(None)
        )
    )
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found.")
    if not game.folder_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Game folder_location is missing."
        )

    create_game_folder(current_user.id, game.folder_location)
    dest_dir = (
        GAMES_DATA_ROOT / str(current_user.id) / "games" / game.folder_location / media_subdir(kind)
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name
    shutil.move(str(source_path), str(dest_path))

    db.add(MediaItem(game_id=payload.game_id, kind=kind, filename=dest_path.name))
    # promoted to a real MediaItem, not deleted — remove the inbox tracking
    # row outright rather than soft-deleting it (there's nothing to restore
    # "from trash", the file just lives somewhere else now)
    inbox_item = await db.scalar(
        select(InboxItem).where(
            InboxItem.user_id == current_user.id,
            InboxItem.kind == kind,
            InboxItem.filename == source_path.name,
        )
    )
    if inbox_item is not None:
        await db.delete(inbox_item)
    await db.commit()

    return {"status": "assigned", "game_id": str(payload.game_id), "filename": dest_path.name}


@router.get("")
async def list_all_media(
    kind: MediaKind | None = Query(default=None),
    tag: str | None = Query(default=None),
    game_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Every already-assigned screenshot/clip/soundtrack across the whole
    library — the inbox above is deliberately separate (unassigned media
    has no game_id to show here)."""
    stmt = (
        select(MediaItem, Game.title)
        .join(Game, Game.id == MediaItem.game_id)
        .where(
            Game.user_id == current_user.id,
            Game.deleted_at.is_(None),
            MediaItem.deleted_at.is_(None),
        )
        .order_by(MediaItem.created_at.desc())
    )
    if kind is not None:
        stmt = stmt.where(MediaItem.kind == kind)
    if game_id is not None:
        stmt = stmt.where(MediaItem.game_id == game_id)
    if tag is not None:
        stmt = stmt.where(MediaItem.tags.any(tag))  # type: ignore[arg-type]  # ARRAY.any(scalar) is valid at runtime; mypy resolves the relationship .any() overload instead

    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": str(item.id),
            "game_id": str(item.game_id),
            "game_title": game_title,
            "filename": item.filename,
            "kind": item.kind,
            "url": f"/api/game/{item.game_id}/screenshots/{item.kind}/{item.filename}",
            "tags": item.tags,
            "note": item.note,
            "linked_achievement_id": str(item.linked_achievement_id)
            if item.linked_achievement_id
            else None,
            "created_at": item.created_at,
        }
        for item, game_title in rows
    ]
