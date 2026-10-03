"""Generates the auto-created Prestige challenge for a card, once its
game's achievements are fully unlocked. The card side never lets a user
type or pick this challenge — this is the only source for what a
Prestige challenge actually is, and it always comes from real per-game
data rather than being invented per call.

Signals are checked in priority order, each one a real fact about the
game rather than a guess:
  1. `tier == 'missable'` achievements — the one genuinely
     provider-verified difficulty signal this app has (RetroAchievements
     only). The challenge is to earn them all in a single blind run.
  2. Tags/features naming a genre with an established permadeath/no-death
     convention (roguelike, souls-like).
Falls back to a small, fixed catalog of well-known challenge-run
archetypes, picked deterministically from the game's own id — stable
across regenerations, never re-rolled, never chosen by a person."""

import hashlib
from dataclasses import dataclass

from src.database.models.achievement import Achievement
from src.database.models.game import Game

_ROGUELIKE_TAGS = ("roguelike", "roguelite", "permadeath")
_SOULSLIKE_TAGS = ("souls-like", "soulslike", "souls")

_FALLBACK_CHALLENGES = [
    (
        "Iron Run: {title}",
        "Complete {title} again in a single attempt — any death or crash restarts the run from the beginning.",
    ),
    (
        "No-Hit Clear: {title}",
        "Complete {title} again without taking damage from a boss or major encounter.",
    ),
    (
        "Blind Restriction: {title}",
        "Complete {title} again under one self-picked permanent restriction (no upgrades, no fast travel, "
        "starting gear only) chosen before you start.",
    ),
    (
        "Against the Clock: {title}",
        "Complete {title} again in under half the time it took the first time.",
    ),
]


@dataclass
class PrestigeChallenge:
    title: str
    description: str


def generate_prestige_challenge(game: Game, achievements: list[Achievement]) -> PrestigeChallenge:
    missable = [a for a in achievements if a.tier == "missable"]
    if missable:
        count = len(missable)
        return PrestigeChallenge(
            title=f"Missable Sweep: {game.title}",
            description=(
                f"Earn all {count} missable achievement{'s' if count != 1 else ''} in {game.title} in a single "
                f"blind playthrough — no save-scumming past the point where they can still be missed."
            ),
        )

    tags = {t.lower() for t in (game.tags or [])} | {f.lower() for f in (game.features or [])}
    if tags & set(_ROGUELIKE_TAGS):
        return PrestigeChallenge(
            title=f"Permadeath Run: {game.title}",
            description=f"Complete {game.title} again in a single life — any death ends the run.",
        )
    if tags & set(_SOULSLIKE_TAGS):
        return PrestigeChallenge(
            title=f"No-Death Clear: {game.title}",
            description=f"Complete {game.title} again without dying once.",
        )

    index = int(hashlib.sha256(str(game.id).encode()).hexdigest(), 16) % len(_FALLBACK_CHALLENGES)
    title_template, desc_template = _FALLBACK_CHALLENGES[index]
    return PrestigeChallenge(
        title=title_template.format(title=game.title),
        description=desc_template.format(title=game.title),
    )
