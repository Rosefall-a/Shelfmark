"""Add session network ownership metadata."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "f2a8c9d0e1b2"
down_revision: str = "e7f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_sessions", sa.Column("geo_network_number", sa.BigInteger(), nullable=True))
    op.add_column("user_sessions", sa.Column("geo_network_organization", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("user_sessions", "geo_network_organization")
    op.drop_column("user_sessions", "geo_network_number")
