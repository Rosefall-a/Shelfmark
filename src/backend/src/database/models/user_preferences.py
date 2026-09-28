# pylint: disable=missing-class-docstring,too-few-public-methods,unsubscriptable-object
"""Per-user app preferences that live on the server (so they follow the
user across browsers): calendar options, notification toggles, and
whatever the Settings page grows next. One row per user, created lazily;
`data` holds only what the user changed, defaults live in code
(api/routes/preferences.py) so adding an option never needs a migration."""

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey

from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
