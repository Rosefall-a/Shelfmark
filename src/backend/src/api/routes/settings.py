# pylint: disable=missing-class-docstring,missing-function-docstring,not-callable,too-many-locals,too-many-branches,duplicate-code
"""API routes for app/user Settings — scan (metadata) preferences,
per-user metadata-provider credentials, and read-only server config the
frontend needs to display (e.g. upload limits)."""

import asyncio

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from fastapi.responses import FileResponse

from pydantic import BaseModel

from sqlalchemy import func, select

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.appearance_settings import AppearanceSettingsRead, AppearanceSettingsUpdate

from src.api.schemas.scan_settings import ScanSettingsRead, ScanSettingsUpdate

from src.core.app_integrations import get_or_create_app_integration_settings

from src.core.auth import get_current_admin, get_current_user

from src.core.config import settings

from src.core.crypto import decrypt_secret, encrypt_secret

from src.core.integrations import resolve_integrations

from src.database.models.app_integration_settings import AppIntegrationSettings

from src.database.models.game import Game

from src.database.models.user import User

from src.database.models.user_appearance_settings import UserAppearanceSettings

from src.database.models.user_scan_settings import UserScanSettings

from src.database.session import get_db

from src.features.metadata import refresh_job

from src.features.metadata.games import steam

from src.features.metadata.games.giant_bomb import GiantBombClient, GiantBombError

from src.features.metadata.games.gog import GOGClient, GOGError

from src.features.metadata.games.retroachievements import (
    RetroAchievementsClient,
    RetroAchievementsError,
)

from src.features.metadata.games.screenscraper import ScreenScraperClient, ScreenScraperError

from src.features.metadata.games.steam import SteamLibraryError

from src.features.metadata.games.xbox import XboxClient, XboxError

from src.helpers.save_badge_image import badge_image_path, delete_badge_image, save_badge_image

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)

# provider key -> [(payload field name, User column name, is Fernet-encrypted)]
PROVIDER_FIELD_MAP: dict[str, list[tuple[str, str, bool]]] = {
    "Steam": [("steam_id", "steam_id", False), ("api_key", "steam_api_key", False)],
    "RetroAchievements": [
        ("api_key", "retroachievements_api_key", False),
        ("username", "retroachievements_username", False),
    ],
    "GiantBomb": [("api_key", "giantbomb_api_key", False)],
    "ScreenScraper": [
        ("ssid", "screenscraper_ssid", False),
        ("sspassword", "screenscraper_sspassword", True),
    ],
    "Xbox": [("client_id", "xbox_client_id", False), ("client_secret", "xbox_client_secret", True)],
    "GOG": [("refresh_token", "gog_refresh_token", True)],
}

_ProviderClientError = (
    SteamLibraryError,
    RetroAchievementsError,
    GiantBombError,
    ScreenScraperError,
    XboxError,
    GOGError,
)


def _validate_provider(provider: str, user: User) -> dict:
    """Builds the right client for `provider` from the user's stored
    credentials and calls its `.validate()`. Raises one of
    `_ProviderClientError` on failure."""
    if provider == "Steam":
        if not user.steam_id or not user.steam_api_key:
            raise SteamLibraryError("Steam ID and API key are both required.")
        games = steam.get_owned_games(user.steam_id, user.steam_api_key)
        summary = steam.get_player_summary(user.steam_id, user.steam_api_key)
        return {
            "validated": True,
            "games_found": len(games),
            "persona_name": summary.get("personaname"),
            "avatar_url": summary.get("avatarfull"),
        }
    if provider == "RetroAchievements":
        client = RetroAchievementsClient(user.retroachievements_api_key or "")
        result = client.validate()
        if user.retroachievements_username:
            summary = client.get_user_summary(user.retroachievements_username)
            result["avatar_url"] = (
                f"https://media.retroachievements.org{summary['UserPic']}"
                if summary.get("UserPic")
                else None
            )
        return result
    if provider == "GiantBomb":
        return GiantBombClient(user.giantbomb_api_key or "").validate()
    if provider == "ScreenScraper":
        return ScreenScraperClient(
            devid=settings.SCREENSCRAPER_DEVID or "",
            devpassword=settings.SCREENSCRAPER_DEVPASSWORD or "",
            ssid=user.screenscraper_ssid or "",
            sspassword=decrypt_secret(user.screenscraper_sspassword)
            if user.screenscraper_sspassword
            else "",
        ).validate()
    if provider == "Xbox":
        return XboxClient(
            user.xbox_client_id or "",
            decrypt_secret(user.xbox_client_secret) if user.xbox_client_secret else "",
        ).validate()
    if provider == "GOG":
        return GOGClient(
            decrypt_secret(user.gog_refresh_token) if user.gog_refresh_token else ""
        ).validate()
    raise ValueError(f"Unknown provider: {provider}")


