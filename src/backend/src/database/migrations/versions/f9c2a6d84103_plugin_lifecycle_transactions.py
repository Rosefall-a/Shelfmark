"""Persist plugin package/grant commit receipts for crash recovery."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f9c2a6d84103"
down_revision = "e7f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plugin_permission_grants",
        sa.Column("revoked_by_operation", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_table(
        "plugin_lifecycle_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plugin_id", sa.String(128), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("added_grants", sa.JSON(), nullable=False),
        sa.Column("removed_grants", sa.JSON(), nullable=False),
        sa.Column("grant_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_plugin_lifecycle_transactions_plugin_id", "plugin_lifecycle_transactions", ["plugin_id"]
    )


def downgrade() -> None:
    op.drop_table("plugin_lifecycle_transactions")
    op.drop_column("plugin_permission_grants", "revoked_by_operation")
