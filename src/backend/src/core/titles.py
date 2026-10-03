# pylint: disable=missing-function-docstring
"""Which spelling of an anime's title to show.

`title` is the canonical one the rest of the app stores and searches by. The
English, romaji and Japanese spellings (from AniList) sit beside it, and the
user's `title_language` preference decides which one is displayed. If the
preferred spelling is not known for a title, the next best is used and
finally `title`, so a title is never blank."""

from typing import Any

_ORDER = {
    "english": ("title_english", "title_romaji", "title_native"),
    "romaji": ("title_romaji", "title_english", "title_native"),
    "native": ("title_native", "title_romaji", "title_english"),
}
ALT_FIELDS = ("title_english", "title_romaji", "title_native")


def display_title(item: Any, language: str) -> str:
    for field in _ORDER.get(language, _ORDER["english"]):
        value = getattr(item, field, None)
        if value:
            return str(value)
    return str(item.title)


def apply_alt_titles(show: Any, meta: dict[str, Any]) -> bool:
    """Stores the spellings AniList gave, only where the title has none yet.
    Returns whether anything was set."""
    changed = False
    for field in ALT_FIELDS:
        if not getattr(show, field, None) and meta.get(field):
            setattr(show, field, meta[field])
            changed = True
    return changed