class ProviderCredentialsRequest(BaseModel):
    fields: dict[str, str]


async def get_or_create_scan_settings(user_id: UUID, db: AsyncSession) -> UserScanSettings:
    """Every user gets a scan-settings row lazily, on first access, rather
    than needing one created at signup time."""
    scan_settings = await db.scalar(
        select(UserScanSettings).where(UserScanSettings.user_id == user_id)
    )
    if scan_settings is None:
        scan_settings = UserScanSettings(user_id=user_id)
        db.add(scan_settings)
        await db.commit()
        await db.refresh(scan_settings)
    return scan_settings


@router.get("/scan", response_model=ScanSettingsRead)
async def get_scan_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserScanSettings:
    """Return the caller's metadata-scan preferences (provider order, which
    fields a search result is allowed to save)."""
    return await get_or_create_scan_settings(current_user.id, db)


@router.put("/scan", response_model=ScanSettingsRead)
async def update_scan_settings(
    payload: ScanSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserScanSettings:
    """Update the caller's metadata-scan preferences."""
    scan_settings = await get_or_create_scan_settings(current_user.id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(scan_settings, field, value)
    await db.commit()
    await db.refresh(scan_settings)
    return scan_settings


async def get_or_create_appearance_settings(
    user_id: UUID, db: AsyncSession
) -> UserAppearanceSettings:
    """Every user gets an appearance-settings row lazily, same pattern as
    get_or_create_scan_settings."""
    appearance = await db.scalar(
        select(UserAppearanceSettings).where(UserAppearanceSettings.user_id == user_id)
    )
    if appearance is None:
        appearance = UserAppearanceSettings(user_id=user_id)
        db.add(appearance)
        await db.commit()
        await db.refresh(appearance)
    return appearance


def _appearance_to_read(appearance: UserAppearanceSettings) -> dict:
    result = AppearanceSettingsRead.model_validate(appearance).model_dump(mode="json")
    if appearance.completion_badge_image_url:
        result["completion_badge_image_url"] = "/api/settings/appearance/badge-image"
    return result


@router.get("/appearance")
async def get_appearance_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the caller's completion-badge appearance preferences."""
    appearance = await get_or_create_appearance_settings(current_user.id, db)
    return _appearance_to_read(appearance)


@router.put("/appearance")
async def update_appearance_settings(
    payload: AppearanceSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Update the caller's completion-badge appearance preferences."""
    appearance = await get_or_create_appearance_settings(current_user.id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(appearance, field, value)
    await db.commit()
    await db.refresh(appearance)
    return _appearance_to_read(appearance)


@router.post("/appearance/badge-image")
async def upload_badge_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Upload a custom completion-badge image (used by the ribbon/corner_badge
    styles instead of the built-in trophy icon)."""
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File must be an image."
        )
    data = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit.",
        )
    try:
        save_badge_image(data, current_user.id)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not save image: {exc}"
        ) from exc

    appearance = await get_or_create_appearance_settings(current_user.id, db)
    appearance.completion_badge_image_url = "set"
    await db.commit()
    await db.refresh(appearance)
    return _appearance_to_read(appearance)


@router.delete("/appearance/badge-image")
async def delete_badge_image_route(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    delete_badge_image(current_user.id)
    appearance = await get_or_create_appearance_settings(current_user.id, db)
    appearance.completion_badge_image_url = None
    await db.commit()
    await db.refresh(appearance)
    return _appearance_to_read(appearance)


@router.get("/appearance/badge-image", response_class=FileResponse)
async def get_badge_image(current_user: User = Depends(get_current_user)) -> FileResponse:
    path = badge_image_path(current_user.id)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No custom badge image uploaded."
        )
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.get("/upload-limits")
async def get_upload_limits() -> dict[str, int]:
    """Read-only — the effective max upload size, set server-wide via
    MAX_UPLOAD_SIZE_MB. Not user-editable from Settings."""
    return {"max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB}


@router.get("/provider-credentials")
async def get_provider_credentials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, dict]:
    """Status for every per-user metadata-provider credential, plus the two
    app-wide-only providers (IGDB, and ScreenScraper's server half) for
    display purposes. Does not re-validate against each provider on every
    call — that would mean a live network round-trip per provider on every
    Settings page load. Save (PUT) is the only place a fresh "connected"
    vs "error" state gets surfaced; this just reports whether credentials
    are present."""
    # non-secret identifiers (never passwords/keys/tokens) are safe to echo
    # back so a field the user already saved shows filled, not blank
    safe_to_display_fields = {"steam_id", "username", "ssid", "client_id"}

    result: dict[str, dict] = {}
    for provider, field_map in PROVIDER_FIELD_MAP.items():
        configured = all(getattr(current_user, column) for _, column, _ in field_map)
        result[provider] = {"status": "configured" if configured else "not_configured"}
        saved_fields = {
            payload_field: getattr(current_user, column)
            for payload_field, column, _ in field_map
            if payload_field in safe_to_display_fields and getattr(current_user, column)
        }
        if saved_fields:
            result[provider]["fields"] = saved_fields
    app_integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
    result["IGDB"] = {
        "status": "configured" if app_integrations.igdb_configured else "not_configured"
    }
    result["TMDB"] = {"status": "configured" if app_integrations.tmdb_api_key else "not_configured"}
    result["OMDb"] = {"status": "configured" if app_integrations.omdb_api_key else "not_configured"}
    result["ScreenScraper"]["app_configured"] = bool(
        settings.SCREENSCRAPER_DEVID and settings.SCREENSCRAPER_DEVPASSWORD
    )

    # library-sync providers also report how much has actually been pulled
    # in — a persistent "N games, last synced ..." beats a toast that
    # disappears the moment you navigate away. `library_games` counts every
    # game currently attributed to that source (however it got there);
    # `last_synced_at` is the real timestamp of the last successful sync
    # run (not derived from Game.updated_at, which unrelated metadata-search
    # edits would also touch and make "last synced" lie).
    sync_timestamp_columns = {
        "Steam": current_user.steam_library_synced_at,
        "RetroAchievements": current_user.retroachievements_library_synced_at,
        "PlayStation": current_user.psn_library_synced_at,
    }
    for provider, last_synced in sync_timestamp_columns.items():
        count = await db.scalar(
            select(func.count(Game.id)).where(
                Game.user_id == current_user.id, Game.source == provider
            )
        )
        result.setdefault(provider, {"status": "not_configured"})
        result[provider]["library_games"] = count
        result[provider]["last_synced_at"] = last_synced

    # display identity — who's actually connected, not just a green dot
    if current_user.steam_persona_name or current_user.steam_avatar_url:
        result["Steam"]["display_name"] = current_user.steam_persona_name
        result["Steam"]["avatar_url"] = current_user.steam_avatar_url
    if current_user.retroachievements_username:
        result["RetroAchievements"]["display_name"] = current_user.retroachievements_username
        result["RetroAchievements"]["avatar_url"] = current_user.retroachievements_avatar_url
    if current_user.psn_online_id:
        result["PlayStation"]["display_name"] = current_user.psn_online_id
        result["PlayStation"]["avatar_url"] = current_user.psn_avatar_url

    return result


@router.put("/provider-credentials/{provider}")
async def save_provider_credentials(
    provider: str,
    payload: ProviderCredentialsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str | None]:
    field_map = PROVIDER_FIELD_MAP.get(provider)
    if field_map is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown provider: {provider}"
        )

    # Steam has two boxes but doesn't care which value lands in which one —
    # a Web API key has a fixed, unambiguous shape (32 hex chars), so if it
    # ended up in the profile-ID box (or vice versa) this just swaps them
    # before anything tries to use them. A blank box means "leave it
    # alone", not "clear it" — saving just one field (e.g. adding the API
    # key in a second pass) must never wipe out the other one that's
    # already saved.
    if provider == "Steam":
        steam_id_input = (payload.fields.get("steam_id") or "").strip()
        api_key_input = (payload.fields.get("api_key") or "").strip()
        if steam_id_input and api_key_input:
            if steam.looks_like_api_key(steam_id_input) and not steam.looks_like_api_key(
                api_key_input
            ):
                steam_id_input, api_key_input = api_key_input, steam_id_input

        if steam_id_input:
            current_user.steam_id = steam_id_input
        if api_key_input:
            current_user.steam_api_key = api_key_input
        await db.commit()

        if not current_user.steam_id or not current_user.steam_api_key:
            missing = "profile ID" if not current_user.steam_id else "API key"
            return {
                "provider": provider,
                "status": "saved",
                "detail": f"Saved: now add your {missing} to connect.",
            }

        try:
            resolved = await asyncio.to_thread(
                steam.resolve_steam_id, current_user.steam_id, current_user.steam_api_key
            )
        except SteamLibraryError as exc:
            return {"provider": provider, "status": "error", "detail": str(exc)}
        if resolved != current_user.steam_id:
            current_user.steam_id = resolved
            await db.commit()

        try:
            result = await asyncio.to_thread(_validate_provider, provider, current_user)
        except _ProviderClientError as exc:
            return {"provider": provider, "status": "error", "detail": str(exc)}
        connected = result.get("validated", True)
        if connected:
            current_user.steam_persona_name = result.get("persona_name")
            current_user.steam_avatar_url = result.get("avatar_url")
            await db.commit()
        return {
            "provider": provider,
            "status": "connected" if connected else "saved",
            "detail": None,
        }

    for payload_field, column, encrypted in field_map:
        value = payload.fields.get(payload_field)
        if value is None:
            continue
        value = value.strip()
        setattr(
            current_user,
            column,
            encrypt_secret(value) if (encrypted and value) else (value or None),
        )
    await db.commit()

    try:
        result = await asyncio.to_thread(_validate_provider, provider, current_user)
    except _ProviderClientError as exc:
        return {"provider": provider, "status": "error", "detail": str(exc)}

    connected = result.get("validated", True)
    if connected and provider == "RetroAchievements":
        current_user.retroachievements_avatar_url = result.get("avatar_url")
        await db.commit()
    return {"provider": provider, "status": "connected" if connected else "saved", "detail": None}


@router.delete("/provider-credentials/{provider}")
async def delete_provider_credentials(
    provider: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    field_map = PROVIDER_FIELD_MAP.get(provider)
    if field_map is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown provider: {provider}"
        )

    for _, column, _ in field_map:
        setattr(current_user, column, None)
    if provider == "Steam":
        current_user.steam_persona_name = None
        current_user.steam_avatar_url = None
    if provider == "RetroAchievements":
        current_user.retroachievements_avatar_url = None
    await db.commit()
    return {"provider": provider, "status": "not_configured"}


class AppIntegrationSettingsRequest(BaseModel):
    igdb_client_id: str | None = None
    igdb_client_secret: str | None = None
    tmdb_api_key: str | None = None
    omdb_api_key: str | None = None
    tvdb_api_key: str | None = None


def _integrations_view(row: AppIntegrationSettings) -> dict:
    """What is in effect (a key saved in Settings, else one from the server's
    environment), never the values themselves. `sources` says which, so the
    screen can tell a key that Settings can override from one it cannot clear."""
    keys = resolve_integrations(row)
    return {
        "igdb_client_id": row.igdb_client_id or keys.igdb_client_id,
        "igdb_configured": keys.igdb_configured,
        "tmdb_configured": bool(keys.tmdb_api_key),
        "omdb_configured": bool(keys.omdb_api_key),
        "tvdb_configured": bool(keys.tvdb_api_key),
        "sources": keys.sources,
    }


@router.get("/app-integrations")
async def get_app_integrations(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict:
    """Deployment-wide (not per-user) integration credentials — admin-only,
    entered through Settings rather than baked into .env, so a self-hosted
    copy of this app never ships with someone else's API keys. The client
    id is safe to echo back (it's not a secret); the client secret never
    is, same rule as every other Fernet-encrypted credential here."""
    del admin
    row = await get_or_create_app_integration_settings(db)
    return _integrations_view(row)


@router.put("/app-integrations")
async def update_app_integrations(
    payload: AppIntegrationSettingsRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict:
    del admin
    row = await get_or_create_app_integration_settings(db)
    updates = payload.model_dump(exclude_unset=True)
    if "igdb_client_id" in updates:
        row.igdb_client_id = updates["igdb_client_id"] or None
    if "igdb_client_secret" in updates:
        row.igdb_client_secret = (
            encrypt_secret(updates["igdb_client_secret"]) if updates["igdb_client_secret"] else None
        )
    if "tmdb_api_key" in updates:
        row.tmdb_api_key = (
            encrypt_secret(updates["tmdb_api_key"]) if updates["tmdb_api_key"] else None
        )
    if "omdb_api_key" in updates:
        row.omdb_api_key = (
            encrypt_secret(updates["omdb_api_key"]) if updates["omdb_api_key"] else None
        )
    if "tvdb_api_key" in updates:
        row.tvdb_api_key = (
            encrypt_secret(updates["tvdb_api_key"]) if updates["tvdb_api_key"] else None
        )
    await db.commit()
    return _integrations_view(row)


@router.delete("/app-integrations")
async def delete_app_integrations(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict:
    del admin
    row = await get_or_create_app_integration_settings(db)
    row.igdb_client_id = None
    row.igdb_client_secret = None
    row.tmdb_api_key = None
    row.omdb_api_key = None
    row.tvdb_api_key = None
    await db.commit()
    return _integrations_view(row)


@router.post("/refresh-media-metadata")
async def refresh_media_metadata(
    mode: str = Query(default="needed", pattern="^(needed|all)$"),
    admin: User = Depends(get_current_admin),
) -> dict:
    """Starts the episode refresh in the background and returns at once with
    its progress (poll /refresh-media-progress). `needed` only touches what
    needs it (airing titles, ones with missing titles or a total that
    disagrees with AniList); `all` checks every title. If a run is already
    going, its progress is returned instead."""
    del admin
    return refresh_job.start(mode)


@router.get("/refresh-media-progress")
async def refresh_media_progress(admin: User = Depends(get_current_admin)) -> dict:
    del admin
    return refresh_job.snapshot()
