"""API routes for managing games, notes, and game artwork."""

import asyncio
import re
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import requests
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.settings import (
    get_or_create_app_integration_settings,
    get_or_create_scan_settings,
)
from src.api.schemas.game import (
    GameBulkUpdate,
    GameCreate,
    GameFieldChangeRead,
    GameRead,
    GameUpdate,
)
from src.core.auth import get_current_user
from src.core.config import settings
from src.core.integrations import resolve_integrations
from src.database.models.achievement import Achievement
from src.database.models.game import Game, GameLink, GameStatus
from src.database.models.game_checklist_item import GameChecklistItem
from src.database.models.game_field_change import GameFieldChange
from src.database.models.game_file_item import GameFileItem
from src.database.models.game_profile import GameProfile
from src.database.models.game_profile_stat_snapshot import GameProfileStatSnapshot
from src.database.models.media_item import MediaItem
from src.database.models.user import User
from src.database.models.user_scan_settings import UserScanSettings
from src.database.session import get_db
from src.features.metadata.locked_fields import apply_updates_with_locking
from src.features.metadata.games import wiseoldman
from src.features.metadata.games.search import search_game_metadata
from src.features.trash.game_trash import move_game_to_trash, restore_game_from_trash
from src.features.trash.media_trash import move_media_file_to_trash, restore_media_file_from_trash
from src.features.trash.sweep import RETENTION_SECONDS
from src.helpers.media import MediaKind, classify_media, list_media, media_subdir, save_media_bytes
from src.helpers.save_game_asset import (
    ASSET_FILENAMES,
    AssetKind,
    create_game_folder,
    save_game_asset,
)

router = APIRouter(
    prefix="/api/game",
    tags=["game"],
    dependencies=[Depends(get_current_user)],
)

_DATA_ROOT = Path("/data/users")
_NOTE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_LEADING_ARTICLE = re.compile(r"^(a|an|the)\s+", flags=re.IGNORECASE)

_DB_DEPENDENCY = Depends(get_db)
_CURRENT_USER_DEPENDENCY = Depends(get_current_user)
_FILE_UPLOAD = File(...)
_BODY_DOTDOTDOT = Body(...)
_NONE_FORM = Form(None)
_NONE_QUERY_STATUS = Query(default=None, alias="status")


class NoteWrite(BaseModel):
    """Request body used to create or replace a game note."""

    content: str


class MetadataSearchResponse(BaseModel):
    query: str
    providers: list[str]
    steamgriddb_configured: bool = False
    provider_errors: list[str] = []
    results: list[dict]


class AssetUrlRequest(BaseModel):
    url: str


class MetadataRefreshRequest(BaseModel):
    dry_run: bool = False
    update_text: bool = True
    fill_missing_art: bool = True
    overwrite_existing_art: bool = False
    expected_updated_at: int | None = None


ALLOWED_ASSET_KINDS = {"key_art", "banner", "logo", "icon"}


def _scan_settings_to_preferences(scan_settings: UserScanSettings) -> dict:
    return {
        "provider_order": scan_settings.provider_order,
        "image_provider_order": scan_settings.image_provider_order,
        "save_developer": scan_settings.save_developer,
        "save_publisher": scan_settings.save_publisher,
        "save_series": scan_settings.save_series,
        "save_tags": scan_settings.save_tags,
        "save_features": scan_settings.save_features,
        "save_description": scan_settings.save_description,
        "save_age_rating": scan_settings.save_age_rating,
        "save_release_date": scan_settings.save_release_date,
        "save_time_to_beat": scan_settings.save_time_to_beat,
        "save_key_art": scan_settings.save_key_art,
        "save_banner": scan_settings.save_banner,
        "save_logo": scan_settings.save_logo,
        "save_icon": scan_settings.save_icon,
    }


@router.get("/metadata/search", response_model=MetadataSearchResponse)
async def search_metadata(
    query: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(default=8, ge=1, le=20),
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Search external providers for data that can prefill a new game.

    SteamGridDB art is only included if the requesting user has their own
    key saved (Settings) — there's no app-wide fallback key. Provider order
    and which fields get saved come from the user's scan settings.
    """
    scan_settings = await get_or_create_scan_settings(current_user.id, db)
    preferences = _scan_settings_to_preferences(scan_settings)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    try:
        result = await asyncio.to_thread(
            search_game_metadata,
            query.strip(),
            limit,
            current_user.steamgriddb_api_key,
            preferences,
            current_user,
            app_integrations.igdb_client_id,
            app_integrations.igdb_client_secret,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Metadata providers could not be reached: {exc}",
        ) from exc

    if result.get("providers"):
        now = int(time.time())
        last_used = dict(scan_settings.provider_last_used)
        for provider_name in result["providers"]:
            last_used[provider_name] = now
        scan_settings.provider_last_used = last_used
        await db.commit()
    return result


@router.get("/{game_id}/assets/{asset_kind}", response_class=FileResponse)
async def get_game_asset(
    game_id: UUID,
    asset_kind: AssetKind,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> FileResponse:
    """Return a stored PNG asset for a game."""
    if asset_kind not in ALLOWED_ASSET_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported asset kind '{asset_kind}'. Supported values: {sorted(ALLOWED_ASSET_KINDS)}",
        )

    game = await _get_game_or_404(game_id, db, current_user.id)
    asset_path = (
        _DATA_ROOT
        / str(game.user_id)
        / "games"
        / game.folder_location
        / ASSET_FILENAMES[asset_kind]
    )
    if not asset_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset '{asset_kind}' has not been uploaded for game {game_id}.",
        )

    return FileResponse(
        asset_path,
        media_type="image/png",
        # was "no-store, max-age=0" — meant the browser re-downloaded every
        # cover/banner on every scroll, reload, and revisit, even when
        # nothing changed. Starlette's FileResponse already sets
        # Last-Modified/ETag from the file's own stat, so a "revalidate"
        # cache still gets a cheap 304 instead of a full re-fetch the
        # instant an asset actually changes (a refresh/re-sync overwrites
        # the file in place, changing its mtime).
        headers={"Cache-Control": "private, max-age=3600, must-revalidate"},
    )


def _derive_sort_title(title: str) -> str:
    """'The Witcher 3' -> 'witcher 3' so articles don't affect sort order."""
    return _LEADING_ARTICLE.sub("", title).strip().lower()


# the same set a metadata search/refresh is allowed to overwrite (see the
# scan-settings save_* toggles in ScanSettingsSection.vue). A field outside
# this set (folder_location, favorite, playtime, ...) isn't "metadata" in
# that sense, so history only tracks what a provider could plausibly have
# changed underneath the user
FIELD_CHANGE_TRACKED_FIELDS = {
    "developer",
    "publisher",
    "series",
    "tags",
    "features",
    "description",
    "age_rating",
    "release_date",
    "time_to_beat_hours",
}


def _field_change_value_to_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else None
    return str(value)


def _record_field_changes(game: Game, updates: dict, db: AsyncSession) -> None:
    now = int(time.time())
    for field in FIELD_CHANGE_TRACKED_FIELDS & updates.keys():
        old_text = _field_change_value_to_text(getattr(game, field))
        new_text = _field_change_value_to_text(updates[field])
        if old_text == new_text:
            continue
        db.add(
            GameFieldChange(
                game_id=game.id,
                field_name=field,
                old_value=old_text,
                new_value=new_text,
                changed_at=now,
            )
        )


def _duplicate_folder_error(folder_name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "duplicate_folder_location",
            "field": "folder_location",
            "value": folder_name,
            "message": f"A game with folder_location '{folder_name}' already exists.",
        },
    )


