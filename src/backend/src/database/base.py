from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.

    Every model that inherits from Base is included
    in SQLAlchemy's metadata.
    """

    """Declarative SQLAlchemy base; no additional behavior is required."""
