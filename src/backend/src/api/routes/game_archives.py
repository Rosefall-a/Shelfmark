# pylint: disable=duplicate-code,too-many-positional-arguments,too-many-boolean-expressions
"""Named, versioned save archives for a game — "Main World", "Pre-Nether-
Update Backup", etc. — plus the BlueMap world-map render/view routes for
archives of kind "world_save". Replaces the old convention (still used by
docs/modpacks, see games.py's /files/{kind} routes) of a save being just
one anonymous uploaded file with no history."""

from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.routes.games import _DATA_ROOT, _get_game_or_404
from src.core.auth import get_current_user
from src.core.config import settings
from src.database.models.game_archive import GameArchive, GameArchiveVersion
from src.database.models.user import User
from src.database.session import get_db
from src.features.trash import archive_trash
from src.features.trash.sweep import RETENTION_SECONDS
from src.features.world_map import bluemap
from src.helpers.media import safe_filename

_DB_DEPENDENCY = Depends(get_db)
_CURRENT_USER_DEPENDENCY = Depends(get_current_user)
_FILE_UPLOAD = File(...)

router = APIRouter(
    prefix="/api/game", tags=["game-archives"], dependencies=[_CURRENT_USER_DEPENDENCY]
)

ArchiveKind = Literal["save", "world_save"]

_UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _save_upload_stream(
    file: UploadFile, dest_dir: Path, original_name: str, limit_mb: int
) -> tuple[Path, int]:
    """Stream an uploaded archive to disk without buffering it in memory."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / safe_filename(original_name)
    limit_bytes = limit_mb * 1024 * 1024
    size = 0
    try:
        with path.open("wb") as output:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Larger than {limit_mb} MB.",
                    )
                output.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path, size


_ARCHIVE_SUBDIRS: dict[ArchiveKind, str] = {"save": "saves", "world_save": "world_saves"}


def _get_archive_kind_from_string(kind_str: str) -> ArchiveKind:
    if kind_str in ("save", "world_save"):
        return kind_str  # type: ignore[return-value]
    raise ValueError(f"Unknown archive kind: {kind_str}")


def _archive_dir(
    game_folder: str, kind: str, archive_id: UUID, user_id: UUID
) -> Path:
    """Return the on-disk directory for an archive."""
    kind = _get_archive_kind_from_string(kind)
    return (
        _DATA_ROOT / str(user_id) / "games" / game_folder / _ARCHIVE_SUBDIRS[kind] / str(archive_id)
    )


async def _get_archive_or_404(
    game_id: UUID,
    archive_id: UUID,
    db: AsyncSession,
    user_id: UUID,
    kind: ArchiveKind | None = None,
    include_deleted: bool = False,
) -> GameArchive:
    await _get_game_or_404(game_id, db, user_id)
    # eager-loads versions — db.get() doesn't, and every caller of this
    # touches archive.versions afterward; a lazy-load on an already-awaited
    # async session blows up with MissingGreenlet
    archive = await db.scalar(
        select(GameArchive)
        .options(selectinload(GameArchive.versions))
        .where(GameArchive.id == archive_id)
    )
    if (
        archive is None
        or archive.game_id != game_id
        or (kind and archive.kind != kind)
        or (not include_deleted and archive.deleted_at is not None)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found.")
    return archive


def _version_to_dict(game_id: UUID, archive: GameArchive, v: GameArchiveVersion) -> dict:
    return {
        "id": str(v.id),
        "filename": v.filename,
        "size": v.size,
        "uploaded_at": v.uploaded_at,
        "url": f"/api/game/{game_id}/archives/{archive.id}/versions/{v.id}/download",
    }


def _archive_to_dict(
    game_id: UUID, archive: GameArchive, include_deleted_versions: bool = False
) -> dict:
    versions = (
        archive.versions
        if include_deleted_versions
        else [v for v in archive.versions if v.deleted_at is None]
    )
    return {
        "id": str(archive.id),
        "name": archive.name,
        "kind": archive.kind,
        "created_at": archive.created_at,
        "updated_at": archive.updated_at,
        "versions": [_version_to_dict(game_id, archive, v) for v in versions],
    }


def _trash_entry(game_id: UUID, archive: GameArchive) -> dict:
    entry = _archive_to_dict(game_id, archive, include_deleted_versions=True)
    entry["deleted_at"] = archive.deleted_at
    entry["purge_at"] = (archive.deleted_at or 0) + RETENTION_SECONDS
    return entry


class RenameArchiveRequest(BaseModel):
    """Payload used to rename an archive."""

    name: str


@router.get("/{game_id}/archives/{kind}")
async def list_archives(
    game_id: UUID,
    kind: ArchiveKind,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> list[dict]:
    """List active archives of the requested kind for a game."""
    await _get_game_or_404(game_id, db, current_user.id
    result = await db.execute(
        select(GameArchive)
        .options(selectinload(GameArchive.versions))
        .where(
            GameArchive.game_id == game_id,
            GameArchive.kind == kind,
            GameArchive.deleted_at.is_(None),
        )
        .order_by(GameArchive.updated_at.desc())
    )
    archives = result.scalars().all()
    return [_archive_to_dict(game_id, a) for a in archives]


@router.get("/{game_id}/archives/{kind}/trash")
async def list_archive_trash(
    game_id: UUID,
    kind: ArchiveKind,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> list[dict]:
    """Soft-deleted archives of this kind, newest-deleted first — each still
    restorable until its purge_at passes (see features/trash/sweep.py)."""
    await _get_game_or_404(game_id, db, current_user.id)
    result = await db.execute(
        select(GameArchive)
        .options(selectinload(GameArchive.versions))
        .where(
            GameArchive.game_id == game_id,
            GameArchive.kind == kind,
            GameArchive.deleted_at.is_not(None),
        )
        .order_by(GameArchive.deleted_at.desc())
    )
    return [_trash_entry(game_id, a) for a in result.scalars().all()]


@router.post("/{game_id}/archives/{kind}")
async def create_archive(
    game_id: UUID,
    kind: ArchiveKind,
    name: str = Form(...),
    file: UploadFile = _FILE_UPLOAD,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Creates a new named archive and uploads its first version in one
    call — e.g. dropping a world save creates the "Main World" slot and
    its first save together, rather than a two-step flow."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    if not game.folder_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Game folder_location is missing."
        )
    if not name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required.")

    limit_mb = (
        settings.MAX_WORLD_SAVE_SIZE_MB
        if kind == "world_save"
        else settings.MAX_SAVE_ARCHIVE_SIZE_MB
    )

    archive = GameArchive(id=uuid4(), game_id=game_id, kind=kind, name=name.strip())
    db.add(archive)
    await db.flush()

    dest_dir = _archive_dir(game.folder_location, kind, archive.id, user_id=current_user.id)  # type: ignore[arg-type]
    try:
        saved_path, size = await _save_upload_stream(
            file, dest_dir, file.filename or "file", limit_mb
        )
        version = GameArchiveVersion(
            id=uuid4(), archive_id=archive.id, filename=saved_path.name, size=size
        )
        db.add(version)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(archive, attribute_names=["versions"])
    return _archive_to_dict(game_id, archive)


@router.post("/{game_id}/archives/{archive_id}/versions")
async def add_archive_version(
    game_id: UUID,
    archive_id: UUID,
    file: UploadFile = _FILE_UPLOAD,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Uploads a new version to an existing archive — the previous
    version(s) stay as history rather than being replaced."""
    archive = await _get_archive_or_404(game_id, archive_id, db, current_user.id)
    game = await _get_game_or_404(game_id, db, current_user.id)
    if not game.folder_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Game folder_location is missing."
        )

    limit_mb = (
        settings.MAX_WORLD_SAVE_SIZE_MB
        if archive.kind == "world_save"
        else settings.MAX_SAVE_ARCHIVE_SIZE_MB
    )

    dest_dir = _archive_dir(game.folder_location, archive.kind, archive.id, user_id=current_user.id)  # type: ignore[arg-type]
    try:
        saved_path, size = await _save_upload_stream(
            file, dest_dir, file.filename or "file", limit_mb
        )
        version = GameArchiveVersion(
            id=uuid4(), archive_id=archive.id, filename=saved_path.name, size=size
        )
        db.add(version)
        archive.updated_at = int(time.time())
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(archive, attribute_names=["versions"])
    return _archive_to_dict(game_id, archive)


