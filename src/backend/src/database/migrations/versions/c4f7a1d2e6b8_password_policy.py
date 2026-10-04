"""Persist deployment-wide password policy settings.

revision: c4f7a1d2e6b8
down_revision: 7b2d4a9e8c11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c4f7a1d2e6b8"
down_revision: str | None = "a3f1c7e9d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_integration_settings", sa.Column("password_min_length", sa.Integer(), nullable=True))
    op.add_column("app_integration_settings", sa.Column("password_require_uppercase", sa.Boolean(), nullable=True))
    op.add_column("app_integration_settings", sa.Column("password_require_lowercase", sa.Boolean(), nullable=True))
    op.add_column("app_integration_settings", sa.Column("password_require_digit", sa.Boolean(), nullable=True))
    op.add_column("app_integration_settings", sa.Column("password_require_symbol", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_integration_settings", "password_require_symbol")
    op.drop_column("app_integration_settings", "password_require_digit")
    op.drop_column("app_integration_settings", "password_require_lowercase")
    op.drop_column("app_integration_settings", "password_require_uppercase")
    op.drop_column("app_integration_settings", "password_min_length")
