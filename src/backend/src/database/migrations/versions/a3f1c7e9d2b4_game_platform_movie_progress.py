"""Record a game's platform, region and language, and how far into a movie you got.

games.platform is the system a game is played on (separate from `source`,
which is where the copy came from); games.region and games.language were
already in the Add/Edit Game form and the library filters but had nowhere
to be stored. movies.progress_minutes is where you left off in a movie you
started but haven't finished.

Both are create-if-missing, so this is safe on a database adopted from an
older history (see src/database/migrate.py).

revision: a3f1c7e9d2b4
down_revision: 7b2d4a9e8c11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from src.database import migration_helpers as h

revision: str = "a3f1c7e9d2b4"
down_revision: str | None = "7b2d4a9e8c11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("platform", "region", "language"):
        h.add_column_if_missing("games", sa.Column(column, sa.String(length=50), nullable=True))
    h.add_column_if_missing("movies", sa.Column("progress_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.execute("ALTER TABLE movies DROP COLUMN IF EXISTS progress_minutes")
    for column in ("language", "region", "platform"):
        op.execute(f"ALTER TABLE games DROP COLUMN IF EXISTS {column}")
