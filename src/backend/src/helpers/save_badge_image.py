# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image

# a badge (ribbon/corner seal/custom icon) isn't a fixed shape the way a
# game's key_art/banner/logo/icon are — no forced crop, just a size cap so
# an oversized upload can't bloat every card's render
BADGE_DATA_ROOT = Path("/data/badges")
_MAX_DIMENSION = 512


def badge_image_path(user_id: UUID | str) -> Path:
    return BADGE_DATA_ROOT / f"{user_id}.png"


def save_badge_image(image_bytes: bytes, user_id: UUID | str) -> Path:
    BADGE_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(image_bytes)) as img:
        img = img.convert("RGBA")
        if img.width > _MAX_DIMENSION or img.height > _MAX_DIMENSION:
            img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.Resampling.LANCZOS)
        path = badge_image_path(user_id)
        img.save(path, format="PNG")
    return path


def delete_badge_image(user_id: UUID | str) -> None:
    path = badge_image_path(user_id)
    if path.exists():
        path.unlink()
