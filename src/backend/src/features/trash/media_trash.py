"""On-disk trash for a game's assigned screenshots/clips/soundtrack —
same idea as inbox_trash.py, keyed by game folder instead of a user's
inbox folder."""
# pylint: disable=missing-function-docstring

from __future__ import annotations

import shutil
from pathlib import Path


def media_trash_dir(game_dir: Path, kind: str) -> Path:
    return game_dir / "_trash" / kind


def move_media_file_to_trash(active_path: Path, game_dir: Path, kind: str) -> None:
    if not active_path.is_file():
        return
    dest_dir = media_trash_dir(game_dir, kind)
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(active_path), str(dest_dir / active_path.name))


def restore_media_file_from_trash(
    filename: str, active_dir: Path, game_dir: Path, kind: str
) -> None:
    src = media_trash_dir(game_dir, kind) / filename
    if not src.is_file():
        return
    active_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(active_dir / filename))


def purge_media_file(filename: str, game_dir: Path, kind: str) -> None:
    path = media_trash_dir(game_dir, kind) / filename
    path.unlink(missing_ok=True)