@router.patch("/{game_id}/archives/{archive_id}")
async def rename_archive(
    game_id: UUID,
    archive_id: UUID,
    payload: RenameArchiveRequest,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Rename an existing archive."""
    archive = await _get_archive_or_404(game_id, archive_id, db, current_user.id
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required.")
    archive.name = payload.name.strip()
    await db.commit()
    await db.refresh(archive, attribute_names=["versions"])
    return _archive_to_dict(game_id, archive)


@router.delete("/{game_id}/archives/{archive_id}")
async def delete_archive(
    game_id: UUID,
    archive_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    """Soft-delete: moves the archive's files to trash and marks it deleted
    rather than removing anything — restorable for 7 days (see
    features/trash/sweep.py, which does the eventual real deletion)."""
    archive = await _get_archive_or_404(game_id, archive_id, db, current_user.id)
    game = await _get_game_or_404(game_id, db, current_user.id)
    if game.folder_location:
        game_dir = _DATA_ROOT / str(current_user.id) / "games" / game.folder_location
        dir_path = _archive_dir(game.folder_location, archive.kind, archive.id, current_user.id)  # type: ignore[arg-type]
        work_dir = game_dir / "world_map" / str(archive.id)
        archive_trash.move_archive_to_trash(dir_path, work_dir, game_dir, archive.kind, archive.id)
    archive.deleted_at = int(time.time())
    await db.commit()
    return {"status": "trashed"}


@router.post("/{game_id}/archives/{archive_id}/restore")
async def restore_archive(
    game_id: UUID,
    archive_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Restore a deleted archive and all of its versions."""
    archive = await _get_archive_or_404(
        game_id, archive_id, db, current_user.id, include_deleted=True
    )
    if archive.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Archive isn't deleted."
        )
    game = await _get_game_or_404(game_id, db, current_user.id)
    if game.folder_location:
        game_dir = _DATA_ROOT / str(current_user.id) / "games" / game.folder_location
        dir_path = _archive_dir(game.folder_location, archive.kind, archive.id, current_user.id)  # type: ignore[arg-type]
        work_dir = game_dir / "world_map" / str(archive.id)
        archive_trash.restore_archive_from_trash(
            dir_path, work_dir, game_dir, archive.kind, archive.id
        )
    archive.deleted_at = None
    for version in archive.versions:
        version.deleted_at = None
    await db.commit()
    await db.refresh(archive, attribute_names=["versions"])
    return _archive_to_dict(game_id, archive)


