from __future__ import annotations

import json
import logging
import secrets
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import RedirectResponse

from src.core.auth import SESSION_COOKIE, SESSION_TTL_SECONDS, hash_password, hash_token
from src.core.config import settings
from src.core.crypto import decrypt_secret
from src.core.oidc import OidcConfig, begin_oidc, oauth, register_oidc_provider
from src.database.models.auth import UserSession
from src.database.models.oidc_settings import OidcSettings
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(prefix="/api/auth/oidc", tags=["auth"])
logger = logging.getLogger(__name__)


def _env_config(request: Request):
    if not (settings.OIDC_ISSUER_URL and settings.OIDC_CLIENT_ID and settings.OIDC_CLIENT_SECRET):
        return None
    issuer = settings.OIDC_ISSUER_URL.strip()
    return OidcConfig(
        issuer_url=issuer,
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        scopes=settings.OIDC_SCOPES,
        redirect_uri=str(request.url_for("oidc_callback")),
        groups_claim=settings.OIDC_GROUPS_CLAIM,
        admin_group=settings.OIDC_ADMIN_GROUP,
        user_match_field=getattr(settings, "OIDC_USER_MATCH_FIELD", "email"),
        discovery_url=issuer if issuer.endswith("/.well-known/openid-configuration") else None,
    )


def _named_rows(row):
    try:
        data = json.loads(row.providers_json or "[]")
    except (TypeError, ValueError):
        return []
    return [
        provider
        for provider in data
        if isinstance(provider, dict) and provider.get("slug") and provider.get("enabled", True)
    ]


def _config_from_provider(provider, redirect_uri: str):
    issuer = str(provider["issuer_url"]).strip()
    return OidcConfig(
        issuer_url=issuer,
        client_id=str(provider["client_id"]),
        client_secret=decrypt_secret(str(provider["client_secret"])),
        scopes=provider.get("scopes") or "openid profile email",
        redirect_uri=redirect_uri,
        groups_claim=provider.get("groups_claim") or "groups",
        admin_group=provider.get("admin_group") or None,
        user_match_field=provider.get("user_match_field") or "email",
        allow_new_users=bool(provider.get("allow_new_users", True)),
        discovery_url=issuer if issuer.endswith("/.well-known/openid-configuration") else None,
        name=provider.get("name") or provider["slug"],
        slug=provider["slug"],
        button_text=provider.get("button_text") or "Continue with SSO",
        button_image_url=provider.get("button_image_url"),
    )


async def _get_config(db, request: Request, slug="default", require_autostart=False):
    row = await db.scalar(select(OidcSettings).limit(1))
    if row and not row.enabled:
        return None
    if row and slug != "default":
        for provider in _named_rows(row):
            if provider.get("slug") == slug and provider.get("client_secret"):
                if require_autostart and provider.get("autostart_enabled", True) is False:
                    return None
                return _config_from_provider(provider, str(request.url_for("oidc_callback_provider", provider_slug=slug)))
        return None

    environment_config = _env_config(request)
    if environment_config is not None:
        return environment_config

    if row and row.issuer_url and row.client_id and row.client_secret:
        issuer = row.issuer_url.strip()
        return OidcConfig(
            issuer_url=issuer,
            client_id=row.client_id,
            client_secret=decrypt_secret(row.client_secret),
            scopes=row.scopes or "openid profile email",
            redirect_uri=str(request.url_for("oidc_callback")),
            groups_claim=row.groups_claim or "groups",
            admin_group=row.admin_group,
            user_match_field=row.user_match_field or "email",
            allow_new_users=row.allow_new_users,
        )
    return _env_config(request) if slug == "default" else None


@router.get("/status")
async def oidc_status(request: Request, db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(OidcSettings).limit(1))
    config = await _get_config(db, request)
    providers = []
    oidc_master_enabled = row.enabled if row is not None else config is not None
    if row and oidc_master_enabled:
        for provider in _named_rows(row):
            if provider.get("show_on_login", True) is False:
                continue
            providers.append(
                {
                    "name": provider.get("name", provider["slug"]),
                    "slug": provider["slug"],
                    "button_text": provider.get("button_text") or "Continue with SSO",
                    "button_image_url": provider.get("button_image_url"),
                }
            )
    if not providers and config:
        providers = [
            {
                "name": config.name,
                "slug": "default",
                "button_text": (
                    row.login_button_text.strip()
                    if row and row.login_button_text.strip()
                    else config.button_text
                ),
                "button_image_url": config.button_image_url,
            }
        ]
    return {
        "enabled": oidc_master_enabled and (config is not None or bool(providers)),
        "issuer": urlparse(config.issuer_url).hostname if config else None,
        "default_login_method": (
            row.default_login_method
            if row and row.default_login_method in {"local", "sso"}
            else "local"
        ),
        "login_button_text": (
            row.login_button_text.strip()
            if row and row.login_button_text.strip()
            else "Continue with SSO"
        ),
        "providers": providers,
    }


@router.get("/login", name="oidc_login")
async def oidc_login(request: Request, db: AsyncSession = Depends(get_db)):
    config = await _get_config(db, request)
    if config is None:
        raise HTTPException(404, "OIDC login is not configured.")
    return await begin_oidc(request, config)


