# pylint: disable=too-many-return-statements,missing-function-docstring
"""Shared helpers for bulk screenshot/clip uploads — used both for a game's
own screenshots/clips folders and for the per-user "inbox" of unassigned
media (uploaded before being sorted into a game)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Literal

MediaKind = Literal["screenshot", "clip", "soundtrack"]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".flac", ".m4a", ".aac"}


def classify_media(content_type: str | None, filename: str) -> MediaKind | None:
    """Images become screenshots, videos become clips, audio becomes
    soundtrack — everything else is rejected. Content-type is checked
    first; falls back to the file extension since browsers/clients don't
    always set it reliably."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized.startswith("image/"):
        return "screenshot"
    if normalized.startswith("video/"):
        return "clip"
    if normalized.startswith("audio/"):
        return "soundtrack"

    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return "screenshot"
    if ext in _VIDEO_EXTENSIONS:
        return "clip"
    if ext in _AUDIO_EXTENSIONS:
        return "soundtrack"
    return None


_SUBDIRS: dict[MediaKind, str] = {
    "screenshot": "screenshots",
    "clip": "clips",
    "soundtrack": "soundtrack",
}


def media_subdir(kind: MediaKind) -> str:
    return _SUBDIRS[kind]


def safe_filename(original_name: str) -> str:
    """Strip path separators and unsafe characters; prefix a short random id
    so two uploads with the same original name never collide."""
    name = Path(original_name).name
    name = _SAFE_NAME.sub("_", name) or "file"
    return f"{uuid.uuid4().hex[:8]}_{name}"


def save_media_bytes(data: bytes, dest_dir: Path, original_name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(original_name)
    path = dest_dir / filename
    path.write_bytes(data)
    return path


def list_media(dir_path: Path) -> list[str]:
    if not dir_path.exists():
        return []
    return sorted(p.name for p in dir_path.iterdir() if p.is_file())
