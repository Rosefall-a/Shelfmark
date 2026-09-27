from __future__ import annotations

import asyncio
import secrets
import shutil
import time
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    create_api_key,
    get_current_admin,
    get_current_user,
    hash_password,
    hash_token,
    password_policy,
    revoke_session,
    set_password_policy_override,
    validate_password,
    verify_password,
)
from src.core.config import settings
from src.core.crypto import encrypt_secret
from src.database.models.auth import UserApiKey, UserSession
from src.database.models.user import User
from src.database.models.app_integration_settings import AppIntegrationSettings
from src.database.session import get_db
from src.features.metadata.games.psn import PSNClient, PSNError

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username_or_email: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=list)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)
    is_admin: bool = False

    @field_validator("password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password(value)


class UserAdminUpdateRequest(BaseModel):
    is_admin: bool


class PsnConnectRequest(BaseModel):
    npsso_token: str = Field(min_length=1)


class UserProfileUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    # only required when actually setting a new password — everything else
    # here (username/email/steamgriddb key) doesn't need it
    current_password: str | None = Field(default=None, min_length=1)
    new_password: str | None = Field(default=None, min_length=1)
    steamgriddb_api_key: str | None = Field(default=None, max_length=64)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str | None) -> str | None:
        return validate_password(value) if value is not None else None



@router.get("/password-policy")
async def get_password_policy() -> dict[str, int | bool]:
    """Return the effective local-password policy without exposing secrets."""
    return password_policy()


class PasswordPolicyUpdate(BaseModel):
    min_length: int = Field(ge=1, le=1024)
    require_uppercase: bool
    require_lowercase: bool
    require_digit: bool
    require_symbol: bool


@router.put("/password-policy")
async def update_password_policy(
    payload: PasswordPolicyUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int | bool]:
    del admin
    from src.core.env_handler import EnvConfigHandler

    handler = EnvConfigHandler()
    if any(handler.has(name) for name in (
        "PASSWORD_MIN_LENGTH",
        "PASSWORD_REQUIRE_UPPERCASE",
        "PASSWORD_REQUIRE_LOWERCASE",
        "PASSWORD_REQUIRE_DIGIT",
        "PASSWORD_REQUIRE_SYMBOL",
    )):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Password policy is managed by the deployment environment and cannot be changed here.",
        )

    row = await db.scalar(select(AppIntegrationSettings).limit(1))
    if row is None:
        row = AppIntegrationSettings()
        db.add(row)
        await db.flush()

    policy = payload.model_dump()
    row.password_min_length = policy["min_length"]
    row.password_require_uppercase = policy["require_uppercase"]
    row.password_require_lowercase = policy["require_lowercase"]
    row.password_require_digit = policy["require_digit"]
    row.password_require_symbol = policy["require_symbol"]
    await db.commit()
    set_password_policy_override(policy)
    return policy


@router.post("/login")
async def login(
    payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    identifier = payload.username_or_email.strip()
    user = await db.scalar(
        select(User).where((User.username == identifier) | (User.email == identifier.lower()))
    )
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    session_token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(session_token),
            expires_at=int(time.time()) + SESSION_TTL_SECONDS,
        )
    )
    await db.commit()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.AUTH_COOKIE_SECURE,
    )
    return {"status": "logged_in", "user_id": str(user.id)}


@router.post("/logout")
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, str]:
    if session_token:
        await revoke_session(db, session_token)
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "logged_out"}


@router.get("/me")
async def current_user(user: User = Depends(get_current_user)) -> dict[str, str | bool | None]:
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "steamgriddb_api_key": user.steamgriddb_api_key,
    }


@router.patch("/me")
async def update_current_user(
    payload: UserProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | bool | None]:
    if payload.new_password is not None:
        if not payload.current_password or not verify_password(
            payload.current_password, user.password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is required to set a new password.",
            )

    if payload.username is not None:
        user.username = payload.username.strip()
    if payload.email is not None:
        user.email = payload.email.strip().lower()
    if payload.new_password is not None:
        user.password_hash = hash_password(payload.new_password)
    if payload.steamgriddb_api_key is not None:
        user.steamgriddb_api_key = payload.steamgriddb_api_key.strip() or None

    if not user.username or not user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username and email are required."
        )

    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username or email already exists."
        ) from exc

    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "steamgriddb_api_key": user.steamgriddb_api_key,
    }


