"""Add notification provider settings and delivery state."""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="c2d7e9f1a4b8"; down_revision="7b2d4a9e8c11"; branch_labels: str|Sequence[str]|None=None; depends_on=None

def upgrade():
    for name,column in [
        ("smtp_enabled",sa.Column("smtp_enabled",sa.Boolean(),nullable=False,server_default=sa.false())),
        ("smtp_host",sa.Column("smtp_host",sa.String(255),nullable=True)),
        ("smtp_port",sa.Column("smtp_port",sa.Integer(),nullable=False,server_default="587")),
        ("smtp_username",sa.Column("smtp_username",sa.String(320),nullable=True)),
        ("smtp_password",sa.Column("smtp_password",sa.Text(),nullable=True)),
        ("smtp_from_email",sa.Column("smtp_from_email",sa.String(320),nullable=True)),
        ("smtp_security",sa.Column("smtp_security",sa.String(16),nullable=False,server_default="starttls")),
    ]: op.add_column("app_integration_settings",column)
    op.create_table("notification_provider_settings",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("user_id",postgresql.UUID(as_uuid=True),nullable=False),
        sa.Column("provider_id",sa.String(64),nullable=False),sa.Column("enabled",sa.Boolean(),nullable=False),
        sa.Column("destination_secret",sa.Text(),nullable=True),sa.Column("updated_at",sa.BigInteger(),nullable=False),
        sa.ForeignKeyConstraint(["user_id"],["users.id"],ondelete="CASCADE"),sa.UniqueConstraint("user_id","provider_id",name="uq_notification_provider_user_provider"))
    op.create_table("notification_deliveries",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("notification_id",postgresql.UUID(as_uuid=True),nullable=False),
        sa.Column("provider_id",sa.String(64),nullable=False),sa.Column("status",sa.String(16),nullable=False),
        sa.Column("attempts",sa.Integer(),nullable=False),sa.Column("last_error",sa.Text(),nullable=True),sa.Column("attempted_at",sa.BigInteger(),nullable=True),sa.Column("next_attempt_at",sa.BigInteger(),nullable=False),
        sa.ForeignKeyConstraint(["notification_id"],["notifications.id"],ondelete="CASCADE"),sa.UniqueConstraint("notification_id","provider_id",name="uq_notification_delivery_notification_provider"))
    op.create_index("ix_notification_delivery_pending","notification_deliveries",["status","next_attempt_at"])
    for name in ("smtp_enabled","smtp_port","smtp_security"): op.alter_column("app_integration_settings",name,server_default=None)

def downgrade():
    op.drop_index("ix_notification_delivery_pending",table_name="notification_deliveries"); op.drop_table("notification_deliveries"); op.drop_table("notification_provider_settings")
    for name in ("smtp_security","smtp_from_email","smtp_password","smtp_username","smtp_port","smtp_host","smtp_enabled"): op.drop_column("app_integration_settings",name)
