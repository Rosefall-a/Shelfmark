from __future__ import annotations

import json
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    get_current_admin,
    hash_password,
    hash_token,
    validate_password,
)
from src.core.config import settings
from src.core.crypto import encrypt_secret
from src.core.env_handler import EnvConfigHandler
from src.core.provider_credentials import apply_deployment_provider_credentials
from src.core.config_registry import CONFIG_REGISTRY
from src.database.models.app_integration_settings import AppIntegrationSettings
from src.database.models.auth import UserSession
from src.database.models.game import Game
from src.database.models.oidc_settings import OidcSettings
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupRequest(BaseModel):
    username: str = ""
    email: str = ""
    password: str = ""
    sections: list[str] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)

    # Kept for compatibility with older setup clients. New clients submit the
    # registry-driven configuration object instead.
    oidc_name: str | None = None
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_scopes: str = "openid profile email"
    oidc_redirect_uri: str | None = None
    oidc_groups_claim: str = "groups"
    oidc_admin_group: str | None = None
    oidc_user_match_field: str = "email"
    oidc_allow_new_users: bool = True
    oidc_button_text: str = "Continue with SSO"
    oidc_default_login_method: str = "local"

    @field_validator("password")
    @classmethod
    def validate_setup_password(cls, value: str) -> str:
        return validate_password(value) if value else value


async def _app_row(db: AsyncSession) -> AppIntegrationSettings:
    from src.api.routes.settings import get_or_create_app_integration_settings

    return await get_or_create_app_integration_settings(db)


async def _oidc_row(db: AsyncSession) -> OidcSettings:
    row = await db.scalar(select(OidcSettings).limit(1))
    if row is None:
        row = OidcSettings()
        db.add(row)
        await db.flush()
    return row


def _persisted_values(app: AppIntegrationSettings, oidc: OidcSettings) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for spec_name, attribute in {
        "STEAMGRIDDB_API_KEY": "steamgriddb_api_key",
        "RETROACHIEVEMENTS_API_KEY": "retroachievements_api_key",
        "GIANTBOMB_API_KEY": "giantbomb_api_key",
        "IGDB_CLIENT_ID": "igdb_client_id",
        "IGDB_CLIENT_SECRET": "igdb_client_secret",
        "TMDB_API_KEY": "tmdb_api_key",
        "OMDB_API_KEY": "omdb_api_key",
        "TVDB_API_KEY": "tvdb_api_key",
        "SCREENSCRAPER_DEVID": "screenscraper_devid",
        "SCREENSCRAPER_DEVPASSWORD": "screenscraper_devpassword",
        "SCREENSCRAPER_SSID": "screenscraper_ssid",
        "SCREENSCRAPER_SSPASSWORD": "screenscraper_sspassword",
        "XBOX_CLIENT_ID": "xbox_client_id",
        "XBOX_CLIENT_SECRET": "xbox_client_secret",
    }.items():
        value = getattr(app, attribute)
        if value:
            values[f"{spec_name}__configured"] = True
            if spec_name in {"IGDB_CLIENT_ID", "SCREENSCRAPER_DEVID", "SCREENSCRAPER_SSID", "XBOX_CLIENT_ID"}:
                values[spec_name] = value

    provider_name = "Provider 1"
    provider_slug = "provider-1"
    try:
        providers = json.loads(oidc.providers_json or "[]")
        if providers and isinstance(providers[0], dict):
            provider_name = str(providers[0].get("name") or provider_name)
            provider_slug = str(providers[0].get("slug") or provider_slug)
    except (TypeError, ValueError):
        pass
    values.update({
        "OIDC_PROVIDER_NAME": provider_name,
        "OIDC_PROVIDER_SLUG": provider_slug,
        "OIDC_ISSUER_URL": oidc.issuer_url,
        "OIDC_CLIENT_ID": oidc.client_id,
        "OIDC_CLIENT_SECRET__configured": bool(oidc.client_secret),
        "OIDC_REDIRECT_URI": oidc.redirect_uri,
        "OIDC_SCOPES": oidc.scopes,
        "OIDC_GROUPS_CLAIM": oidc.groups_claim,
        "OIDC_ADMIN_GROUP": oidc.admin_group,
        "OIDC_USER_MATCH_FIELD": oidc.user_match_field,
        "OIDC_ALLOW_NEW_USERS": oidc.allow_new_users,
        "OIDC_DEFAULT_LOGIN_METHOD": oidc.default_login_method,
        "OIDC_LOGIN_BUTTON_TEXT": oidc.login_button_text,
    })
    return values


