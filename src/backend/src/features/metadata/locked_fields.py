"""Tracks which metadata-sourced fields an admin has deliberately changed
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
    """Apply updates while tracking deliberately changed metadata fields.

    ``title_lock`` is an explicit override used by edit forms. When omitted,
    changing a title keeps the existing behaviour of locking it automatically.
    Passing ``True`` locks the title; passing ``False`` explicitly unlocks it.
    """
    updates = dict(updates)
    title_lock = updates.pop("title_lock", None)

    locked = set(entity.locked_fields)
    for field, value in updates.items():
        if field in lockable_fields and value != getattr(entity, field):
            locked.add(field)
        setattr(entity, field, value)

    if title_lock is True:
        locked.add("title")
    elif title_lock is False:
        locked.discard("title")

    entity.locked_fields = sorted(locked)
