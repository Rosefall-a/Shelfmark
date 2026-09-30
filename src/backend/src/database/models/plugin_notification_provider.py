"""Durable registrations for notification providers supplied by plugins."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class PluginNotificationProviderRegistration(Base):
    __tablename__ = "plugin_notification_provider_registrations"
    __table_args__ = (UniqueConstraint("provider_id", name="uq_plugin_notification_provider_id"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    installation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    action_id: Mapped[str] = mapped_column(String(128), nullable=False)
    registered_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
    )
    revoked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
