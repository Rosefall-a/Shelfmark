from unittest.mock import AsyncMock, Mock

import pytest

from src.core.auth import (
    create_api_key,
    hash_password,
    hash_token,
    revoke_session,
    validate_password,
    verify_password,
)


def test_validate_password_accepts_password_meeting_policy() -> None:
    password = "Correct!9"

    assert validate_password(password) == password


def test_validate_password_rejects_missing_requirements() -> None:
    invalid_passwords = (
        "short!A1",
        "lowercase!1",
        "UPPERCASE!1",
        "NoSymbol99",
    )

    for password in invalid_passwords:
        try:
            validate_password(password)
        except ValueError:
            continue
        raise AssertionError(f"Expected password to be rejected: {password}")


def test_password_hash_round_trip_and_wrong_password() -> None:
    password = "Correct!9"
    stored_hash = hash_password(password)

    assert stored_hash.startswith("scrypt$")
    assert verify_password(password, stored_hash)
    assert not verify_password("Wrong!9", stored_hash)


def test_verify_password_rejects_malformed_hash() -> None:
    assert not verify_password("Correct!9", "not-a-valid-hash")
    assert not verify_password("Correct!9", "bcrypt$1$2$3$00$00")


def test_api_key_contains_only_safe_persisted_derivatives() -> None:
    api_key, prefix, key_hash = create_api_key()

    assert api_key.startswith("utk_")
    assert prefix == api_key[:12]
    assert key_hash == hash_token(api_key)
    assert len(key_hash) == 64


@pytest.mark.asyncio
async def test_revoke_session_preserves_metadata_and_commits() -> None:
    db = AsyncMock()
    db.execute.return_value = Mock(rowcount=1)

    assert await revoke_session(db, "raw-browser-cookie") is True

    statement = db.execute.await_args.args[0]
    assert "UPDATE user_sessions" in str(statement)
    assert "revoked_at" in str(statement)
    assert hash_token("raw-browser-cookie") in statement.compile().params.values()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoke_session_is_idempotent() -> None:
    db = AsyncMock()
    db.execute.return_value = Mock(rowcount=0)

    assert await revoke_session(db, "already-revoked") is False
    db.commit.assert_awaited_once()
