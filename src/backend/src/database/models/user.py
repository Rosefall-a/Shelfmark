# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class User(Base):
    """Application account."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    oidc_subject: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Secret path token for the iCalendar feed — calendar apps subscribe
    # by URL and can't send a login cookie, so the feed authenticates by
    # this instead. NULL until the user first asks for their feed URL.
    calendar_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    steamgriddb_api_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    psn_npsso_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    psn_validated_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    retroachievements_api_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    giantbomb_api_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    screenscraper_ssid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    screenscraper_sspassword: Mapped[str | None] = mapped_column(Text, nullable=True)
    xbox_client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    xbox_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    gog_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    steam_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    steam_api_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retroachievements_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    steam_library_synced_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    retroachievements_library_synced_at: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    psn_library_synced_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    steam_persona_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    steam_avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    retroachievements_avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    psn_online_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    psn_avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    updated_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=time.time, onupdate=time.time
    )
