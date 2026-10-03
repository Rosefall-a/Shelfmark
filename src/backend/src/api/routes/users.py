# pylint: disable=missing-module-docstring
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(
    prefix="/api/user",
    tags=["user"],
    dependencies=[Depends(get_current_user)],
)

_USER_DATA_ROOT = Path("/data/user")
_PROFILE_FILENAME = "profile.png"
_MAX_PROFILE_SIZE = 10 * 1024 * 1024


async def _get_user_or_404(user_id: UUID, db: AsyncSession) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    return user


async def _get_authorized_user(
    user_id: UUID,
    db: AsyncSession,
    current_user: User,
) -> User:
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this user's profile.",
        )
    return await _get_user_or_404(user_id, db)


def _profile_path(user_id: UUID) -> Path:
    return _USER_DATA_ROOT / str(user_id) / _PROFILE_FILENAME


@router.put("/{user_id}/profile-picture")
async def upload_profile_picture(
    user_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Validate and save a user's profile picture as profile.png."""
    await _get_authorized_user(user_id, db, current_user)

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile picture is empty.",
        )
    if len(image_bytes) > _MAX_PROFILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Profile picture must be 10 MB or smaller.",
        )

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            profile_image = image.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a valid image.",
        ) from exc

    profile_directory = _USER_DATA_ROOT / str(user_id)
    profile_directory.mkdir(parents=True, exist_ok=True)
    target_path = profile_directory / _PROFILE_FILENAME
    temporary_path = profile_directory / f".{_PROFILE_FILENAME}.tmp"

    try:
        profile_image.save(temporary_path, format="PNG")
        temporary_path.replace(target_path)
    except OSError as exc:
        if temporary_path.exists():
            temporary_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save profile picture.",
        ) from exc
    finally:
        profile_image.close()

    return {
        "user_id": str(user_id),
        "path": str(target_path),
        "status": "saved",
    }


@router.get("/{user_id}/profile-picture", response_class=FileResponse)
async def get_profile_picture(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Return the user's stored profile picture."""
    await _get_authorized_user(user_id, db, current_user)
    target_path = _profile_path(user_id)
    if not target_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile picture not found for user {user_id}.",
        )

    return FileResponse(
        target_path,
        media_type="image/png",
        headers={"Cache-Control": "no-store, max-age=0"},
    )
