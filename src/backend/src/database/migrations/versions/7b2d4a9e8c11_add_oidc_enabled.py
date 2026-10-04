"""Add a deployment-level OIDC enabled switch.

revision: 7b2d4a9e8c11
down_revision: f186cf8aa5c4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from src.database import migration_helpers as h

revision: str = "7b2d4a9e8c11"
down_revision: str | None = "f186cf8aa5c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # safe to re-run on a database adopted from an older history (see
    # src/database/migrate.py), which may already have the column
    if h.has_column("oidc_settings", "enabled"):
        return
    op.add_column(
        "oidc_settings",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("oidc_settings", "enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("oidc_settings", "enabled")
