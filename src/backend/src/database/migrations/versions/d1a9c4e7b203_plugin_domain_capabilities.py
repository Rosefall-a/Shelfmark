"""Add plugin notification-provider delivery state.

Revision ID: d1a9c4e7b203
Revises: c4e8a1b92d77
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d1a9c4e7b203"
down_revision: str | None = "c4e8a1b92d77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_provider_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider_id", name="uq_notification_provider_user_provider"
        ),
    )
    op.create_index(
        "ix_notification_provider_settings_user_id",
        "notification_provider_settings",
        ["user_id"],
    )
    op.create_table(
        "plugin_notification_provider_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plugin_id", sa.String(length=128), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("action_id", sa.String(length=128), nullable=False),
        sa.Column("registered_at", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", name="uq_plugin_notification_provider_id"),
    )
    op.create_index(
        "ix_plugin_notification_provider_registrations_plugin_id",
        "plugin_notification_provider_registrations",
        ["plugin_id"],
    )
    op.create_index(
        "ix_plugin_notification_provider_registrations_installation_id",
        "plugin_notification_provider_registrations",
        ["installation_id"],
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.BigInteger(), nullable=True),
        sa.Column("next_attempt_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notification_id",
            "provider_id",
            name="uq_notification_delivery_notification_provider",
        ),
    )
    op.create_index(
        "ix_notification_delivery_pending",
        "notification_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_delivery_pending", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index(
        "ix_plugin_notification_provider_registrations_installation_id",
        table_name="plugin_notification_provider_registrations",
    )
    op.drop_index(
        "ix_plugin_notification_provider_registrations_plugin_id",
        table_name="plugin_notification_provider_registrations",
    )
    op.drop_table("plugin_notification_provider_registrations")
    op.drop_index(
        "ix_notification_provider_settings_user_id",
        table_name="notification_provider_settings",
    )
    op.drop_table("notification_provider_settings")
