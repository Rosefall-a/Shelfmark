"""Merge the notification-provider and metadata-refresh migration branches.

Revision ID: d8e4f1a2b6c3
Revises: c2d7e9f1a4b8, c4f1d2e8a9b0
"""

from collections.abc import Sequence

revision: str = "d8e4f1a2b6c3"
down_revision: tuple[str, str] = ("c2d7e9f1a4b8", "c4f1d2e8a9b0")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
