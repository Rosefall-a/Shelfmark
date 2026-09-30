from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.routes.settings import get_or_create_app_integration_settings
from src.core.auth import get_current_admin
from src.core.crypto import decrypt_secret, encrypt_secret
from src.core.env_handler import EnvConfigHandler
from src.core.provider_credentials import apply_deployment_provider_credentials
from src.database.models.oidc_settings import OidcSettings
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(
    prefix="/api/settings/deployment", tags=["settings"], dependencies=[Depends(get_current_admin)]
)


class OidcProviderRequest(BaseModel):
    name: str
    slug: str
    issuer_url: str
    client_id: str
    client_secret: str | None = None
    scopes: str = "openid profile email"
    redirect_uri: str | None = None
    groups_claim: str = "groups"
    admin_group: str | None = None
    user_match_field: str = "email"
    allow_new_users: bool = True
    button_text: str = "Continue with SSO"
    button_image_url: str | None = None
    enabled: bool = True


class DeploymentSettingsRequest(BaseModel):
    steamgriddb_api_key: str | None = None
    retroachievements_api_key: str | None = None
    giantbomb_api_key: str | None = None
    igdb_client_id: str | None = None
    igdb_client_secret: str | None = None
    screenscraper_ssid: str | None = None
    screenscraper_sspassword: str | None = None
    screenscraper_devid: str | None = None
    screenscraper_devpassword: str | None = None
    xbox_client_id: str | None = None
    xbox_client_secret: str | None = None
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_scopes: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_groups_claim: str | None = None
    oidc_admin_group: str | None = None
    oidc_user_match_field: str | None = None
    oidc_enabled: bool | None = None
    oidc_default_login_method: str | None = None
    oidc_login_button_text: str | None = None
    oidc_allow_new_users: bool | None = None
    oidc_providers_json: str | None = None


_SECRET_FIELDS = {
    "steamgriddb_api_key",
    "retroachievements_api_key",
    "giantbomb_api_key",
    "igdb_client_secret",
    "screenscraper_sspassword",
    "screenscraper_devpassword",
    "xbox_client_secret",
}
_SAFE_PROVIDER_FIELDS = {
    "igdb_client_id",
    "screenscraper_ssid",
    "screenscraper_devid",
    "xbox_client_id",
}

_PROVIDER_ENV_NAMES = {
    "steamgriddb_api_key": "STEAMGRIDDB_API_KEY",
    "retroachievements_api_key": "RETROACHIEVEMENTS_API_KEY",
    "giantbomb_api_key": "GIANTBOMB_API_KEY",
    "igdb_client_id": "IGDB_CLIENT_ID",
    "igdb_client_secret": "IGDB_CLIENT_SECRET",
    "screenscraper_ssid": "SCREENSCRAPER_SSID",
    "screenscraper_sspassword": "SCREENSCRAPER_SSPASSWORD",
    "screenscraper_devid": "SCREENSCRAPER_DEVID",
    "screenscraper_devpassword": "SCREENSCRAPER_DEVPASSWORD",
    "xbox_client_id": "XBOX_CLIENT_ID",
    "xbox_client_secret": "XBOX_CLIENT_SECRET",
}

_OIDC_ENV_NAMES = {
    "issuer_url": "OIDC_ISSUER_URL",
    "client_id": "OIDC_CLIENT_ID",
    "client_secret": "OIDC_CLIENT_SECRET",
    "scopes": "OIDC_SCOPES",
    "redirect_uri": "OIDC_REDIRECT_URI",
    "groups_claim": "OIDC_GROUPS_CLAIM",
    "admin_group": "OIDC_ADMIN_GROUP",
    "user_match_field": "OIDC_USER_MATCH_FIELD",
}

_OIDC_ENV_LOCKED_FIELDS = {
    "oidc_issuer_url",
    "oidc_client_id",
    "oidc_client_secret",
    "oidc_scopes",
    "oidc_redirect_uri",
    "oidc_groups_claim",
    "oidc_admin_group",
    "oidc_user_match_field",
    "oidc_allow_new_users",
    "oidc_enabled",
}


async def _oidc_row(db):
    row = await db.scalar(select(OidcSettings).limit(1))
    if row is None:
        row = OidcSettings()
        db.add(row)
        await db.flush()
    return row


def _provider_view(raw):
    item = dict(raw)
    secret = item.pop("client_secret", "")
    item["client_secret_configured"] = bool(secret)
    return item


def _provider_rows(row):
    try:
        data = json.loads(row.providers_json or "[]")
    except (TypeError, ValueError):
        data = []
    return [p for p in data if isinstance(p, dict) and p.get("enabled", True) and p.get("slug")]


async def get_deployment_settings(db: AsyncSession, admin: User) -> dict:
    del admin
    app = await get_or_create_app_integration_settings(db)
    oidc = await _oidc_row(db)
    handler = EnvConfigHandler()
    provider_locks = {
        field: handler.has(env_name)
        for field, env_name in _PROVIDER_ENV_NAMES.items()
    }
    providers = {
        field: None if provider_locks[field] else getattr(app, field)
        for field in _SAFE_PROVIDER_FIELDS
    }
    for field in _SECRET_FIELDS:
        providers[field + "_configured"] = bool(getattr(app, field)) or provider_locks[field]
    oidc_locks = {
        field: handler.has(env_name)
        for field, env_name in _OIDC_ENV_NAMES.items()
    }
    named = [_provider_view(p) for p in _provider_rows(oidc)]
    return {
        "providers": providers,
        "provider_locks": provider_locks,
        "oidc": {

            "issuer_url": None if oidc_locks["issuer_url"] else oidc.issuer_url,
            "client_id": None if oidc_locks["client_id"] else oidc.client_id,
            "scopes": None if oidc_locks["scopes"] else oidc.scopes,
            "redirect_uri": None if oidc_locks["redirect_uri"] else oidc.redirect_uri,
            "groups_claim": None if oidc_locks["groups_claim"] else oidc.groups_claim,
            "admin_group": None if oidc_locks["admin_group"] else oidc.admin_group,
            "user_match_field": None if oidc_locks["user_match_field"] else (oidc.user_match_field or "email"),
            "enabled": oidc.enabled,
            "default_login_method": oidc.default_login_method
            if oidc.default_login_method in {"local", "sso"}
            else "local",
            "login_button_text": oidc.login_button_text.strip() or "Continue with SSO",
            "allow_new_users": oidc.allow_new_users,
            "client_secret_configured": bool(oidc.client_secret),
            "named_providers": named,
            "locked_fields": {
                **{f"oidc_{name}": locked for name, locked in oidc_locks.items()},
                "oidc_allow_new_users": handler.has("OIDC_ISSUER_URL"),
                "oidc_enabled": False,
            },
        },
    }