async def _ensure_folder_location_available(
    folder_name: str,
    user_id: UUID,
    db: AsyncSession,
    exclude_game_id: UUID | None = None,
) -> None:
    stmt = select(Game.id).where(
        Game.user_id == user_id,
        Game.folder_location == folder_name,
        Game.deleted_at.is_(None),
    )
    if exclude_game_id is not None:
        stmt = stmt.where(Game.id != exclude_game_id)

    existing = await db.scalar(stmt)
    if existing is not None:
        raise _duplicate_folder_error(folder_name)


def _normalize_note_name(note_name: str) -> str:
    normalized = note_name.strip()
    if normalized.lower().endswith(".md"):
        normalized = normalized[:-3]

    if not normalized or not _NOTE_NAME_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Note name must contain only letters, numbers, underscores, or hyphens and no file extension.",
        )

    return normalized


def _game_note_path(game: Game, note_name: str) -> Path:
    if not game.folder_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Game folder_location is missing.",
        )

    note_file_name = f"{_normalize_note_name(note_name)}.md"
    note_dir = _DATA_ROOT / str(game.user_id) / "games" / game.folder_location / "notes"
    note_dir.mkdir(parents=True, exist_ok=True)
    return note_dir / note_file_name


async def _get_game_or_404(
    game_id: UUID, db: AsyncSession, user_id: UUID, include_deleted: bool = False
) -> Game:
    stmt = select(Game).where(Game.id == game_id, Game.user_id == user_id)
    if not include_deleted:
        stmt = stmt.where(Game.deleted_at.is_(None))
    game = await db.scalar(stmt)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game {game_id} not found",
        )
    return game


@router.get("/achievements-summary")
async def get_achievements_summary(
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, dict[str, int]]:
    """Per-game {total, unlocked} counts for every one of the caller's games
    that has any achievements at all, in one grouped query — powers the
    completion badge on library/card views without an N+1 request per game."""
    rows = await db.execute(
        select(
            Achievement.game_id,
            func.count(Achievement.id),
            func.sum(func.cast(Achievement.unlocked, Integer)),
        )
        .join(Game, Game.id == Achievement.game_id)
        .where(Game.user_id == current_user.id, Game.deleted_at.is_(None))
        .group_by(Achievement.game_id)
    )
    return {
        str(game_id): {"total": total, "unlocked": unlocked or 0}
        for game_id, total, unlocked in rows
    }


@router.get("/{game_id}/achievements")
async def list_game_achievements(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> list[dict]:
    """Achievements/trophies pulled in by a library sync (Settings ->
    Metadata/API -> Steam/PlayStation/RetroAchievements). Empty until that
    game has been synced at least once — this never calls out to a
    provider itself, it only reads what's already stored."""
    await _get_game_or_404(game_id, db, current_user.id)
    result = await db.execute(
        select(Achievement)
        .where(Achievement.game_id == game_id)
        .order_by(Achievement.unlocked.desc(), Achievement.name)
    )
    return [
        {
            "id": str(a.id),
            "provider": a.provider,
            "name": a.name,
            "description": a.description,
            "icon_url": a.icon_url,
            "unlocked": a.unlocked,
            "unlocked_at": a.unlocked_at,
        }
        for a in result.scalars().all()
    ]


@router.post(
    "/{game_id}/assets/{asset_kind}",
    responses={
        status.HTTP_200_OK: {"description": "Image uploaded and resized"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid asset kind or upload"},
        status.HTTP_404_NOT_FOUND: {"description": "Game not found"},
    },
)
async def upload_game_asset(
    game_id: UUID,
    asset_kind: AssetKind,
    file: UploadFile = _FILE_UPLOAD,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    """Upload and persist artwork for a game."""
    if asset_kind not in ALLOWED_ASSET_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported asset kind '{asset_kind}'. Supported values: {sorted(ALLOWED_ASSET_KINDS)}",
        )

    await _get_game_or_404(game_id, db, current_user.id)

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is required.",
        )

    # Do not trust the browser-supplied MIME type here. Some valid image
    # files are reported as application/octet-stream (or with no type at all).
    # save_game_asset decodes the actual image bytes with Pillow, which gives
    # us the real validation without rejecting otherwise valid manual uploads.
    image_bytes = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(image_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit.",
        )

    try:
        target_path = await save_game_asset(image_bytes, game_id, asset_kind)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not process image: {exc}",
        ) from exc

    return {
        "game_id": str(game_id),
        "asset_kind": asset_kind,
        "path": str(target_path),
        "status": "saved",
    }


@router.post(
    "/{game_id}/assets/{asset_kind}/from-url",
    responses={
        status.HTTP_200_OK: {"description": "Image downloaded and resized"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid URL or image"},
        status.HTTP_404_NOT_FOUND: {"description": "Game not found"},
    },
)
async def download_game_asset(
    game_id: UUID,
    asset_kind: AssetKind,
    payload: AssetUrlRequest,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    """Download an image URL and persist it as a normalized game asset."""
    if asset_kind not in ALLOWED_ASSET_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported asset kind '{asset_kind}'.",
        )

    await _get_game_or_404(game_id, db, current_user.id)
    parsed_url = urlparse(payload.url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Image URL must use http or https."
        )

    try:
        response = await asyncio.to_thread(requests.get, payload.url, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not download image: {exc}"
        ) from exc

    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="URL did not return an image."
        )
    image_bytes = response.content
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(image_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit.",
        )

    try:
        output_path = await save_game_asset(image_bytes, game_id, asset_kind)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not save image: {exc}"
        ) from exc

    return {
        "game_id": str(game_id),
        "asset_kind": asset_kind,
        "path": str(output_path),
        "status": "saved",
    }


def _media_item_to_dict(item: MediaItem, game_id: UUID) -> dict:
    return {
        "id": str(item.id),
        "filename": item.filename,
        "kind": item.kind,
        "url": f"/api/game/{game_id}/screenshots/{item.kind}/{item.filename}",
        "tags": item.tags,
        "note": item.note,
        "linked_achievement_id": str(item.linked_achievement_id)
        if item.linked_achievement_id
        else None,
        "profile_id": str(item.profile_id) if item.profile_id else None,
        "created_at": item.created_at,
    }


