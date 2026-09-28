"""Safe developer-facing lifecycle diagnostics; no secrets are returned."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from src.core.config import settings

def environment_name() -> str:
    mode = settings.STARTUP_MODE.strip().lower()
    if mode in {"dev", "development"}: return "development"
    if mode == "testing": return "testing"
    if mode: return "production-like"
    return "normal"

def diagnostics_enabled() -> bool:
    return settings.DEBUG or settings.STARTUP_MODE.strip().lower() in {"dev", "development", "testing"}

def _migration_state(connection: AsyncConnection) -> tuple[str, list[str]]:
    def read_state(sync_connection) -> tuple[str, list[str]]:
        context = MigrationContext.configure(sync_connection)
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        heads = sorted(ScriptDirectory.from_config(config).get_heads())
        current = sorted(context.get_current_heads())
        if not current: return "not-initialized", heads
        return ("up-to-date" if current == heads else "pending"), heads
    return connection.run_sync(read_state)

async def collect_diagnostics() -> dict[str, Any]:
    database, migrations, heads = "unavailable", "unknown", []
    from src.database.session import engine
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            database = "ready"
            migrations, heads = await _migration_state(connection)
    except Exception:
        pass
    return {"environment": environment_name(), "debug_enabled": settings.DEBUG, "backend": "ready", "database": database, "migrations": migrations, "migration_heads": len(heads)}
