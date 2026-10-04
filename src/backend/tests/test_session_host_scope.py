from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from src.api.routes.auth import LoginRequest, login, logout
from src.core.auth import get_current_user, session_cookie_name


def _request(host: str, cookie_name: str | None = None, cookie_value: str | None = None) -> Request:
    headers = [(b"host", host.encode("ascii"))]
    if cookie_name and cookie_value:
        headers.append((b"cookie", f"{cookie_name}={cookie_value}".encode("ascii")))
    return Request({"type": "http", "headers": headers})


def test_session_cookie_name_is_stable_per_host_and_port() -> None:
    assert session_cookie_name("localhost:5173") == session_cookie_name("localhost:5173")
    assert session_cookie_name("localhost:5173") != session_cookie_name("localhost:8080")
    assert session_cookie_name("LOCALHOST:5173") == session_cookie_name("localhost:5173")


@pytest.mark.asyncio
async def test_login_uses_different_cookie_names_for_different_ports() -> None:
    user = SimpleNamespace(id="user-id", is_active=True, password_hash="stored")
    db = Mock()
    db.scalar = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.add = Mock()

    with patch("src.api.routes.auth.verify_password", return_value=True):
        first_response = Response()
        await login(
            LoginRequest(username_or_email="admin", password="Correct!9"),
            _request("localhost:5173"),
            first_response,
            db,
        )

        second_response = Response()
        await login(
            LoginRequest(username_or_email="admin", password="Correct!9"),
            _request("localhost:8080"),
            second_response,
            db,
        )

    assert first_response.headers["set-cookie"].startswith(
        f"{session_cookie_name('localhost:5173')}="
    )
    assert second_response.headers["set-cookie"].startswith(
        f"{session_cookie_name('localhost:8080')}="
    )


@pytest.mark.asyncio
async def test_session_cookie_only_authenticates_on_its_own_host() -> None:
    token = "host-a-session"
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(id="user-id", is_active=True)

    user = await get_current_user(
        _request("localhost:5173", session_cookie_name("localhost:5173"), token),
        db,
    )
    assert user.id == "user-id"

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            _request("localhost:8080", session_cookie_name("localhost:5173"), token),
            db,
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_deletes_the_request_host_cookie() -> None:
    db = AsyncMock()
    db.execute.return_value = Mock(rowcount=1)
    response = Response()

    await logout(
        _request("localhost:8080", session_cookie_name("localhost:8080"), "token"),
        response,
        db,
    )

    assert response.headers["set-cookie"].startswith(
        f"{session_cookie_name('localhost:8080')}="
    )
