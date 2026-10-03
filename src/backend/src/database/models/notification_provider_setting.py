from __future__ import annotations

import time
from uuid import UUID, uuid4
from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.database.base import Base

class NotificationProviderSetting(Base):
    __tablename__ = "notification_provider_settings"
    __table_args__ = (UniqueConstraint("user_id", "provider_id", name="uq_notification_provider_user_provider"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    destination_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time, onupdate=time.time)