@router.post("/me/psn")
async def connect_psn(
    payload: PsnConnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int | None]:
    """Validate a PSN npsso token against Sony's OAuth flow before persisting
    it — never store a token that doesn't actually work."""
    try:
        result = await asyncio.to_thread(PSNClient(payload.npsso_token).validate)
    except PSNError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user.psn_npsso_token = encrypt_secret(payload.npsso_token)
    user.psn_validated_at = int(time.time())
    user.psn_online_id = result.get("profile_name")
    user.psn_avatar_url = result.get("avatar_url")
    await db.commit()
    return {
        "status": "connected",
        "validated_at": user.psn_validated_at,
        "display_name": user.psn_online_id,
        "avatar_url": user.psn_avatar_url,
    }


@router.delete("/me/psn")
async def disconnect_psn(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    user.psn_npsso_token = None
    user.psn_validated_at = None
    user.psn_online_id = None
    user.psn_avatar_url = None
    await db.commit()
    return {"status": "disconnected"}


@router.get("/me/psn/status")
async def psn_status(user: User = Depends(get_current_user)) -> dict[str, bool | int | str | None]:
    """Never echoes the token itself — connected/validated_at only. Does not
    re-validate against Sony on every call; reconnect (POST /me/psn) to
    re-check a token that may have expired."""
    return {
        "connected": user.psn_npsso_token is not None,
        "validated_at": user.psn_validated_at,
        "display_name": user.psn_online_id,
        "avatar_url": user.psn_avatar_url,
    }


@router.get("/users")
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, str | bool | int]]:
    del admin
    users = await db.scalars(select(User).order_by(User.username))
    return [
        {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "created_at": user.created_at,
        }
        for user in users
    ]


@router.post("/api-keys")
async def create_user_api_key(
    payload: ApiKeyCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | list[str]]:
    api_key, key_prefix, key_hash = create_api_key()
    db.add(
        UserApiKey(
            user_id=user.id,
            name=payload.name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=payload.scopes,
        )
    )
    await db.commit()
    return {
        "api_key": api_key,
        "key_prefix": key_prefix,
        "name": payload.name,
        "scopes": payload.scopes,
        "warning": "Store this key now. It will not be shown again.",
    }


@router.delete("/api-keys/{key_id}")
async def revoke_user_api_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    api_key = await db.scalar(
        select(UserApiKey).where(UserApiKey.id == key_id, UserApiKey.user_id == user.id)
    )
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    api_key.revoked_at = int(time.time())
    await db.commit()
    return {"status": "revoked", "key_id": str(key_id)}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | bool]:
    del admin
    username = payload.username.strip()
    email = payload.email.strip().lower()
    if not username or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username and email are required."
        )

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_admin=payload.is_admin,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username or email already exists."
        ) from exc

    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
    }


@router.patch("/users/{user_id}")
async def update_user_admin_status(
    user_id: UUID,
    payload: UserAdminUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | bool]:
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if (
        user.username == settings.PRIMARY_USER_USERNAME
        or user.email == settings.PRIMARY_USER_EMAIL.lower()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The primary user's admin status cannot be changed.",
        )
    if user.id == admin.id and not payload.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own admin access.",
        )

    user.is_admin = payload.is_admin
    await db.commit()
    await db.refresh(user)
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: UUID,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if (
        user.username == settings.PRIMARY_USER_USERNAME
        or user.email == settings.PRIMARY_USER_EMAIL.lower()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The primary user cannot be deleted."
        )
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account."
        )

    await db.delete(user)
    await db.commit()
    shutil.rmtree(Path("/data/user") / str(user_id), ignore_errors=True)
    return {"status": "deleted", "user_id": str(user_id)}
