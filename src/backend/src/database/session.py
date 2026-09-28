# pylint: disable=missing-module-docstring
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import settings

# The engine manages the connection pool to PostgreSQL.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
)


# Factory for creating AsyncSession objects.
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides one database session
    for the lifetime of a request.
    """
    async with SessionLocal() as session:
        yield session