@router.get("/login/{provider_slug}")
async def oidc_provider_login(
    provider_slug: str, request: Request, db: AsyncSession = Depends(get_db)
):
    config = await _get_config(db, request, provider_slug, require_autostart=True)
    if config is None:
        raise HTTPException(404, "OIDC provider autostart is not enabled.")
    return await begin_oidc(request, config)


async def _fetch_oidc_token(request, client):
    params = {
        "code": request.query_params.get("code"),
        "state": request.query_params.get("state"),
    }
    state = params["state"]
    if not state:
        raise ValueError("Missing OIDC state parameter")
    state_data = await client.framework.get_state_data(request.session, state)
    if not state_data:
        raise ValueError("Invalid OIDC state parameter")
    await client.framework.clear_state_data(request.session, state)
    params = client._format_state_params(state_data, params)
    token = await client.fetch_access_token(**params)
    if "id_token" not in token or "nonce" not in state_data:
        return token
    try:
        token["userinfo"] = await client.parse_id_token(
            token, nonce=state_data["nonce"], claims_options=None
        )
    except ValueError as exc:
        if str(exc) != "Invalid key set format":
            raise
        logger.warning("OIDC provider returned an invalid JWKS document; using UserInfo endpoint")
        token["userinfo"] = await client.userinfo(token=token)
    return token


def _groups(claims, name):
    value = claims.get(name)
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if str(item).strip()}
    return set()


def _match_value(claims, field, email):
    if field == "username":
        return str(claims.get("preferred_username") or claims.get("name") or "").strip()
    return email


def _safe_username(value, email):
    username = "".join(char for char in value.strip() if char.isalnum() or char in "._-")[:100]
    return username or email.split("@", 1)[0][:90] or f"user-{secrets.token_hex(4)}"


async def _complete_callback(request, db, config, client_name):
    register_oidc_provider(config, client_name)
    client = oauth.create_client(client_name)
    if client is None:
        return RedirectResponse("/login?oidc_error=provider_unavailable", 303)
    try:
        token = await _fetch_oidc_token(request, client)
        claims = dict(token.get("userinfo") or await client.userinfo(token=token))
        claims.update({key: value for key, value in token.items() if key not in claims})
    except Exception:
        logger.exception("OIDC callback token/userinfo exchange failed")
        return RedirectResponse("/login?oidc_error=authentication_failed", 303)

    subject = str(claims.get("sub", "")).strip()
    email = str(claims.get("email", "")).strip().lower()
    if not subject or not email:
        return RedirectResponse("/login?oidc_error=identity_missing", 303)

    field = config.user_match_field if config.user_match_field in {"email", "username"} else "email"
    match = _match_value(claims, field, email)
    if not match:
        return RedirectResponse("/login?oidc_error=identity_missing", 303)

    linked_subject = f"{config.slug}:{subject}"
    user = await db.scalar(select(User).where(User.oidc_subject == linked_subject))
    if user is None:
        if field == "username":
            user = await db.scalar(select(User).where(User.username == match))
        else:
            user = await db.scalar(select(User).where(User.email == email))

    is_admin = bool(
        config.admin_group and config.admin_group in _groups(claims, config.groups_claim)
    )
    if user is None:
        if not config.allow_new_users:
            return RedirectResponse("/login?oidc_error=user_creation_disabled", 303)
        username = _safe_username(
            str(claims.get("preferred_username") or claims.get("name") or ""), email
        )
        base = username
        suffix = 1
        while await db.scalar(select(User.id).where(User.username == username)) is not None:
            suffix += 1
            username = f"{base[: 100 - len(str(suffix)) - 1]}-{suffix}"
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(48) + "A!a"),
            is_active=True,
            is_admin=is_admin,
            oidc_subject=linked_subject,
        )
        db.add(user)
        await db.flush()
    else:
        if not user.is_active:
            return RedirectResponse("/login?oidc_error=account_disabled", 303)
        if user.oidc_subject and user.oidc_subject not in {linked_subject, subject}:
            return RedirectResponse("/login?oidc_error=identity_conflict", 303)
        user.oidc_subject = linked_subject
        user.email = email
        if config.admin_group:
            user.is_admin = is_admin

    session_token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(session_token),
            expires_at=int(time.time()) + SESSION_TTL_SECONDS,
        )
    )
    await db.commit()
    response = RedirectResponse("/login?oidc=success", 303)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.AUTH_COOKIE_SECURE,
        path="/",
    )
    return response


@router.get("/callback", name="oidc_callback")
async def oidc_callback(request: Request, db: AsyncSession = Depends(get_db)):
    config = await _get_config(db, request)
    if config is None:
        return RedirectResponse("/login?oidc_error=not_configured", 303)
    return await _complete_callback(request, db, config, "oidc")


@router.get("/callback/{provider_slug}", name="oidc_callback_provider")
async def oidc_callback_provider(
    provider_slug: str, request: Request, db: AsyncSession = Depends(get_db)
):
    config = await _get_config(db, request, provider_slug)
    if config is None:
        return RedirectResponse("/login?oidc_error=not_configured", 303)
    return await _complete_callback(request, db, config, f"oidc_{provider_slug}")
