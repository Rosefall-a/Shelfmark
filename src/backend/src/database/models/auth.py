from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class UserSession(Base):
    # session metadata model
    __tablename__ = "user_sessions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    last_seen_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    geo_country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geo_region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geo_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geo_latitude: Mapped[float | None] = mapped_column(nullable=True)
    geo_longitude: Mapped[float | None] = mapped_column(nullable=True)
    geo_network_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geo_network_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geo_network_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    geo_network_organization: Mapped[str | None] = mapped_column(String(256), nullable=True)
    anomaly_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    anomaly_previous_location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)


class UserApiKey(Base):
    __tablename__ = "user_api_keys"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
