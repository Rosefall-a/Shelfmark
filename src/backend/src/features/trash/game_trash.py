"""On-disk trash for whole games — the highest-blast-radius delete in the
app (cascades to screenshots, clips, notes, achievements, saves,
everything) previously had the weakest protection: instant and
permanent. This moves the entire game folder aside in one shot instead
of removing it, so features/trash/sweep.py has something to restore
from for 7 days."""
# pylint: disable=missing-function-docstring

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID


def game_trash_dir(data_root: Path, game_id: UUID) -> Path:
    return data_root / "_trash" / str(game_id)


def move_game_to_trash(active_dir: Path, data_root: Path, game_id: UUID) -> None:
    if not active_dir.is_dir():
        return
    dest = game_trash_dir(data_root, game_id)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(active_dir), str(dest))


def restore_game_from_trash(active_dir: Path, data_root: Path, game_id: UUID) -> None:
    src = game_trash_dir(data_root, game_id)
    if not src.is_dir():
        return
    if active_dir.exists():
        shutil.rmtree(active_dir)
    active_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(active_dir))


def purge_game_trash(data_root: Path, game_id: UUID) -> None:
    dest = game_trash_dir(data_root, game_id)
    if dest.is_dir():
        shutil.rmtree(dest, ignore_errors=True)
