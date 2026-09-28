"""On-disk trash for game_archives — moves files aside instead of deleting
them outright, so a soft-deleted archive/version can still be recovered
within the 7-day window (see sweep.py for the part that actually purges
them). Everything for one archive lives under one trash folder, keyed by
archive id, so restoring or purging never has to guess which files belong
to which archive:

    {game_dir}/_trash/{kind}/{archive_id}/files/{filename...}
    {game_dir}/_trash/{kind}/{archive_id}/world_map/   (world_save only)

Moving files one at a time (not the whole directory in one shutil.move) is
deliberate: a version can be trashed on its own while the rest of the
archive stays active, and a later archive-level trash of the same id must
not collide with files already sitting there from that earlier move.
"""
# pylint: disable=missing-function-docstring

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID


def trash_root(game_dir: Path, kind: str, archive_id: UUID) -> Path:
    return game_dir / "_trash" / kind / str(archive_id)


def trash_files_dir(game_dir: Path, kind: str, archive_id: UUID) -> Path:
    return trash_root(game_dir, kind, archive_id) / "files"


def trash_world_map_dir(game_dir: Path, kind: str, archive_id: UUID) -> Path:
    return trash_root(game_dir, kind, archive_id) / "world_map"


def move_file_to_trash(active_path: Path, game_dir: Path, kind: str, archive_id: UUID) -> None:
    if not active_path.is_file():
        return
    dest_dir = trash_files_dir(game_dir, kind, archive_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(active_path), str(dest_dir / active_path.name))


def restore_file_from_trash(
    filename: str, active_dir: Path, game_dir: Path, kind: str, archive_id: UUID
) -> None:
    src = trash_files_dir(game_dir, kind, archive_id) / filename
    if not src.is_file():
        return
    active_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(active_dir / filename))


def move_archive_to_trash(
    active_dir: Path, world_map_dir: Path | None, game_dir: Path, kind: str, archive_id: UUID
) -> None:
    """Moves every remaining file in the archive's active directory (and its
    world_map render, if any) into trash. Any file already moved there by an
    earlier per-version trash just stays put."""
    if active_dir.is_dir():
        dest_dir = trash_files_dir(game_dir, kind, archive_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        for item in active_dir.iterdir():
            if item.is_file():
                shutil.move(str(item), str(dest_dir / item.name))
        if not any(active_dir.iterdir()):
            active_dir.rmdir()

    if world_map_dir is not None and world_map_dir.is_dir():
        dest = trash_world_map_dir(game_dir, kind, archive_id)
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(world_map_dir), str(dest))


def restore_archive_from_trash(
    active_dir: Path, world_map_dir: Path | None, game_dir: Path, kind: str, archive_id: UUID
) -> None:
    files_dir = trash_files_dir(game_dir, kind, archive_id)
    if files_dir.is_dir():
        active_dir.mkdir(parents=True, exist_ok=True)
        for item in files_dir.iterdir():
            shutil.move(str(item), str(active_dir / item.name))

    if world_map_dir is not None:
        trashed_world_map = trash_world_map_dir(game_dir, kind, archive_id)
        if trashed_world_map.is_dir():
            if world_map_dir.exists():
                shutil.rmtree(world_map_dir)
            world_map_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trashed_world_map), str(world_map_dir))

    root = trash_root(game_dir, kind, archive_id)
    if root.is_dir() and not any(root.rglob("*")):
        shutil.rmtree(root, ignore_errors=True)


def purge_archive_trash(game_dir: Path, kind: str, archive_id: UUID) -> None:
    root = trash_root(game_dir, kind, archive_id)
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
