"""Add a deployment-level OIDC enabled switch.

revision: 7b2d4a9e8c11
down_revision: f186cf8aa5c4
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "7b2d4a9e8c11"
down_revision: str | None = "f186cf8aa5c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "oidc_settings",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("oidc_settings", "enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("oidc_settings", "enabled")
