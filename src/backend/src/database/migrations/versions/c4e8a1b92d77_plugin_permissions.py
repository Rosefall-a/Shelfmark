"""Add plugin permission grants, requests and scoped client identities."""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c4e8a1b92d77"
down_revision: str | None = "7b2d4a9e8c11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plugin_permission_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plugin_id", sa.String(128), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.Column("capability_version", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.String(1024), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_at", sa.BigInteger(), nullable=False),
        sa.Column("resolved_at", sa.BigInteger(), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("plugin_id", "installation_id", "user_id"):
        op.create_index("ix_plugin_permission_requests_" + column, "plugin_permission_requests", [column])

    op.create_table(
        "plugin_permission_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plugin_id", sa.String(128), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.Column("capability_version", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("granted_at", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("plugin_id", "installation_id", "user_id", "device_id"):
        op.create_index("ix_plugin_permission_grants_" + column, "plugin_permission_grants", [column])

    op.create_table(
        "plugin_client_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plugin_id", sa.String(128), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("last_seen_at", sa.BigInteger(), nullable=True),
        sa.Column("revoked_at", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    for column in ("plugin_id", "installation_id", "user_id", "device_id"):
        op.create_index("ix_plugin_client_identities_" + column, "plugin_client_identities", [column])


def downgrade() -> None:
    for column in ("device_id", "user_id", "installation_id", "plugin_id"):
        op.drop_index("ix_plugin_client_identities_" + column, table_name="plugin_client_identities")
    op.drop_table("plugin_client_identities")
    for column in ("device_id", "user_id", "installation_id", "plugin_id"):
        op.drop_index("ix_plugin_permission_grants_" + column, table_name="plugin_permission_grants")
    op.drop_table("plugin_permission_grants")
    for column in ("user_id", "installation_id", "plugin_id"):
        op.drop_index("ix_plugin_permission_requests_" + column, table_name="plugin_permission_requests")
    op.drop_table("plugin_permission_requests")