async def _configuration(db: AsyncSession, request: Request) -> dict[str, Any]:
    app = await _app_row(db)
    oidc = await _oidc_row(db)
    handler = EnvConfigHandler()
    redirect_uri = str(request.url_for("oidc_callback"))
    return {
        "sections": handler.setup_schema(
            _persisted_values(app, oidc),
            generated_values={"OIDC_REDIRECT_URI": redirect_uri},
        ),
        "startup_mode": handler.mode.value,
        "startup_ui_enabled": handler.startup_ui_enabled(),
    }


async def _save_configuration(
    db: AsyncSession,
    values: dict[str, Any],
    selected_sections: set[str],
    generated_redirect_uri: str,
) -> None:
    """Persist only fields owned by the setup registry.

    Environment-owned values are deliberately ignored here: the environment
    remains authoritative even when a malicious/old client sends them.
    """
    app = await _app_row(db)
    oidc = await _oidc_row(db)
    handler = EnvConfigHandler()

    app_fields = {
        "STEAMGRIDDB_API_KEY": "steamgriddb_api_key",
        "RETROACHIEVEMENTS_API_KEY": "retroachievements_api_key",
        "GIANTBOMB_API_KEY": "giantbomb_api_key",
        "IGDB_CLIENT_ID": "igdb_client_id",
        "IGDB_CLIENT_SECRET": "igdb_client_secret",
        "TMDB_API_KEY": "tmdb_api_key",
        "OMDB_API_KEY": "omdb_api_key",
        "TVDB_API_KEY": "tvdb_api_key",
        "SCREENSCRAPER_DEVID": "screenscraper_devid",
        "SCREENSCRAPER_DEVPASSWORD": "screenscraper_devpassword",
        "SCREENSCRAPER_SSID": "screenscraper_ssid",
        "SCREENSCRAPER_SSPASSWORD": "screenscraper_sspassword",
        "XBOX_CLIENT_ID": "xbox_client_id",
        "XBOX_CLIENT_SECRET": "xbox_client_secret",
    }
    for name, attribute in app_fields.items():
        if name not in values or handler.has(name):
            continue
        value = values[name]
        if value in (None, ""):
            continue
        spec = next(spec for spec in CONFIG_REGISTRY if spec.name == name)
        setattr(app, attribute, encrypt_secret(str(value)) if spec.secret else str(value))

    oidc_env_complete = all(
        handler.has(name)
        for name in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
    )
    oidc_selected = "oidc" in selected_sections

    # OIDC is optional during first-run setup. Do not enable it merely because
    # an OIDC row exists (the row is created while building the setup schema).
    # Environment configuration is only considered OIDC configuration when all
    # three required provider credentials are supplied.
    if not oidc_selected and not oidc_env_complete:
        oidc.enabled = False
        return

    oidc.redirect_uri = generated_redirect_uri
    oidc_fields = {
        "OIDC_ISSUER_URL": "issuer_url",
        "OIDC_CLIENT_ID": "client_id",
        "OIDC_SCOPES": "scopes",
        "OIDC_GROUPS_CLAIM": "groups_claim",
        "OIDC_ADMIN_GROUP": "admin_group",
        "OIDC_USER_MATCH_FIELD": "user_match_field",
        "OIDC_ALLOW_NEW_USERS": "allow_new_users",
        "OIDC_DEFAULT_LOGIN_METHOD": "default_login_method",
        "OIDC_LOGIN_BUTTON_TEXT": "login_button_text",
    }
    for name, attribute in oidc_fields.items():
        if handler.has(name):
            # Environment overrides remain authoritative, but mirror them into
            # the OIDC row so status/settings recognise a complete provider.
            value = handler.get(name)
        elif name in values:
            value = values[name]
        else:
            continue
        if value is None or value == "":
            continue
        setattr(oidc, attribute, value)
    if handler.has("OIDC_CLIENT_SECRET"):
        oidc.client_secret = encrypt_secret(str(handler.get("OIDC_CLIENT_SECRET")))
    elif "OIDC_CLIENT_SECRET" in values and values["OIDC_CLIENT_SECRET"]:
        oidc.client_secret = encrypt_secret(str(values["OIDC_CLIENT_SECRET"]))

    missing = [
        name
        for name, value in (
            ("OIDC_ISSUER_URL", oidc.issuer_url),
            ("OIDC_CLIENT_ID", oidc.client_id),
            ("OIDC_CLIENT_SECRET", oidc.client_secret),
        )
        if not value
    ]
    if missing:
        raise HTTPException(400, "OIDC requires an issuer URL, client ID, and client secret when enabled.")

    # A provider is only enabled after all required credentials have been
    # resolved. This prevents an empty setup OIDC row from being treated as
    # enabled.
    oidc.enabled = True

    # Register the initial/default provider in the same provider format used by
    # the OIDC settings UI. This makes an OIDC configuration supplied during
    # first-run setup visible to the normal OIDC status/login endpoints.
    try:
        providers = json.loads(oidc.providers_json or "[]")
    except (TypeError, ValueError):
        providers = []
    providers = [
        item for item in providers
        if isinstance(item, dict)
        and item.get("slug") != (values.get("OIDC_PROVIDER_SLUG") or "provider-1")
    ]
    providers.insert(0, {
        "name": values.get("OIDC_PROVIDER_NAME") or "Provider 1",
        "slug": values.get("OIDC_PROVIDER_SLUG") or "provider-1",
        "issuer_url": oidc.issuer_url,
        "client_id": oidc.client_id,
        "client_secret": oidc.client_secret,
        "scopes": oidc.scopes or "openid profile email",
        "groups_claim": oidc.groups_claim or "groups",
        "admin_group": oidc.admin_group,
        "user_match_field": oidc.user_match_field or "email",
        "allow_new_users": oidc.allow_new_users,
        "button_text": oidc.login_button_text or "Continue with SSO",
        "enabled": True,
        "show_on_login": True,
        "autostart_enabled": True,
    })
    oidc.providers_json = json.dumps(providers)


