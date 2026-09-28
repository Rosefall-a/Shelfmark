"""Create-if-missing wrappers for Alembic operations.

Every migration after the baseline must be safe to run on a database that
already has part of what it adds: src/database/migrate.py attaches a
database from an older (squashed) history to the baseline and then runs
every later migration on it. These helpers look before they act, so the
same migration builds a fresh database and leaves an adopted one alone.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.engine.Inspector:
    # a fresh inspector per call: Inspector caches what it has read, and
    # the schema changes between calls inside one migration
    return sa.inspect(op.get_bind())


def has_table(table: str) -> bool:
    return _inspector().has_table(table)


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return any(col["name"] == column for col in _inspector().get_columns(table))


def has_index(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(index["name"] == name for index in _inspector().get_indexes(table))


def has_constraint(name: str) -> bool:
    row = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"), {"name": name}
    )
    return row.first() is not None


def create_table_if_missing(table: str, *columns: sa.schema.SchemaItem, **kw: object) -> None:
    if not has_table(table):
        op.create_table(table, *columns, **kw)


def add_column_if_missing(table: str, column: sa.Column) -> None:
    if not has_column(table, column.name):
        op.add_column(table, column)


def create_index_if_missing(
    name: str,
    table: str,
    columns: list[str],
    *,
    unique: bool = False,
    postgresql_where: sa.TextClause | None = None,
) -> None:
    if not has_index(table, name):
        op.create_index(name, table, columns, unique=unique, postgresql_where=postgresql_where)


def drop_index_if_exists(name: str, table: str) -> None:
    if has_index(table, name):
        op.drop_index(name, table_name=table)


def create_unique_constraint_if_missing(name: str, table: str, columns: list[str]) -> None:
    if not has_constraint(name):
        op.create_unique_constraint(name, table, columns)


def delete_duplicate_episodes(table: str) -> None:
    """Keep one row per (season_id, episode_number), preferring the one with
    the most progress, so a unique constraint on the pair can be created on
    a database where a sync once raced."""
    op.execute(
        f"""
        DELETE FROM {table} WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY season_id, episode_number
                    ORDER BY watched DESC, (note IS NOT NULL) DESC, (rating IS NOT NULL) DESC, id
                ) AS rn FROM {table}
            ) ranked WHERE rn > 1
        )
        """
    )