@router.post("/{game_id}/screenshots")
async def upload_game_screenshots(
    game_id: UUID,
    files: list[UploadFile] = _FILE_UPLOAD,
    profile_id: UUID | None = _NONE_FORM,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    """Bulk upload — accepts any mix of images, videos, and audio in one
    request. Images become screenshots, videos become clips, audio becomes
    soundtrack; anything else is rejected per-file (the rest still save).
    Each saved file gets a MediaItem row (not just a file on disk) so it can
    be tagged, noted, and linked to an achievement afterward. An optional
    profile_id tags the whole batch to one account (e.g. an OSRS ironman) —
    useful for a "levelup dump from this account" upload in one go."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    if not game.folder_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Game folder_location is missing."
        )
    if profile_id is not None:
        await _get_profile_or_404(profile_id, game_id, db)

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
        # clip routinely exceeds a cover-art-sized limit
        limit_mb = (
            settings.MAX_CLIP_SIZE_MB
            if kind in ("clip", "soundtrack")
            else settings.MAX_UPLOAD_SIZE_MB
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

        dest_dir = (
            _DATA_ROOT / str(game.user_id) / "games" / game.folder_location / media_subdir(kind)
        )
        saved_path = save_media_bytes(data, dest_dir, file.filename or "file")
        db.add(
            MediaItem(game_id=game_id, kind=kind, filename=saved_path.name, profile_id=profile_id)
        )
        results.append({"filename": saved_path.name, "status": "saved", "kind": kind})

    await db.commit()
    return {"results": results}


@router.get("/{game_id}/screenshots")
async def list_game_screenshots(
    game_id: UUID,
    profile_id: UUID | None = _NONE_FORM,
    unscoped_only: bool = Query(False, description="Only items with no profile_id set."),
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    await _get_game_or_404(game_id, db, current_user.id)
    stmt = select(MediaItem).where(MediaItem.game_id == game_id, MediaItem.deleted_at.is_(None))
    if profile_id is not None:
        stmt = stmt.where(MediaItem.profile_id == profile_id)
    elif unscoped_only:
        stmt = stmt.where(MediaItem.profile_id.is_(None))
    result = await db.execute(stmt.order_by(MediaItem.created_at.desc()))
    return {"media": [_media_item_to_dict(item, game_id) for item in result.scalars().all()]}


@router.get("/{game_id}/screenshots/{kind}/{filename}", response_class=FileResponse)
async def get_game_screenshot(
    game_id: UUID,
    kind: MediaKind,
    filename: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> FileResponse:
    game = await _get_game_or_404(game_id, db, current_user.id)
    path = (
        _DATA_ROOT
        / str(game.user_id)
        / "games"
        / (game.folder_location or "")
        / media_subdir(kind)
        / Path(filename).name
    )
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found.")
    return FileResponse(path)


class MediaItemUpdate(BaseModel):
    tags: list[str] | None = None
    note: str | None = None
    linked_achievement_id: UUID | None = None
    profile_id: UUID | None = None


@router.patch("/{game_id}/screenshots/{media_id}")
async def update_media_item(
    game_id: UUID,
    media_id: UUID,
    payload: MediaItemUpdate,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    await _get_game_or_404(game_id, db, current_user.id)
    item = await db.scalar(
        select(MediaItem).where(MediaItem.id == media_id, MediaItem.game_id == game_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media item not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return _media_item_to_dict(item, game_id)


@router.delete("/{game_id}/screenshots/{kind}/{filename}")
async def delete_game_screenshot(
    game_id: UUID,
    kind: MediaKind,
    filename: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    """Soft-delete: moves the file to trash and marks its row deleted
    rather than removing it — restorable for 7 days, same as game
    archives (features/trash/sweep.py does the eventual real deletion)."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    item = await db.scalar(
        select(MediaItem).where(
            MediaItem.game_id == game_id,
            MediaItem.kind == kind,
            MediaItem.filename == filename,
            MediaItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media item not found.")
    game_dir = _DATA_ROOT / str(game.user_id) / "games" / (game.folder_location or "")
    path = game_dir / media_subdir(kind) / Path(filename).name
    move_media_file_to_trash(path, game_dir, kind)
    item.deleted_at = int(time.time())
    await db.commit()
    return {"status": "trashed", "filename": filename}


@router.get("/{game_id}/screenshots/trash")
async def list_game_screenshot_trash(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    await _get_game_or_404(game_id, db, current_user.id)
    result = await db.execute(
        select(MediaItem)
        .where(MediaItem.game_id == game_id, MediaItem.deleted_at.is_not(None))
        .order_by(MediaItem.deleted_at.desc())
    )
    media = []
    for item in result.scalars().all():
        assert item.deleted_at is not None  # guaranteed by the deleted_at.is_not(None) filter above
        media.append(
            {
                **_media_item_to_dict(item, game_id),
                "deleted_at": item.deleted_at,
                "purge_at": item.deleted_at + RETENTION_SECONDS,
            }
        )
    return {"media": media}


@router.post("/{game_id}/screenshots/{kind}/{filename}/restore")
async def restore_game_screenshot(
    game_id: UUID,
    kind: MediaKind,
    filename: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    game = await _get_game_or_404(game_id, db, current_user.id)
    item = await db.scalar(
        select(MediaItem).where(
            MediaItem.game_id == game_id,
            MediaItem.kind == kind,
            MediaItem.filename == filename,
            MediaItem.deleted_at.is_not(None),
        )
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deleted media item not found."
        )
    game_dir = _DATA_ROOT / str(game.user_id) / "games" / (game.folder_location or "")
    restore_media_file_from_trash(filename, game_dir / media_subdir(kind), game_dir, kind)
    item.deleted_at = None
    await db.commit()
    return _media_item_to_dict(item, game_id)


GameFileKind = Literal["doc", "modpack"]
# "save" and "world_save" moved to game_archives.py — named, versioned
# archives instead of an anonymous single flat file each

_GAME_FILE_SUBDIRS: dict[GameFileKind, str] = {
    "doc": "docs",
    "modpack": "modpacks",
}


def _game_file_subdir(kind: GameFileKind) -> str:
    return _GAME_FILE_SUBDIRS[kind]


async def _sync_game_file_items(game_id: UUID, game_dir: Path, db: AsyncSession) -> None:
    """Docs/modpacks used to be tracked only on disk, with no DB row at
    all — this backfills a row (created_at from the file's mtime) for
    anything already sitting in the active folder that doesn't have one
    yet, so existing files from before this migration still show up
    without a one-time manual migration script (same approach as
    media.py's _sync_inbox_items)."""
    existing = await db.execute(
        select(GameFileItem.kind, GameFileItem.filename).where(
            GameFileItem.game_id == game_id, GameFileItem.deleted_at.is_(None)
        )
    )
    known = {(kind, filename) for kind, filename in existing.all()}
    added = False
    for kind in ("doc", "modpack"):
        for filename in list_media(game_dir / _game_file_subdir(kind)):  # type: ignore[arg-type]
            if (kind, filename) in known:
                continue
            path = game_dir / _game_file_subdir(kind) / filename  # type: ignore[arg-type]
            try:
                mtime = int(path.stat().st_mtime)
            except OSError:
                mtime = int(time.time())
            db.add(GameFileItem(game_id=game_id, kind=kind, filename=filename, created_at=mtime))
            added = True
    if added:
        await db.commit()


@router.post("/{game_id}/files/{kind}")
async def upload_game_files(
    game_id: UUID,
    kind: GameFileKind,
    files: list[UploadFile] = _FILE_UPLOAD,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    """Generic file attachments for a game — docs/manuals and modpacks can
    be almost any format, so unlike screenshots/clips there's no
    content-type validation, just a size cap."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    if not game.folder_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Game folder_location is missing."
        )

    # a modpack zip is routinely hundreds of MB to a few GB — far past a
    # doc-sized limit
    limit_mb = settings.MAX_WORLD_SAVE_SIZE_MB if kind == "modpack" else settings.MAX_UPLOAD_SIZE_MB
    max_bytes = limit_mb * 1024 * 1024
    results: list[dict] = []
    for file in files:
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
        dest_dir = (
            _DATA_ROOT
            / str(game.user_id)
            / "games"
            / game.folder_location
            / _game_file_subdir(kind)
        )
        saved_path = save_media_bytes(data, dest_dir, file.filename or "file")
        db.add(GameFileItem(game_id=game_id, kind=kind, filename=saved_path.name))
        results.append({"filename": saved_path.name, "status": "saved", "size": len(data)})

    await db.commit()
    return {"results": results}


@router.get("/{game_id}/files/{kind}")
async def list_game_files(
    game_id: UUID,
    kind: GameFileKind,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    game = await _get_game_or_404(game_id, db, current_user.id)
    if not game.folder_location:
        return {"files": []}
    game_dir = _DATA_ROOT / str(game.user_id) / "games" / game.folder_location
    await _sync_game_file_items(game_id, game_dir, db)
    result = await db.execute(
        select(GameFileItem)
        .where(
            GameFileItem.game_id == game_id,
            GameFileItem.kind == kind,
            GameFileItem.deleted_at.is_(None),
        )
        .order_by(GameFileItem.filename)
    )
    return {
        "files": [
            {
                "filename": item.filename,
                "size": (game_dir / _game_file_subdir(kind) / item.filename).stat().st_size
                if (game_dir / _game_file_subdir(kind) / item.filename).is_file()
                else 0,
                "url": f"/api/game/{game_id}/files/{kind}/{item.filename}",
            }
            for item in result.scalars().all()
        ]
    }


@router.get("/{game_id}/files/{kind}/trash")
async def list_game_file_trash(
    game_id: UUID,
    kind: GameFileKind,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    await _get_game_or_404(game_id, db, current_user.id)
    result = await db.execute(
        select(GameFileItem)
        .where(
            GameFileItem.game_id == game_id,
            GameFileItem.kind == kind,
            GameFileItem.deleted_at.is_not(None),
        )
        .order_by(GameFileItem.deleted_at.desc())
    )
    files = []
    for item in result.scalars().all():
        assert item.deleted_at is not None  # guaranteed by the deleted_at.is_not(None) filter above
        files.append(
            {
                "filename": item.filename,
                "deleted_at": item.deleted_at,
                "purge_at": item.deleted_at + RETENTION_SECONDS,
            }
        )
    return {"files": files}


@router.get("/{game_id}/files/{kind}/{filename}", response_class=FileResponse)
async def get_game_file(
    game_id: UUID,
    kind: GameFileKind,
    filename: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> FileResponse:
    game = await _get_game_or_404(game_id, db, current_user.id)
    path = (
        _DATA_ROOT
        / str(game.user_id)
        / "games"
        / (game.folder_location or "")
        / _game_file_subdir(kind)
        / Path(filename).name
    )
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    # arbitrary user files (saves/docs) should download, not attempt to
    # render inline the way an image/video screenshot asset does — the
    # random 8-char prefix save_media_bytes adds to dedupe filenames is
    # stripped back off for the name the browser actually saves it as
    original_name = Path(filename).name.split("_", 1)[-1]
    return FileResponse(path, filename=original_name, media_type="application/octet-stream")


@router.delete("/{game_id}/files/{kind}/{filename}")
async def delete_game_file(
    game_id: UUID,
    kind: GameFileKind,
    filename: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    """Soft-delete: moves the file to trash and marks its row deleted
    rather than removing it — restorable for 7 days, same as every other
    delete path in the app (features/trash/sweep.py does the eventual
    real deletion)."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    game_dir = _DATA_ROOT / str(game.user_id) / "games" / (game.folder_location or "")
    await _sync_game_file_items(game_id, game_dir, db)
    name = Path(filename).name
    item = await db.scalar(
        select(GameFileItem).where(
            GameFileItem.game_id == game_id,
            GameFileItem.kind == kind,
            GameFileItem.filename == name,
            GameFileItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    path = game_dir / _game_file_subdir(kind) / name
    move_media_file_to_trash(path, game_dir, kind)
    item.deleted_at = int(time.time())
    await db.commit()
    return {"status": "trashed", "filename": name}


@router.post("/{game_id}/files/{kind}/{filename}/restore")
async def restore_game_file(
    game_id: UUID,
    kind: GameFileKind,
    filename: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    game = await _get_game_or_404(game_id, db, current_user.id)
    name = Path(filename).name
    item = await db.scalar(
        select(GameFileItem).where(
            GameFileItem.game_id == game_id,
            GameFileItem.kind == kind,
            GameFileItem.filename == name,
            GameFileItem.deleted_at.is_not(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deleted file not found.")
    game_dir = _DATA_ROOT / str(game.user_id) / "games" / (game.folder_location or "")
    restore_media_file_from_trash(name, game_dir / _game_file_subdir(kind), game_dir, kind)
    item.deleted_at = None
    await db.commit()
    return {"status": "restored", "filename": name}


@router.put(
    "/{game_id}/notes/{note_name}",
    responses={
        status.HTTP_201_CREATED: {"description": "Note created or updated"},
        status.HTTP_404_NOT_FOUND: {"description": "Game not found"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid note name"},
    },
)
async def set_game_note(
    game_id: UUID,
    note_name: str,
    payload: NoteWrite = _BODY_DOTDOTDOT,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str | None]:
    """Create or replace a markdown note for a game."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    note_path = _game_note_path(game, note_name)
    note_path.write_text(payload.content, encoding="utf-8")

    return {
        "game_id": str(game_id),
        "note_name": _normalize_note_name(note_name),
        "path": str(note_path),
        "status": "saved",
    }


@router.get(
    "/{game_id}/notes",
    responses={
        status.HTTP_200_OK: {"description": "List of markdown notes for the game"},
        status.HTTP_404_NOT_FOUND: {"description": "Game not found"},
    },
)
async def list_game_notes(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[str]]:
    """Return the markdown note names associated with a game."""
    game = await _get_game_or_404(game_id, db, current_user.id)

    if not game.folder_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Game folder_location is missing.",
        )

    notes_dir = _DATA_ROOT / str(game.user_id) / "games" / game.folder_location / "notes"
    if not notes_dir.exists():
        return {"notes": []}

    note_names = sorted(
        path.stem for path in notes_dir.iterdir() if path.is_file() and path.suffix.lower() == ".md"
    )
    return {"notes": note_names}


@router.get(
    "/{game_id}/notes/{note_name}",
    responses={
        status.HTTP_200_OK: {"description": "Markdown note contents"},
        status.HTTP_404_NOT_FOUND: {"description": "Game or note not found"},
    },
)
async def get_game_note(
    game_id: UUID,
    note_name: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> Response:
    """Return the contents of one game note as markdown."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    note_path = _game_note_path(game, note_name)

    if not note_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note '{_normalize_note_name(note_name)}' not found for game {game_id}",
        )

    return Response(
        content=note_path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8"
    )


@router.delete(
    "/{game_id}/notes/{note_name}",
    responses={
        status.HTTP_200_OK: {"description": "Note deleted"},
        status.HTTP_404_NOT_FOUND: {"description": "Game or note not found"},
    },
)
async def delete_game_note(
    game_id: UUID,
    note_name: str,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    """Delete one markdown note from a game."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    note_path = _game_note_path(game, note_name)

    if not note_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note '{_normalize_note_name(note_name)}' not found for game {game_id}",
        )

    note_path.unlink()
    return {
        "game_id": str(game_id),
        "note_name": _normalize_note_name(note_name),
        "status": "deleted",
    }


async def _get_profile_or_404(
    profile_id: UUID, game_id: UUID, db: AsyncSession, include_deleted: bool = False
) -> GameProfile:
    stmt = select(GameProfile).where(GameProfile.id == profile_id, GameProfile.game_id == game_id)
    if not include_deleted:
        stmt = stmt.where(GameProfile.deleted_at.is_(None))
    profile = await db.scalar(stmt)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return profile


def _profile_to_dict(profile: GameProfile) -> dict:
    return {
        "id": str(profile.id),
        "game_id": str(profile.game_id),
        "name": profile.name,
        "note": profile.note,
        "stats": profile.stats,
        "wiseoldman_username": profile.wiseoldman_username,
        "created_at": profile.created_at,
    }


async def _record_stat_snapshot(
    db: AsyncSession,
    profile_id: UUID,
    stats: dict[str, str],
    recorded_at: int | None = None,
    xp: dict[str, int] | None = None,
    kc: dict[str, int] | None = None,
) -> None:
    """Called whenever a profile's stats change (manual edit or WiseOldMan
    sync) — a dated copy so progression can be shown later instead of only
    ever seeing the current numbers. xp/kc (WiseOldMan syncs only — a
    manual edit leaves them empty) are the raw integers a "gained this
    much" digest needs; `stats` alone (display strings) isn't precise
    enough since a level can span tens of thousands of XP. Not deduped:
    two saves the same minute just make two rows, which is harmless and
    keeps this simple."""
    if not stats:
        return
    db.add(
        GameProfileStatSnapshot(
            profile_id=profile_id,
            stats=stats,
            xp=xp or {},
            kc=kc or {},
            recorded_at=recorded_at or int(time.time()),
        )
    )


class ProfileWrite(BaseModel):
    name: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    note: str | None = None
    stats: dict[str, str] | None = None
    wiseoldman_username: str | None = None


@router.get("/{game_id}/profiles")
async def list_game_profiles(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    """Named sub-scopes for a game (e.g. separate OSRS accounts) — lets
    checklist items and screenshots be filtered down to one instead of
    mixed together across every account the game has."""
    await _get_game_or_404(game_id, db, current_user.id)
    result = await db.execute(
        select(GameProfile)
        .where(GameProfile.game_id == game_id, GameProfile.deleted_at.is_(None))
        .order_by(GameProfile.created_at.asc())
    )
    return {"profiles": [_profile_to_dict(p) for p in result.scalars().all()]}


@router.post("/{game_id}/profiles", status_code=status.HTTP_201_CREATED)
async def create_game_profile(
    game_id: UUID,
    payload: ProfileWrite,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    await _get_game_or_404(game_id, db, current_user.id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required.")
    profile = GameProfile(game_id=game_id, name=name)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return _profile_to_dict(profile)


@router.patch("/{game_id}/profiles/{profile_id}")
async def update_game_profile(
    game_id: UUID,
    profile_id: UUID,
    payload: ProfileUpdate,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    await _get_game_or_404(game_id, db, current_user.id)
    profile = await _get_profile_or_404(profile_id, game_id, db)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        name = (updates["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required.")
        updates["name"] = name
    for field, value in updates.items():
        setattr(profile, field, value)
    if "stats" in updates:
        await _record_stat_snapshot(db, profile.id, updates["stats"])
    await db.commit()
    await db.refresh(profile)
    return _profile_to_dict(profile)


class WiseOldManSyncRequest(BaseModel):
    username: str | None = None


_WISEOLDMAN_SYNC_BODY = Body(default=WiseOldManSyncRequest())


@router.post("/{game_id}/profiles/{profile_id}/sync-wiseoldman")
async def sync_profile_wiseoldman(
    game_id: UUID,
    profile_id: UUID,
    payload: WiseOldManSyncRequest = _WISEOLDMAN_SYNC_BODY,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Pulls current skill levels from wiseoldman.net (OSRS's community
    stat tracker, no account/API key needed) into this profile's stats.
    Manual, click-to-sync — no scheduled background refresh."""
    await _get_game_or_404(game_id, db, current_user.id)
    profile = await _get_profile_or_404(profile_id, game_id, db)
    username = (payload.username or profile.wiseoldman_username or "").strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A WiseOldMan username is required."
        )
    try:
        result = await asyncio.to_thread(wiseoldman.get_player_stats, username)
    except wiseoldman.WiseOldManError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    stats = dict(result["stats"])
    if result.get("combat_level"):
        stats["Combat"] = result["combat_level"]
    profile.stats = stats
    profile.wiseoldman_username = username

    # first sync ever for this profile — backfill whatever history
    # WiseOldMan already has for the account (only as good as how often
    # *someone* updated it there before), so progression doesn't start
    # from a blank slate just because this is the first time this app
    # asked. A later sync only ever adds today's snapshot below.
    has_history = await db.scalar(
        select(GameProfileStatSnapshot.id)
        .where(GameProfileStatSnapshot.profile_id == profile.id)
        .limit(1)
    )
    if has_history is None:
        try:
            history = await asyncio.to_thread(wiseoldman.get_player_snapshots, username)
        except Exception:  # noqa: BLE001 — backfill is best-effort, never blocks the sync itself
            history = []
        for entry in history:
            await _record_stat_snapshot(
                db,
                profile.id,
                entry["stats"],
                entry["recorded_at"],
                entry.get("xp"),
                entry.get("kc"),
            )

    await _record_stat_snapshot(db, profile.id, stats, xp=result.get("xp"), kc=result.get("kc"))
    await db.commit()
    await db.refresh(profile)
    return _profile_to_dict(profile)


@router.get("/{game_id}/profiles/{profile_id}/stat-history")
async def get_profile_stat_history(
    game_id: UUID,
    profile_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    await _get_game_or_404(game_id, db, current_user.id)
    await _get_profile_or_404(profile_id, game_id, db)
    result = await db.execute(
        select(GameProfileStatSnapshot)
        .where(GameProfileStatSnapshot.profile_id == profile_id)
        .order_by(GameProfileStatSnapshot.recorded_at.desc())
    )
    return {
        "snapshots": [
            {
                "id": str(s.id),
                "recorded_at": s.recorded_at,
                "stats": s.stats,
                "xp": s.xp,
                "kc": s.kc,
            }
            for s in result.scalars().all()
        ]
    }


@router.delete("/{game_id}/profiles/{profile_id}")
async def delete_game_profile(
    game_id: UUID,
    profile_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    """Soft-delete only — no files involved, so this just flips the flag
    (features/trash/sweep.py purges the row itself after 7 days). Checklist
    items and media tagged to this profile keep their profile_id and
    simply stop showing up under an active profile filter until restored."""
    await _get_game_or_404(game_id, db, current_user.id)
    profile = await _get_profile_or_404(profile_id, game_id, db)
    profile.deleted_at = int(time.time())
    await db.commit()
    return {"status": "trashed", "id": str(profile_id)}


@router.get("/{game_id}/profiles/trash")
async def list_game_profile_trash(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    await _get_game_or_404(game_id, db, current_user.id)
    result = await db.execute(
        select(GameProfile).where(
            GameProfile.game_id == game_id, GameProfile.deleted_at.is_not(None)
        )
    )
    profiles = []
    for p in result.scalars().all():
        assert p.deleted_at is not None  # guaranteed by the deleted_at.is_not(None) filter above
        profiles.append(
            {
                **_profile_to_dict(p),
                "deleted_at": p.deleted_at,
                "purge_at": p.deleted_at + RETENTION_SECONDS,
            }
        )
    return {"profiles": profiles}


@router.post("/{game_id}/profiles/{profile_id}/restore")
async def restore_game_profile(
    game_id: UUID,
    profile_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    await _get_game_or_404(game_id, db, current_user.id)
    profile = await _get_profile_or_404(profile_id, game_id, db, include_deleted=True)
    if profile.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Profile is not trashed."
        )
    profile.deleted_at = None
    await db.commit()
    await db.refresh(profile)
    return _profile_to_dict(profile)


def _checklist_item_to_dict(item: GameChecklistItem) -> dict:
    return {
        "id": str(item.id),
        "game_id": str(item.game_id),
        "profile_id": str(item.profile_id) if item.profile_id else None,
        "text": item.text,
        "done": item.done,
        "is_header": item.is_header,
        "sort_order": item.sort_order,
        "created_at": item.created_at,
    }


class ChecklistItemWrite(BaseModel):
    text: str
    profile_id: UUID | None = None
    is_header: bool = False


class ChecklistItemUpdate(BaseModel):
    text: str | None = None
    done: bool | None = None
    is_header: bool | None = None
    sort_order: float | None = None


@router.get("/{game_id}/checklist")
async def list_game_checklist(
    game_id: UUID,
    profile_id: UUID | None = _NONE_FORM,
    unscoped_only: bool = Query(False, description="Only items with no profile_id set."),
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, list[dict]]:
    await _get_game_or_404(game_id, db, current_user.id)
    stmt = select(GameChecklistItem).where(
        GameChecklistItem.game_id == game_id, GameChecklistItem.deleted_at.is_(None)
    )
    if profile_id is not None:
        stmt = stmt.where(GameChecklistItem.profile_id == profile_id)
    elif unscoped_only:
        stmt = stmt.where(GameChecklistItem.profile_id.is_(None))
    result = await db.execute(
        stmt.order_by(GameChecklistItem.sort_order.asc(), GameChecklistItem.created_at.asc())
    )
    return {"items": [_checklist_item_to_dict(item) for item in result.scalars().all()]}


@router.post("/{game_id}/checklist", status_code=status.HTTP_201_CREATED)
async def create_checklist_item(
    game_id: UUID,
    payload: ChecklistItemWrite,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    await _get_game_or_404(game_id, db, current_user.id)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required.")
    if payload.profile_id is not None:
        await _get_profile_or_404(payload.profile_id, game_id, db)
    max_sort = await db.scalar(
        select(func.max(GameChecklistItem.sort_order)).where(
            GameChecklistItem.game_id == game_id, GameChecklistItem.profile_id == payload.profile_id
        )
    )
    item = GameChecklistItem(
        game_id=game_id,
        profile_id=payload.profile_id,
        text=text,
        is_header=payload.is_header,
        sort_order=(max_sort or 0) + 1,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _checklist_item_to_dict(item)


class ChecklistReorder(BaseModel):
    # the full ordered list of item ids within one scope (profile_id must
    # match what they were fetched/created under) — sent whole rather than
    # as a single move, so an up/down-arrow swap and a future drag-and-drop
    # both reduce to "here's the new order" instead of two different APIs
    profile_id: UUID | None = None
    item_ids: list[UUID]


@router.put("/{game_id}/checklist/reorder")
async def reorder_checklist(
    game_id: UUID,
    payload: ChecklistReorder,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    await _get_game_or_404(game_id, db, current_user.id)
    result = await db.execute(
        select(GameChecklistItem).where(
            GameChecklistItem.game_id == game_id,
            GameChecklistItem.profile_id == payload.profile_id,
            GameChecklistItem.deleted_at.is_(None),
        )
    )
    items_by_id = {item.id: item for item in result.scalars().all()}
    for index, item_id in enumerate(payload.item_ids):
        item = items_by_id.get(item_id)
        if item is not None:
            item.sort_order = float(index)
    await db.commit()
    return {"status": "reordered"}


@router.patch("/{game_id}/checklist/{item_id}")
async def update_checklist_item(
    game_id: UUID,
    item_id: UUID,
    payload: ChecklistItemUpdate,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    await _get_game_or_404(game_id, db, current_user.id)
    item = await db.scalar(
        select(GameChecklistItem).where(
            GameChecklistItem.id == item_id,
            GameChecklistItem.game_id == game_id,
            GameChecklistItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found."
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return _checklist_item_to_dict(item)


@router.delete("/{game_id}/checklist/{item_id}")
async def delete_checklist_item(
    game_id: UUID,
    item_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, str]:
    await _get_game_or_404(game_id, db, current_user.id)
    item = await db.scalar(
        select(GameChecklistItem).where(
            GameChecklistItem.id == item_id,
            GameChecklistItem.game_id == game_id,
            GameChecklistItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found."
        )
    item.deleted_at = int(time.time())
    await db.commit()
    return {"status": "trashed", "id": str(item_id)}


async def _validate_game_relationship(
    parent_game_id: UUID | None,
    relationship_type: str | None,
    db: AsyncSession,
    user_id: UUID,
    game_id: UUID | None = None,
) -> None:
    """A relationship_type only makes sense alongside a parent_game_id
    (GameUpdate can't enforce this itself — a partial update might set only
    one of the two fields in a given request, with the other already
    correct from an earlier one). Also blocks a game being its own parent
    and pointing at a parent that isn't actually this user's."""
    if relationship_type is not None and parent_game_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="relationship_type requires parent_game_id to be set.",
        )
    if parent_game_id is None:
        return
    if game_id is not None and parent_game_id == game_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A game cannot be its own parent."
        )
    parent = await db.scalar(
        select(Game).where(
            Game.id == parent_game_id, Game.user_id == user_id, Game.deleted_at.is_(None)
        )
    )
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="parent_game_id does not exist."
        )


@router.post(
    "/create",
    response_model=GameRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "Duplicate folder_location",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "duplicate_folder_location",
                            "field": "folder_location",
                            "value": "ExistingFolder",
                            "message": "A game with folder_location 'ExistingFolder' already exists.",
                        }
                    }
                }
            },
        }
    },
)
async def create_game(
    payload: GameCreate,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> Game:
    """Create a game after validating its folder location."""
    await _ensure_folder_location_available(payload.folder_location, current_user.id, db)
    await _validate_game_relationship(
        payload.parent_game_id, payload.relationship_type, db, current_user.id
    )

    data = payload.model_dump()
    data["user_id"] = current_user.id
    if not data.get("sort_title"):
        data["sort_title"] = _derive_sort_title(data["title"])

    # `links` is a relationship, not a plain column — the constructor needs
    # actual GameLink instances, not the raw {label, url} dicts model_dump
    # produces
    link_rows = [GameLink(label=link["label"], url=link["url"]) for link in data.pop("links", [])]

    game = Game(**data)
    game.links = link_rows
    db.add(game)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _duplicate_folder_error(payload.folder_location) from exc

    create_game_folder(game.user_id, game.folder_location)
    return game


@router.get("/list", response_model=list[GameRead])
async def list_games(
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
    status_filter: GameStatus | None = _NONE_QUERY_STATUS,
    favorite: bool | None = Query(default=None),
    search: str | None = Query(default=None, description="Case-insensitive title search"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Game]:
    """Return games filtered by status, favorite flag, or title search."""
    stmt = select(Game).where(Game.user_id == current_user.id, Game.deleted_at.is_(None))

    if status_filter is not None:
        stmt = stmt.where(Game.status == status_filter)
    if favorite is not None:
        stmt = stmt.where(Game.favorite == favorite)
    if search:
        stmt = stmt.where(Game.title.ilike(f"%{search}%"))

    stmt = stmt.order_by(Game.sort_title).offset(skip).limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/get/{game_id}", response_model=GameRead)
async def get_game(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> Game:
    """Return one game by ID."""
    return await _get_game_or_404(game_id, db, current_user.id)


@router.get("/{game_id}/variants", response_model=list[GameRead])
async def get_game_variants(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> list[Game]:
    """Every game whose parent_game_id points at this one — the reverse of
    the parent breadcrumb (GameDetail.vue's `parentGameTitle`). A base game
    like Minecraft has no idea its modpacks exist otherwise, since the FK
    only points child -> parent."""
    await _get_game_or_404(game_id, db, current_user.id)
    stmt = (
        select(Game)
        .where(
            Game.user_id == current_user.id,
            Game.parent_game_id == game_id,
            Game.deleted_at.is_(None),
        )
        .order_by(Game.sort_title)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.patch(
    "/update/{game_id}",
    response_model=GameRead,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "Duplicate folder_location",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "duplicate_folder_location",
                            "field": "folder_location",
                            "value": "ExistingFolder",
                            "message": "A game with folder_location 'ExistingFolder' already exists.",
                        }
                    }
                }
            },
        }
    },
)
async def update_game(
    game_id: UUID,
    payload: GameUpdate,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> Game:
    """Update a game and keep its derived sort title synchronized."""
    game = await _get_game_or_404(game_id, db, current_user.id)

    updates = payload.model_dump(exclude_unset=True)

    if "folder_location" in updates and updates["folder_location"] is not None:
        await _ensure_folder_location_available(
            updates["folder_location"], current_user.id, db, exclude_game_id=game_id
        )

    if "parent_game_id" in updates or "relationship_type" in updates:
        effective_parent = updates.get("parent_game_id", game.parent_game_id)
        effective_relationship = updates.get("relationship_type", game.relationship_type)
        await _validate_game_relationship(
            effective_parent, effective_relationship, db, current_user.id, game_id
        )

    # `links` is a relationship, not a plain column — setattr needs actual
    # GameLink instances, not the raw {label, url} dicts model_dump
    # produces. Reassigning the whole list lets cascade="all, delete-orphan"
    # (see Game.links) drop whichever rows aren't in the new list.
    if "links" in updates:
        new_links = updates.pop("links") or []
        game.links = [GameLink(label=link["label"], url=link["url"]) for link in new_links]

    _record_field_changes(game, updates, db)
    apply_updates_with_locking(game, updates, frozenset(_GAME_METADATA_FIELDS))

    for field, value in updates.items():
        setattr(game, field, value)

    # Keep sort_title in sync if title changed but sort_title wasn't explicitly set
    if "title" in updates and "sort_title" not in updates:
        game.sort_title = _derive_sort_title(game.title)

    # first time this game reaches Mastered, record when — a later status
    # change away from and back to Mastered doesn't overwrite it, so it
    # stays "when I first 100%'d this" rather than "when I last did"
    if updates.get("status") == GameStatus.MASTERED and game.completion_date is None:
        game.completion_date = int(time.time())

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _duplicate_folder_error(game.folder_location) from exc

    return game


_GAME_METADATA_FIELDS = frozenset({
    "title",
    "description",
    "developer",
    "publisher",
    "series",
    "tags",
    "features",
    "age_rating",
    "release_date",
    "time_to_beat_hours",
    "links",
})


def _normalize_metadata_title(title: str) -> str:
    return title.replace("™", "").replace("®", "").replace("©", "").strip().lower()


def _metadata_value_is_present(value: object) -> bool:
    return value is not None and value != "" and value != []


@router.post("/{game_id}/metadata/refresh")
async def refresh_game_metadata(
    game_id: UUID,
    payload: MetadataRefreshRequest,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict:
    """Preview or apply a metadata-provider refresh for one game.

    Provider lookup uses the same configured game metadata registry as the
    existing search flow. Applying is server-side so authorization, locks,
    history, artwork protection, and stale-editor detection cannot be bypassed
    by a client replaying a provider result.
    """
    game = await _get_game_or_404(game_id, db, current_user.id)
    scan_settings = await get_or_create_scan_settings(current_user.id, db)
    preferences = _scan_settings_to_preferences(scan_settings)
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))

    try:
        result = await asyncio.to_thread(
            search_game_metadata,
            game.title,
            8,
            current_user.steamgriddb_api_key,
            preferences,
            current_user,
            app_integrations.igdb_client_id,
            app_integrations.igdb_client_secret,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Metadata providers could not be reached: {exc}",
        ) from exc

    providers = result.get("providers", [])
    provider_errors = result.get("provider_errors", [])
    if providers:
        last_used = dict(scan_settings.provider_last_used)
        now = int(time.time())
        for provider_name in providers:
            last_used[provider_name] = now
        scan_settings.provider_last_used = last_used

    match = next(
        (
            candidate
            for candidate in result.get("results", [])
            if isinstance(candidate, dict)
            and _normalize_metadata_title(str(candidate.get("title") or ""))
            == _normalize_metadata_title(game.title)
        ),
        None,
    )
    if match is None:
        await db.commit()
        return {
            "status": "no-match",
            "provider": None,
            "provider_errors": provider_errors,
            "changed_fields": [],
            "skipped_locked_fields": [],
            "would_add_key_art": False,
            "would_add_banner": False,
            "game_updated_at": game.updated_at,
        }

    field_values: dict[str, object] = {
        "title": match.get("title"),
        "description": match.get("description"),
        "developer": match.get("developer"),
        "publisher": match.get("publisher"),
        "series": match.get("series"),
        "tags": match.get("tags"),
        "features": match.get("features"),
        "age_rating": match.get("age_rating"),
        "release_date": match.get("release_date"),
        "time_to_beat_hours": match.get("time_to_beat_hours"),
        "links": match.get("links"),
    }
    gated_flags = {
        "developer": "save_developer",
        "publisher": "save_publisher",
        "series": "save_series",
        "tags": "save_tags",
        "features": "save_features",
        "description": "save_description",
        "age_rating": "save_age_rating",
        "release_date": "save_release_date",
        "time_to_beat_hours": "save_time_to_beat",
    }
    updates: dict[str, object] = {}
    skipped_locked: list[str] = []
    for field, fresh in field_values.items():
        if field != "title" and gated_flags.get(field) and not preferences.get(gated_flags[field], True):
            continue
        if not _metadata_value_is_present(fresh):
            continue
        if field in game.locked_fields:
            skipped_locked.append(field)
            continue
        current = getattr(game, field)
        if fresh != current:
            updates[field] = fresh

    changed_fields = sorted(updates)
    key_art_url = match.get("key_art_url")
    banner_url = match.get("banner_url")
    game_dir = _DATA_ROOT / str(game.user_id) / "games" / game.folder_location
    key_art_exists = (game_dir / ASSET_FILENAMES["key_art"]).is_file()
    banner_exists = (game_dir / ASSET_FILENAMES["banner"]).is_file()
    would_add_key_art = bool(
        payload.fill_missing_art and key_art_url and (payload.overwrite_existing_art or not key_art_exists)
    )
    would_add_banner = bool(
        payload.fill_missing_art and banner_url and (payload.overwrite_existing_art or not banner_exists)
    )

    if payload.dry_run:
        # A preview records no game changes, but the existing provider-last-used
        # telemetry may be updated as part of the provider lookup.
        await db.commit()
        return {
            "status": "preview",
            "provider": match.get("provider"),
            "provider_errors": provider_errors,
            "changed_fields": changed_fields,
            "skipped_locked_fields": sorted(set(skipped_locked)),
            "would_add_key_art": would_add_key_art,
            "would_add_banner": would_add_banner,
            "game_updated_at": game.updated_at,
        }

    if payload.expected_updated_at is not None:
        # The preview may have been open while another tab or sync changed the game.
        # Re-read under a row lock before applying so two concurrent refreshes cannot
        # both pass the same stale timestamp.
        await db.rollback()
        locked_game = await db.scalar(
            select(Game)
            .where(Game.id == game_id, Game.user_id == current_user.id, Game.deleted_at.is_(None))
            .with_for_update()
        )
        if locked_game is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Game {game_id} not found")
        if locked_game.updated_at != payload.expected_updated_at:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Game changed after the metadata preview. Refresh the editor and try again.",
            )
        game = locked_game
        # Recompute from the freshly locked row. Locks and configured save_* flags
        # may have changed while the preview was open, so do not trust preview data.
        updates = {}
        skipped_locked = []
        for field, fresh in field_values.items():
            if field != "title" and gated_flags.get(field) and not preferences.get(gated_flags[field], True):
                continue
            if not _metadata_value_is_present(fresh):
                continue
            if field in game.locked_fields:
                skipped_locked.append(field)
                continue
            if getattr(game, field) != fresh:
                updates[field] = fresh
        changed_fields = sorted(updates)
        key_art_exists = (game_dir / ASSET_FILENAMES["key_art"]).is_file()
        banner_exists = (game_dir / ASSET_FILENAMES["banner"]).is_file()

    if payload.update_text:
        _record_field_changes(game, updates, db)
        for field, value in updates.items():
            setattr(game, field, value)

    if payload.fill_missing_art:
        async def _download_art(url: str) -> bytes:
            response = await asyncio.to_thread(requests.get, url, timeout=20)
            response.raise_for_status()
            return response.content

        if key_art_url and (payload.overwrite_existing_art or not key_art_exists):
            try:
                await save_game_asset(await _download_art(str(key_art_url)), game.id, "key_art")
            except Exception as exc:  # noqa: BLE001 — one image must not cancel text metadata
                provider_errors.append(f"{match.get('provider', 'Metadata')}: cover art could not be downloaded: {exc}")
            else:
                would_add_key_art = True
        if banner_url and (payload.overwrite_existing_art or not banner_exists):
            try:
                await save_game_asset(await _download_art(str(banner_url)), game.id, "banner")
            except Exception as exc:  # noqa: BLE001 — one image must not cancel text metadata
                provider_errors.append(f"{match.get('provider', 'Metadata')}: banner art could not be downloaded: {exc}")
            else:
                would_add_banner = True

    await db.commit()
    await db.refresh(game)
    return {
        "status": "updated",
        "provider": match.get("provider"),
        "provider_errors": provider_errors,
        "changed_fields": changed_fields,
        "skipped_locked_fields": sorted(set(skipped_locked)),
        "would_add_key_art": would_add_key_art,
        "would_add_banner": would_add_banner,
        "game_updated_at": game.updated_at,
    }


@router.get("/{game_id}/field-changes", response_model=list[GameFieldChangeRead])
async def list_field_changes(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> list[GameFieldChange]:
    """Most-recent-first metadata history for one game."""
    await _get_game_or_404(game_id, db, current_user.id)
    stmt = (
        select(GameFieldChange)
        .where(GameFieldChange.game_id == game_id)
        .order_by(GameFieldChange.changed_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.patch("/bulk-update")
async def bulk_update_games(
    payload: GameBulkUpdate,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> dict[str, int]:
    """Apply the same field values to many of the caller's games at once —
    e.g. fixing status across a batch, or filling in developer/publisher
    for titles a metadata search couldn't confidently match on its own."""
    updates = payload.model_dump(exclude_unset=True, exclude={"game_ids"})
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update.")

    result = await db.execute(
        select(Game).where(
            Game.user_id == current_user.id,
            Game.id.in_(payload.game_ids),
            Game.deleted_at.is_(None),
        )
    )
    games = result.scalars().all()
    for game in games:
        for field, value in updates.items():
            setattr(game, field, value)
        if updates.get("status") == GameStatus.MASTERED and game.completion_date is None:
            game.completion_date = int(time.time())
    await db.commit()
    return {"updated": len(games)}


@router.delete("/delete/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> None:
    """Soft-delete: moves the game's entire folder to trash and marks the
    row deleted rather than removing anything — restorable for 7 days.
    This is the highest-blast-radius delete in the app (screenshots,
    clips, notes, achievements, saves, everything lives under this one
    folder), so it gets the same protection as game archives instead of
    the instant, permanent delete it had before."""
    game = await _get_game_or_404(game_id, db, current_user.id)
    if game.folder_location:
        move_game_to_trash(
            _DATA_ROOT / str(game.user_id) / "games" / game.folder_location, _DATA_ROOT, game_id
        )
    game.deleted_at = int(time.time())
    await db.commit()


@router.get("/trash")
async def list_game_trash(
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> list[dict]:
    result = await db.execute(
        select(Game)
        .where(Game.user_id == current_user.id, Game.deleted_at.is_not(None))
        .order_by(Game.deleted_at.desc())
    )
    trashed = []
    for game in result.scalars().all():
        assert game.deleted_at is not None  # guaranteed by the deleted_at.is_not(None) filter above
        trashed.append(
            {
                "id": str(game.id),
                "title": game.title,
                "deleted_at": game.deleted_at,
                "purge_at": game.deleted_at + RETENTION_SECONDS,
            }
        )
    return trashed


@router.post("/{game_id}/restore", response_model=GameRead)
async def restore_game(
    game_id: UUID,
    db: AsyncSession = _DB_DEPENDENCY,
    current_user: User = _CURRENT_USER_DEPENDENCY,
) -> Game:
    game = await _get_game_or_404(game_id, db, current_user.id, include_deleted=True)
    if game.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Game isn't deleted.")
    if game.folder_location:
        # a new active game may have claimed this folder name while this one
        # sat in trash (the partial unique index only protects active rows) —
        # check before touching any files, not after, so a rejected restore
        # never leaves the folder half-moved
        await _ensure_folder_location_available(
            game.folder_location, current_user.id, db, exclude_game_id=game_id
        )
        restore_game_from_trash(
            _DATA_ROOT / str(game.user_id) / "games" / game.folder_location, _DATA_ROOT, game_id
        )
    game.deleted_at = None
    await db.commit()
    await db.refresh(game)
    return game