@router.delete("/{game_id}/archives/{archive_id}/versions/{version_id}")
async def delete_archive_version(
    game_id: UUID,
    archive_id: UUID,
    version_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Soft-delete one version of an archive."""
    archive = await _get_archive_or_404(game_id, archive_id, db, current_user.id)
    game = await _get_game_or_404(game_id, db, current_user.id)
    version = next(
        (v for v in archive.versions if v.id == version_id and v.deleted_at is None), None
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    active_versions = [v for v in archive.versions if v.deleted_at is None]
    if len(active_versions) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delete the whole save to remove its last remaining version.",
        )
    if game.folder_location:
        game_dir = _DATA_ROOT / str(current_user.id) / "games" / game.folder_location
        path = (
            _archive_dir(game.folder_location, archive.kind, archive.id, current_user.id)
            / version.filename
        )  # type: ignore[arg-type]
        archive_trash.move_file_to_trash(path, game_dir, archive.kind, archive.id)
    version.deleted_at = int(time.time())
    await db.commit()
    await db.refresh(archive, attribute_names=["versions"])
    return _archive_to_dict(game_id, archive)


@router.post("/{game_id}/archives/{archive_id}/versions/{version_id}/restore")
async def restore_archive_version(
    game_id: UUID,
    archive_id: UUID,
    version_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Restore one deleted archive version."""
    archive = await _get_archive_or_404(
        game_id, archive_id, db, current_user.id, include_deleted=True
    )
    game = await _get_game_or_404(game_id, db, current_user.id)
    version = next(
        (v for v in archive.versions if v.id == version_id and v.deleted_at is not None), None
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deleted version not found."
        )
    if game.folder_location:
        game_dir = _DATA_ROOT / str(current_user.id) / "games" / game.folder_location
        dir_path = _archive_dir(game.folder_location, archive.kind, archive.id, current_user.id)  # type: ignore[arg-type]
        archive_trash.restore_file_from_trash(
            version.filename, dir_path, game_dir, archive.kind, archive.id
        )
    version.deleted_at = None
    await db.commit()
    await db.refresh(archive, attribute_names=["versions"])
    return _archive_to_dict(game_id, archive)


@router.get(
    "/{game_id}/archives/{archive_id}/versions/{version_id}/download", response_class=FileResponse
)
async def download_archive_version(
    game_id: UUID,
    archive_id: UUID,
    version_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> FileResponse:
    """Download an archived save version."""
    archive = await _get_archive_or_404(game_id, archive_id, db, current_user.id
    game = await _get_game_or_404(game_id, db, current_user.id)
    version = next(
        (v for v in archive.versions if v.id == version_id and v.deleted_at is None), None
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    path = (
        _archive_dir(game.folder_location or "", archive.kind, archive.id, current_user.id)
        / version.filename
    )  # type: ignore[arg-type]
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    original_name = version.filename.split("_", 1)[-1]
    return FileResponse(path, filename=original_name, media_type="application/octet-stream")


# --- World Map (BlueMap render of a world_save archive's latest version) --


@router.get("/{game_id}/world-map/worlds")
async def list_world_maps(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> list[dict]:
    """Every world_save archive for this game, each with its own render
    status and thumbnail — a game (e.g. a modpack) can have several
    distinct worlds without needing a separate game card per world."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    result = await db.execute(
        select(GameArchive)
        .options(selectinload(GameArchive.versions))
        .where(
            GameArchive.game_id == game_id,
            GameArchive.kind == "world_save",
            GameArchive.deleted_at.is_(None),
        )
        .order_by(GameArchive.updated_at.desc())
    )
    archives = result.scalars().all()
    worlds = []
    for archive in archives:
        entry = _archive_to_dict(game_id, archive)
        entry.update(bluemap.get_status(game_id, archive.id))
        entry["has_thumbnail"] = False  # filled in below once we have folder_location
        worlds.append(entry)

    if game.folder_location:
        game_dir = _DATA_ROOT / str(current_user.id) / "games" / game.folder_location
        for entry, archive in zip(worlds, archives, strict=True):
            entry["has_thumbnail"] = bluemap.thumbnail_path(game_dir, archive.id).is_file()
    return worlds


@router.post("/{game_id}/world-map/{archive_id}/render")
async def render_world_map_route(
    game_id: UUID,
    archive_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    """Kicks off a BlueMap render of a world_save archive's latest version
    as a background task — this can take a long time for a real world, so
    the request returns immediately; poll .../world-map/{archive_id}/status
    for progress."""
    archive = await _get_archive_or_404(game_id, archive_id, db, current_user.id, kind="world_save")
    game = await _get_game_or_404(game_id, db, current_user.id)
    if not game.folder_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Game folder_location is missing."
        )
    active_versions = [v for v in archive.versions if v.deleted_at is None]
    if not active_versions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a world save first."
        )

    if bluemap.get_status(game_id, archive_id)["status"] == "rendering":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A render is already in progress."
        )

    latest = active_versions[0]  # ordered newest-first (see GameArchive.versions)
    world_zip = (
        _archive_dir(game.folder_location, "world_save", archive_id, current_user.id)
        / latest.filename
    )
    game_dir = _DATA_ROOT / str(current_user.id) / "games" / game.folder_location
    background_tasks.add_task(bluemap.render_world_map, game_id, archive_id, game_dir, world_zip)
    return {"status": "rendering"}


@router.get("/{game_id}/world-map/{archive_id}/status")
async def get_world_map_status(
    game_id: UUID,
    archive_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Return the current render status for a world map."""
    await _get_archive_or_404(game_id, archive_id, db, current_user.id, kind="world_save")
    return bluemap.get_status(game_id, archive_id)


@router.get("/{game_id}/world-map/{archive_id}/thumbnail", response_class=FileResponse)
async def get_world_map_thumbnail(
    game_id: UUID,
    archive_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> FileResponse:
    """Return the rendered world-map thumbnail."""
    game = await _get_game_or_404(game_id, db, current_user.id
    path = bluemap.thumbnail_path(
        _DATA_ROOT / str(current_user.id) / "games" / (game.folder_location or ""), archive_id
    )
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No thumbnail yet.")
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.get("/{game_id}/world-map/{archive_id}/view/{file_path:path}")
async def get_world_map_file(
    game_id: UUID,
    archive_id: UUID,
    file_path: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> FileResponse:
    """Serves one world's rendered BlueMap webapp (index.html + its assets)
    so the frontend can embed it in an iframe. `file_path` defaults to
    index.html when empty, matching how a static webapp normally resolves
    its root."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    root = bluemap.web_root(
        _DATA_ROOT / str(current_user.id) / "games" / (game.folder_location or ""), archive_id
    )
    target = root / (file_path or "index.html")
    resolved = target.resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path.")
    if resolved.is_file():
        return FileResponse(resolved)

    # BlueMap pre-gzips its larger data/tile files on disk (textures.json.gz,
    # every *.prbm tile) and expects the web server to decompress-on-serve for
    # the plain filename its webapp actually requests — without this, every
    # texture/tile fetch 404s and the rendered map shows as untextured.
    gz_path = resolved.with_name(resolved.name + ".gz")
    if gz_path.is_file():
        media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        return FileResponse(gz_path, media_type=media_type, headers={"Content-Encoding": "gzip"})

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not rendered yet.")
