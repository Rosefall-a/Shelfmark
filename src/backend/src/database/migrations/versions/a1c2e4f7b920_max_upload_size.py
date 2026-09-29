"""Add admin-editable max upload size override

Revision ID: a1c2e4f7b920
Revises: f186cf8aa5c4
Create Date: 2026-09-28 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1c2e4f7b920"
down_revision: Union[str, None] = "f186cf8aa5c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_integration_settings",
        sa.Column("max_upload_size_mb", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_integration_settings", "max_upload_size_mb")
