# pylint: disable=missing-module-docstring,too-few-public-methods
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class OidcProvider(Base):
    """A named OIDC identity provider available on the login page."""

    __tablename__ = "oidc_providers"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issuer_url: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(String(256), nullable=False)
    client_secret: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="openid profile email")
    redirect_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    groups_claim: Mapped[str] = mapped_column(String(128), nullable=False, default="groups")
    admin_group: Mapped[str | None] = mapped_column(String(256), nullable=True)
    user_match_field: Mapped[str] = mapped_column(String(16), nullable=False, default="email")
    allow_new_users: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    button_text: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Continue with SSO"
    )
    button_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )
