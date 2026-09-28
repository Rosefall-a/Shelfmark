# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import UUID

from PIL import Image
from sqlalchemy import select

from src.database.models.game import Game
from src.database.session import SessionLocal

DATA_ROOT = Path("/data/users")

AssetKind = Literal["key_art", "banner", "logo", "icon"]

ASSET_SIZES: dict[AssetKind, tuple[int, int]] = {
    "key_art": (600, 900),
    "banner": (3840, 1240),
    "logo": (1024, 1024),
    "icon": (512, 512),
}

ASSET_FILENAMES: dict[AssetKind, str] = {
    "key_art": "key_art.png",
    "banner": "banner.png",
    "logo": "logo.png",
    "icon": "icon.png",
}


def create_game_folder(user_id: UUID | str, folder_name: str) -> Path:
    """Create and return the persistent data directory for a game."""
    folder_path = DATA_ROOT / str(user_id) / "games" / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    (folder_path / "notes").mkdir(exist_ok=True)
    (folder_path / "screenshots").mkdir(exist_ok=True)
    (folder_path / "clips").mkdir(exist_ok=True)
    return folder_path


def _load_image_bytes(image: bytes | str | Path | Image.Image) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGBA")

    if isinstance(image, (str, Path)):
        with Image.open(image) as img:
            return img.convert("RGBA")

    with Image.open(BytesIO(image)) as img:
        return img.convert("RGBA")


# stretches to the exact target box rather than preserving aspect ratio —
# deliberate, not a "contain" resize: every asset of a given kind must be
# the same pixel dimensions for consistent layout, and provider-sourced
# art (IGDB/Steam/SteamGridDB) already comes in each kind's expected ratio,
# so the stretch is negligible in practice
def _resize_to_exact(image: Image.Image, width: int, height: int) -> Image.Image:
    original = image.convert("RGBA")
    resized = original.resize((width, height), Image.Resampling.LANCZOS)
    return resized


async def get_game_folder(game_id: UUID | str) -> tuple[UUID, str]:
    async with SessionLocal() as session:
        game = await session.scalar(
            select(Game).where(Game.id == str(game_id), Game.deleted_at.is_(None))
        )
        if game is None:
            raise ValueError(f"Game not found for id: {game_id}")
        if not game.folder_location:
            raise ValueError(f"Game {game_id} is missing folder_location")
        return game.user_id, game.folder_location


async def save_game_asset(
    image: bytes | str | Path | Image.Image,
    game_id: UUID | str,
    asset_kind: AssetKind,
) -> Path:
    """Resize one image to the exact target size for a game asset and save it to disk.

    Example:
        await save_game_asset(image_bytes, game_id, "key_art")
    """
    if asset_kind not in ASSET_SIZES:
        raise ValueError(f"Unsupported asset kind: {asset_kind}")

    user_id, folder_name = await get_game_folder(game_id)
    output_dir = create_game_folder(user_id, folder_name)

    width, height = ASSET_SIZES[asset_kind]
    image_obj = _load_image_bytes(image)
    resized = _resize_to_exact(image_obj, width, height)

    output_path = output_dir / ASSET_FILENAMES[asset_kind]
    resized.save(output_path, format="PNG")
    return output_path
