from dataclasses import dataclass, field

from src.features.metadata.locked_fields import apply_updates_with_locking


@dataclass
class Entity:
    title: str = "Original"
    description: str = "Original description"
    locked_fields: list[str] = field(default_factory=list)


def test_title_changes_are_locked_by_default() -> None:
    entity = Entity()

    apply_updates_with_locking(entity, {"title": "Manual title"}, frozenset({"title"}))

    assert entity.title == "Manual title"
    assert entity.locked_fields == ["title"]


def test_title_lock_can_be_explicitly_enabled_without_a_title_change() -> None:
    entity = Entity()

    apply_updates_with_locking(
        entity,
        {"title_lock": True},
        frozenset({"title"}),
    )

    assert entity.title == "Original"
    assert entity.locked_fields == ["title"]


def test_title_lock_can_be_explicitly_disabled() -> None:
    entity = Entity(locked_fields=["title"])

    apply_updates_with_locking(
        entity,
        {"title_lock": False},
        frozenset({"title"}),
    )

    assert entity.locked_fields == []
