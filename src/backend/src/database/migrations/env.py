import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.core.config import settings
from src.database.base import Base

# Import every model module here so its table gets registered on
# Base.metadata before autogenerate compares it against the database.
from src.database.models import (
    achievement,  # noqa: F401
    anime,  # noqa: F401
    app_integration_settings,  # noqa: F401
    auth,  # noqa: F401
    bounty,  # noqa: F401
    calendar_event,  # noqa: F401
    card,  # noqa: F401
    game,  # noqa: F401
    game_archive,  # noqa: F401
    game_checklist_item,  # noqa: F401
    game_field_change,  # noqa: F401
    game_file_item,  # noqa: F401
    game_profile,  # noqa: F401
    game_profile_stat_snapshot,  # noqa: F401
    inbox_item,  # noqa: F401
    job_setting,  # noqa: F401
    media_extras,  # noqa: F401
    media_item,  # noqa: F401
    movies,  # noqa: F401
    notification,  # noqa: F401
    oidc_provider,
    oidc_settings,
    tv_show,  # noqa: F401
    user,  # noqa: F401
    user_appearance_settings,  # noqa: F401
    user_preferences,  # noqa: F401
    user_scan_settings,  # noqa: F401
)
from src.database.models import set as set_model  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live DB connection (rarely used)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect using the async engine and run migrations against it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