@router.get("/configuration")
async def setup_configuration(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    return await _configuration(db, request)


@router.get("/status")
async def setup_status(db: AsyncSession = Depends(get_db)) -> dict[str, bool | str]:
    has_user = await db.scalar(select(User.id).limit(1)) is not None
    handler = EnvConfigHandler()
    return {
        "setup_required": not has_user,
        "startup_mode": handler.mode.value,
        "startup_ui_enabled": handler.startup_ui_enabled(),
    }


@router.put("/configuration")
async def update_setup_configuration(
    payload: SetupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict[str, object]:
    del admin
    selected = set(payload.sections)
    await _save_configuration(db, payload.configuration, selected, str(request.url_for("oidc_callback")))
    await db.commit()
    apply_deployment_provider_credentials(await _app_row(db))
    return await _configuration(db, request)


@router.post("", status_code=status.HTTP_201_CREATED)
async def setup_admin(
    payload: SetupRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | bool]:
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('unnamed_tracking_app_setup'))"))

    if await db.scalar(select(User.id).limit(1)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup is already complete.")

    handler = EnvConfigHandler()
    values = dict(payload.configuration)

    # The browser only submits editable fields. Deployment values therefore
    # come directly from EnvConfigHandler and cannot be replaced by the UI.
    admin_values = handler.bootstrap_primary_user()
    username = (payload.username or values.get("PRIMARY_USER_USERNAME") or admin_values["username"]).strip()
    email = (payload.email or values.get("PRIMARY_USER_EMAIL") or admin_values["email"]).strip().lower()
    password = payload.password or values.get("PRIMARY_USER_PASSWORD") or admin_values["password"]

    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="Username, email, and password are required.")

    # OIDC is optional as a section. Selecting it means it is being configured
    # and will enable OIDC after complete provider credentials are saved.
    selected = set(payload.sections)
    oidc_env_complete = all(
        handler.has(name)
        for name in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
    )
    if oidc_env_complete:
        selected.add("oidc")

    await _save_configuration(db, values, selected, str(request.url_for("oidc_callback")))
    await db.flush()
    apply_deployment_provider_credentials(await _app_row(db))

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        is_admin=True,
    )
    db.add(user)
    try:
        await db.flush()
        await db.execute(update(Game).where(Game.user_id.is_(None)).values(user_id=user.id))

        session_token = secrets.token_urlsafe(32)
        db.add(
            UserSession(
                user_id=user.id,
                token_hash=hash_token(session_token),
                expires_at=int(time.time()) + SESSION_TTL_SECONDS,
            )
        )
        await db.commit()
        await db.refresh(user)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already exists.") from exc

    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.AUTH_COOKIE_SECURE,
    )
    return {"status": "setup_complete", "user_id": str(user.id), "is_admin": True}
