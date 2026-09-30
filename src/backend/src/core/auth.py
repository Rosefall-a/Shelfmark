from __future__ import annotations

import hashlib
import re
import secrets
import time
from typing import Final

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.database.models.auth import UserApiKey, UserSession
from src.database.models.user import User
from src.database.session import get_db

_SALT_BYTES: Final = 16
_HASH_BYTES: Final = 32
_SCRYPT_N: Final = 2**14
_SCRYPT_R: Final = 8
_SCRYPT_P: Final = 1
_DB_DEPENDENCY = Depends(get_db)
SESSION_COOKIE: Final = "session"
SESSION_TTL_SECONDS: Final = 30 * 24 * 60 * 60
API_KEY_PREFIX: Final = "utk_"


def validate_password(password: str) -> str:
    """Validate the minimum password policy and return the original value."""
    if len(password) < 9:
        raise ValueError("Password must be at least 9 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain an uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain a lowercase letter.")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("Password must contain a symbol.")
    return password


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_HASH_BYTES,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${password_hash.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, hash_hex = stored_hash.split("$")
        if algorithm != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(hash_hex)),
        )
        return secrets.compare_digest(candidate, bytes.fromhex(hash_hex))
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_api_key() -> tuple[str, str, str]:
    secret = secrets.token_urlsafe(32)
    api_key = f"{API_KEY_PREFIX}{secret}"
    return api_key, api_key[:12], hash_token(api_key)


async def revoke_session(db: AsyncSession, session_token: str) -> bool:
    """Delete one opaque session using only the hash of its cookie value."""
    result = await db.execute(
        delete(UserSession).where(UserSession.token_hash == hash_token(session_token))
    )
    await db.commit()
    return bool(result.rowcount)


async def get_current_user(
    db: AsyncSession = _DB_DEPENDENCY,
    authorization: str | None = Header(default=None),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    user: User | None = None
    now = int(time.time())

    if authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:].strip()
        if api_key.startswith(API_KEY_PREFIX):
            user = await db.scalar(
                select(User)
                .join(UserApiKey, UserApiKey.user_id == User.id)
                .where(
                    UserApiKey.key_hash == hash_token(api_key),
                    UserApiKey.revoked_at.is_(None),
                    User.is_active.is_(True),
                )
            )

    if user is None and session_token:
        user = await db.scalar(
            select(User)
            .join(UserSession, UserSession.user_id == User.id)
            .where(
                UserSession.token_hash == hash_token(session_token),
                UserSession.expires_at > now,
                User.is_active.is_(True),
            )
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def ensure_primary_user(db: AsyncSession) -> User:
    """Create the configured admin account once and return it."""
    username = settings.PRIMARY_USER_USERNAME.strip()
    email = settings.PRIMARY_USER_EMAIL.strip().lower()
    if not username or not email or not settings.PRIMARY_USER_PASSWORD:
        raise RuntimeError("Primary user username, email, and password must be configured.")
    try:
        validate_password(settings.PRIMARY_USER_PASSWORD)
    except ValueError as exc:
        raise RuntimeError(f"Invalid primary user password: {exc}") from exc

    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        user = await db.scalar(select(User).where(User.email == email))

    if user is None:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(settings.PRIMARY_USER_PASSWORD),
            is_admin=True,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    if user.email != email:
        raise RuntimeError("Primary user username and email point to different accounts.")
    if not user.is_admin:
        user.is_admin = True
        await db.commit()
        await db.refresh(user)
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return user
