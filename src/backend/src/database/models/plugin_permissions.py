"""Database models for plugin permission grants, requests and scoped clients."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class PluginLifecycleTransaction(Base):
    """Commit receipt for recovering an interrupted package/grant transaction."""

    __tablename__ = "plugin_lifecycle_transactions"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    added_grants: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    removed_grants: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    grant_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed: Mapped[bool] = mapped_column(nullable=False, default=False)


class PluginPermissionRequest(Base):
    __tablename__ = "plugin_permission_requests"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    installation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_version: Mapped[int] = mapped_column(nullable=False)
    rationale: Mapped[str] = mapped_column(String(1024), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    requested_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    resolved_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PluginPermissionGrant(Base):
    __tablename__ = "plugin_permission_grants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    installation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_version: Mapped[int] = mapped_column(nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    device_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    granted_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revoked_by_operation: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class PluginClientIdentity(Base):
    __tablename__ = "plugin_client_identities"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    installation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    last_seen_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
