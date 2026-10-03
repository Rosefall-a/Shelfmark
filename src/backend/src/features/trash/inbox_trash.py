"""On-disk trash for inbox media — same idea as archive_trash.py but simpler,
since an inbox item is always a single flat file, never a nested archive.
Moving a file aside instead of deleting it outright is what makes the
7-day recovery window in features/trash/sweep.py possible."""
# pylint: disable=missing-function-docstring

from __future__ import annotations

import shutil
from pathlib import Path


def inbox_trash_dir(inbox_dir: Path, kind: str) -> Path:
    return inbox_dir / "_trash" / kind


def move_inbox_file_to_trash(active_path: Path, inbox_dir: Path, kind: str) -> None:
    if not active_path.is_file():
        return
    dest_dir = inbox_trash_dir(inbox_dir, kind)
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(active_path), str(dest_dir / active_path.name))


def restore_inbox_file_from_trash(
    filename: str, active_dir: Path, inbox_dir: Path, kind: str
) -> None:
    src = inbox_trash_dir(inbox_dir, kind) / filename
    if not src.is_file():
        return
    active_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(active_dir / filename))


def purge_inbox_file(filename: str, inbox_dir: Path, kind: str) -> None:
    path = inbox_trash_dir(inbox_dir, kind) / filename
    path.unlink(missing_ok=True)
