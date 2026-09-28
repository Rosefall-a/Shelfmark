# pylint: disable=missing-module-docstring,too-few-public-methods,unsubscriptable-object
import time

from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class JobSetting(Base):
    """How one cleanup job is scheduled: whether it runs by itself, how
    often, and when it last ran. A job with no row has never been set up, which
    means the job's own default. Deployment-wide (jobs work on everyone's library), so it is
    changed by an administrator."""

    __tablename__ = "job_settings"

    job_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1440, server_default="1440"
    )
    last_run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )
