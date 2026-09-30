from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class OidcSettings(Base):
    """Deployment OIDC defaults and backward-compatible single-provider settings."""

    __tablename__ = "oidc_settings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    issuer_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="openid profile email")
    redirect_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    groups_claim: Mapped[str] = mapped_column(String(128), nullable=False, default="groups")
    admin_group: Mapped[str | None] = mapped_column(String(256), nullable=True)
    user_match_field: Mapped[str] = mapped_column(String(16), nullable=False, default="email")
    default_login_method: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    login_button_text: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Continue with SSO"
    )
    allow_new_users: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    providers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )
