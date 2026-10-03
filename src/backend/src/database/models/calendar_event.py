# pylint: disable=missing-module-docstring,too-few-public-methods,unsubscriptable-object
import time
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Date, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class CalendarEvent(Base):
    """An entry the user put on the calendar by hand: a premiere the
    providers do not list, a reminder, a watch party. It may point at a title
    in the library (`media_type` and `media_id`) so it opens that title, but it
    stands on its own and never changes the title."""

    __tablename__ = "calendar_events"
    __table_args__ = (Index("ix_calendar_events_user_date", "user_id", "event_date"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    # "HH:MM" local to the user, or empty for an all-day entry
    event_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    media_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=lambda: int(time.time())
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )
