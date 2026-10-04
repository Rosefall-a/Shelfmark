from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class AppIntegrationSettings(Base):
    """Singleton row containing deployment-wide provider credentials.

    These credentials are shared fallbacks for users who have not supplied
    their own provider credentials. User credentials take precedence over
    this row, and this row takes precedence over environment variables.
    Secret values are stored encrypted; only safe identifiers are returned
    by the settings API.
    """

    __tablename__ = "app_integration_settings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Metadata providers
    steamgriddb_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    retroachievements_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    giantbomb_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    igdb_client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    igdb_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    # movies metadata search — a bare API key grants access by itself
    # (unlike igdb_client_id), so both are Fernet-encrypted and never
    # echoed back to the client, same rule as igdb_client_secret
    tmdb_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    omdb_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TheTVDB v4 — the only real franchise/relations source for TV shows
    # (TMDB has no collection concept for TV). Same treatment as the keys
    # above: Fernet-encrypted, never echoed back.
    tvdb_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    screenscraper_ssid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    screenscraper_sspassword: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenscraper_devid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    screenscraper_devpassword: Mapped[str | None] = mapped_column(Text, nullable=True)

    # OAuth application credentials can safely be shared by the deployment;
    # user-specific refresh/access tokens remain on User.
    xbox_client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    xbox_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)

    password_min_length: Mapped[int | None] = mapped_column(nullable=True)
    password_require_uppercase: Mapped[bool | None] = mapped_column(nullable=True)
    password_require_lowercase: Mapped[bool | None] = mapped_column(nullable=True)
    password_require_digit: Mapped[bool | None] = mapped_column(nullable=True)
    password_require_symbol: Mapped[bool | None] = mapped_column(nullable=True)
    # Admin-editable override for MAX_UPLOAD_SIZE_MB (core/config.py) — null
    # means "use the .env default", so a deployment that never touches this
    # in Settings behaves exactly as it did before this column existed.
    max_upload_size_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=time.time, onupdate=time.time
    )