@router.get("")
async def read_deployment_settings(
    db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)
) -> dict:
    return await get_deployment_settings(db, admin)


@router.put("")
async def update_deployment_settings(
    payload: DeploymentSettingsRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict:
    app = await get_or_create_app_integration_settings(db)
    oidc = await _oidc_row(db)
    handler = EnvConfigHandler()
    provider_locks = {
        field: handler.has(env_name)
        for field, env_name in _PROVIDER_ENV_NAMES.items()
    }
    locked_fields = {
        f"oidc_{name}": handler.has(env_name)
        for name, env_name in _OIDC_ENV_NAMES.items()
    }
    locked_fields["oidc_allow_new_users"] = handler.has("OIDC_ISSUER_URL")
    locked_fields["oidc_enabled"] = False
    effective_oidc_enabled = bool(oidc.enabled)
    if payload.oidc_enabled is not None:
        effective_oidc_enabled = bool(payload.oidc_enabled)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if provider_locks.get(field) or field in _OIDC_ENV_LOCKED_FIELDS and locked_fields.get(field):
            raise HTTPException(409, f"{field} is managed by the deployment environment and cannot be changed here.")
        if field == "oidc_providers_json":
            try:
                incoming = json.loads(value or "[]")
            except ValueError as exc:
                raise HTTPException(400, "Invalid OIDC provider configuration JSON.") from exc
            if not isinstance(incoming, list) or len(incoming) > 20:
                raise HTTPException(400, "OIDC provider list must contain 0–20 providers.")
            existing = {p.get("slug"): p for p in _provider_rows(oidc)}
            normalized = []
            slugs = set()
            for item in incoming:
                if not isinstance(item, dict):
                    raise HTTPException(400, "Invalid OIDC provider entry.")
                slug = str(item.get("slug", "")).strip().lower()
                name = str(item.get("name", "")).strip()
                issuer = str(item.get("issuer_url", "")).strip()
                client_id = str(item.get("client_id", "")).strip()
                if (
                    not slug
                    or not name
                    or (effective_oidc_enabled and (not issuer or not client_id))
                    or slug in slugs
                    or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in slug)
                ):
                    raise HTTPException(
                        400, "Each OIDC provider needs a unique name, slug, issuer and client ID."
                    )
                if item.get("user_match_field", "email") not in {"email", "username"}:
                    raise HTTPException(400, "OIDC user matching must be email or username.")
                secret = item.get("client_secret") or existing.get(slug, {}).get("client_secret")
                if not secret and effective_oidc_enabled:
                    raise HTTPException(
                        400, f"Client secret is required for OIDC provider '{name}' while OIDC is enabled."
                    )
                if item.get("client_secret"):
                    secret = encrypt_secret(str(item["client_secret"]))
                normalized.append(
                    {
                        **item,
                        "slug": slug,
                        "name": name,
                        "issuer_url": issuer,
                        "client_id": client_id,
                        "client_secret": secret,
                        "enabled": bool(item.get("enabled", True)),
                    }
                )
                slugs.add(slug)
            if effective_oidc_enabled:
                incomplete = [
                    item["name"]
                    for item in normalized
                    if not item["issuer_url"] or not item["client_id"] or not item["client_secret"]
                ]
                if incomplete:
                    raise HTTPException(
                        400,
                        "OIDC is enabled, so every enabled provider must have an issuer, client ID, and client secret: "
                        + ", ".join(incomplete),
                    )
            oidc.providers_json = json.dumps(normalized)
        elif field.startswith("oidc_"):
            if field == "oidc_enabled":
                oidc.enabled = bool(value)
            elif field == "oidc_client_secret":
                if value:
                    oidc.client_secret = encrypt_secret(value)
            elif field == "oidc_user_match_field":
                if value not in {"email", "username"}:
                    raise HTTPException(400, "OIDC user matching must be email or username.")
                oidc.user_match_field = value
            elif field == "oidc_default_login_method":
                if value not in {"local", "sso"}:
                    raise HTTPException(400, "Default login method must be local or sso.")
                oidc.default_login_method = value
            elif field == "oidc_login_button_text":
                text = (value or "").strip()
                if not text or len(text) > 100:
                    raise HTTPException(400, "SSO button text must be 1–100 characters.")
                oidc.login_button_text = text
            elif field == "oidc_allow_new_users":
                oidc.allow_new_users = bool(value)
            elif value is not None:
                setattr(oidc, field.removeprefix("oidc_"), value or None)
        elif field in _SECRET_FIELDS:
            if value:
                setattr(app, field, encrypt_secret(value))
        elif field in _SAFE_PROVIDER_FIELDS:
            setattr(app, field, value or None)
    await db.commit()
    apply_deployment_provider_credentials(app)
    return await get_deployment_settings(db, admin)
