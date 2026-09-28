# pylint: disable=too-few-public-methods\n"""Tracks which metadata-sourced fields an admin has deliberately changed
on a Movie/TVShow/Anime row, so the "Apply metadata" search result button
(features/metadata/*/search.py's results, applied via each FormModal) can
skip re-filling them later instead of silently overwriting a manual fix."""

from typing import Any, Protocol


class _LockableEntity(Protocol):
    locked_fields: list[str]


def apply_updates_with_locking(
    entity: _LockableEntity,
    updates: dict[str, Any],
    lockable_fields: frozenset[str],
) -> None:
    """Applies `updates` onto `entity`. Any field in `lockable_fields`
    whose value actually changes is added to `entity.locked_fields`."""
    locked = set(entity.locked_fields)
    for field, value in updates.items():
        if field in lockable_fields and value != getattr(entity, field):
            locked.add(field)
        setattr(entity, field, value)
    entity.locked_fields = sorted(locked)
