"""Add browser session metadata used by the session-manager plugin."""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "e7f1a2b3c4d5"
down_revision: str | None = "d1a9c4e7b203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_sessions", sa.Column("last_seen_at", sa.BigInteger(), nullable=True))
    for name, typ in [
        ("ip_address", sa.String(255)),
        ("user_agent", sa.String(1024)),
        ("geo_country", sa.String(128)),
        ("geo_region", sa.String(128)),
        ("geo_city", sa.String(128)),
        ("geo_latitude", sa.Float()),
        ("geo_longitude", sa.Float()),
        ("geo_network_type", sa.String(32)),
        ("geo_network_label", sa.String(128)),
        ("geo_network_number", sa.BigInteger()),
        ("geo_network_organization", sa.String(256)),
        ("anomaly_reason", sa.String(512)),
        ("anomaly_previous_location", sa.String(512)),
        ("revoked_at", sa.BigInteger()),
    ]:
        op.add_column("user_sessions", sa.Column(name, typ, nullable=True))
    op.execute(
        sa.text("UPDATE user_sessions SET last_seen_at = created_at WHERE last_seen_at IS NULL")
    )
    op.alter_column("user_sessions", "last_seen_at", nullable=False)
    op.create_index("ix_user_sessions_last_seen_at", "user_sessions", ["last_seen_at"])
    op.create_index("ix_user_sessions_revoked_at", "user_sessions", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_revoked_at", table_name="user_sessions")
    op.drop_index("ix_user_sessions_last_seen_at", table_name="user_sessions")
    for name in (
        "revoked_at",
        "anomaly_previous_location",
        "anomaly_reason",
        "geo_network_organization",
        "geo_network_number",
        "geo_network_label",
        "geo_network_type",
        "geo_longitude",
        "geo_latitude",
        "geo_city",
        "geo_region",
        "geo_country",
        "user_agent",
        "ip_address",
        "last_seen_at",
    ):
        op.drop_column("user_sessions", name)
