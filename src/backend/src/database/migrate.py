# pylint: disable=missing-class-docstring,import-outside-toplevel,unused-import,broad-exception-caught,missing-function-docstring,try-except-raise
"""Brings the database up to date on every start, so updating the app is
just pulling the new version and starting it.

What it does, in order:
1. Waits for the database to accept connections (and gives up with a clear
   message after a minute, instead of retrying a real error 30 times).
2. Takes a lock so two starting containers never migrate at once.
3. Looks at what the database says its version is:
   - empty database: builds everything from the migrations
   - a version this code has never heard of (the migration history was
     rewritten or squashed since this database was created), or tables
     with no version at all: it is attached to the starting migration and
     brought up to date, keeping all data. Afterwards it is checked against
     the models, and if something the code needs is STILL missing (nothing
     in the history creates it) it stops and says exactly what, instead of
     guessing, and forgets the attachment so the next start checks again.
   - a version that is in the history: nothing special
4. Runs every migration newer than the database.

Rewriting the migration history is therefore safe for existing installs:
any database from the old history is adopted automatically on its next
start. New migrations should still be written to be safe to run twice
(create-if-missing), see docs/migrations.md."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

_LOCK_ID = 7_310_442_901
_WAIT_SECONDS = 60


@dataclass(frozen=True)
class Plan:
    action: str  # "fresh" | "upgrade" | "adopt"
    reason: str


def decide(current: set[str], known: set[str], has_tables: bool) -> Plan:
    """What to do with a database, from its recorded versions, the versions
    this code's history contains, and whether it has any tables at all."""
    if not has_tables:
        return Plan("fresh", "empty database")
    if not current:
        return Plan("adopt", "tables exist but no recorded version")
    unknown = sorted(current - known)
    if unknown:
        return Plan(
            "adopt", f"recorded version {', '.join(unknown)} is not in this migration history"
        )
    return Plan("upgrade", "recorded version is in the history")


def missing_from_database(engine: Engine) -> list[str]:
    """What the models need that the database does not have: whole tables
    and columns. Extra things in the database (an old index, a spare
    column) are harmless and ignored."""
    import src.main  # noqa: F401  registers every model on Base.metadata
    from src.database.base import Base

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    problems: list[str] = []
    for entry in diff:
        ops = entry if isinstance(entry, list) else [entry]
        for op in ops:
            kind = op[0]
            if kind == "add_table":
                problems.append(f"table {op[1].name}")
            elif kind == "add_column":
                problems.append(f"column {op[2]}.{op[3].name}")
    return problems


def _engine() -> Engine:
    from src.core.config import settings

    return create_engine(settings.DATABASE_URL.replace("+asyncpg", "+psycopg"), pool_pre_ping=True)


def _wait_for_database(engine: Engine) -> None:
    deadline = time.time() + _WAIT_SECONDS
    last = ""
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            last = str(exc).splitlines()[0]
            if time.time() > deadline:
                raise SystemExit(
                    f"Database is not reachable after {_WAIT_SECONDS}s: {last}"
                ) from exc
            print(f"Waiting for the database ({last})...", flush=True)
            time.sleep(2)


def main() -> None:
    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    known = {rev.revision for rev in script.walk_revisions()}
    bases = script.get_bases()
    if len(script.get_heads()) != 1 or len(bases) != 1:
        raise SystemExit(
            f"The migration history is not a single line (heads: {script.get_heads()}, roots: {bases}). "
            "Fix it before starting."
        )

    engine = _engine()
    _wait_for_database(engine)

    with engine.connect() as lock_conn:
        lock_conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": _LOCK_ID})
        try:
            inspector = inspect(lock_conn)
            tables = set(inspector.get_table_names())
            has_tables = bool(tables - {"alembic_version"})
            current: set[str] = set()
            if "alembic_version" in tables:
                current = {
                    row[0]
                    for row in lock_conn.execute(text("SELECT version_num FROM alembic_version"))
                }
            lock_conn.commit()

            plan = decide(current, known, has_tables)
            print(f"Database: {plan.action} ({plan.reason})", flush=True)

            if plan.action == "adopt":
                # the migrations after the starting one are written to be safe on a
                # database that already has part of what they add, so attach first
                # and check afterwards: checking the models first would refuse every
                # database that predates a migration this version ships
                base = bases[0]
                print(
                    f"Attaching the database to migration {base}. Its data is untouched.",
                    flush=True,
                )
                command.stamp(cfg, base, purge=True)
                command.upgrade(cfg, "head")
                problems = missing_from_database(engine)
                if problems:
                    command.stamp(cfg, "base", purge=True)  # not attached: check again next start
                    raise SystemExit(
                        "This database was made by an older version and is missing what this version needs, "
                        "and no migration creates it: "
                        + ", ".join(problems)
                        + ". Start the previous version once so it can finish its own updates, then update again."
                    )
            else:
                command.upgrade(cfg, "head")
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _LOCK_ID})
            lock_conn.commit()
    print("Database is up to date.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"Migration failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
