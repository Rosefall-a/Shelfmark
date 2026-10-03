"""Picks a bounty for the system to propose on its own — either on a
timer (see `maybe_auto_propose` in api/routes/bounties.py, checked lazily
whenever the caller lists their bounties, no scheduled job/worker) or
on demand via the Random Bounty reroll button.

Two signal types, since those are the two kinds of real progress data
this app already tracks:
  - "mastery" candidates: a game already well into its achievements
    (50-99% unlocked) that doesn't have a mastery bounty yet — nudges
    toward finishing something you're already close on.
  - "completion" candidates: a dropped/on-hold/backlog game that's sat
    idle 14+ days with no completion bounty yet — the classic "go back
    to this" nudge, now expressed as a real goal instead of a vague poke.

Mastery candidates are preferred (finishing something nearly-done beats
restarting something abandoned); each pool excludes games that already
have a bounty of that type, in any status, so a dismissed/completed
suggestion is never re-proposed for the same game."""

import random
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.achievement import Achievement
from src.database.models.bounty import Bounty
from src.database.models.game import Game, GameStatus

MIN_IDLE_SECONDS = 14 * 24 * 60 * 60
_COMPLETION_ELIGIBLE_STATUSES = (GameStatus.DROPPED, GameStatus.ON_HOLD, GameStatus.BACKLOG)

MASTERY_POINTS_REWARD = 200
COMPLETION_POINTS_REWARD = 100


@dataclass
class BountyProposal:
    title: str
    type: str
    game_id: UUID
    points_reward: int


async def _mastery_candidates(db: AsyncSession, user_id: UUID) -> list[BountyProposal]:
    already_targeted = select(Bounty.game_id).where(
        Bounty.user_id == user_id, Bounty.type == "mastery"
    )
    totals = (
        select(
            Achievement.game_id,
            func.count().label("total"),
            func.count().filter(Achievement.unlocked.is_(True)).label("unlocked"),
        )
        .group_by(Achievement.game_id)
        .subquery()
    )
    result = await db.execute(
        select(Game, totals.c.total, totals.c.unlocked)
        .join(totals, totals.c.game_id == Game.id)
        .where(
            Game.user_id == user_id,
            Game.deleted_at.is_(None),
            Game.id.not_in(already_targeted),
            totals.c.total > 0,
        )
    )
    candidates = []
    for game, total, unlocked in result.all():
        pct = unlocked / total
        if 0.5 <= pct < 1.0:
            candidates.append(
                BountyProposal(
                    title=f"Master {game.title}",
                    type="mastery",
                    game_id=game.id,
                    points_reward=MASTERY_POINTS_REWARD,
                )
            )
    return candidates


async def _completion_candidates(db: AsyncSession, user_id: UUID) -> list[BountyProposal]:
    already_targeted = select(Bounty.game_id).where(
        Bounty.user_id == user_id, Bounty.type == "completion"
    )
    cutoff = int(time.time()) - MIN_IDLE_SECONDS
    result = await db.execute(
        select(Game).where(
            Game.user_id == user_id,
            Game.deleted_at.is_(None),
            Game.status.in_(_COMPLETION_ELIGIBLE_STATUSES),
            Game.id.not_in(already_targeted),
        )
    )
    candidates = []
    for game in result.scalars().all():
        idle_since = game.last_played_at if game.last_played_at is not None else game.created_at
        if idle_since is None or idle_since <= cutoff:
            candidates.append(
                BountyProposal(
                    title=f"Finish {game.title}",
                    type="completion",
                    game_id=game.id,
                    points_reward=COMPLETION_POINTS_REWARD,
                )
            )
    return candidates


async def pick_bounty_proposal(db: AsyncSession, user_id: UUID) -> BountyProposal | None:
    """Mastery candidates are preferred as a pool — finishing something
    nearly-done beats restarting something abandoned — but which one
    within the winning pool is picked at random, so hitting reroll (or a
    later timer tick, if more than one candidate still qualifies) doesn't
    always land on the same suggestion."""
    mastery = await _mastery_candidates(db, user_id)
    if mastery:
        return random.choice(mastery)
    completion = await _completion_candidates(db, user_id)
    if completion:
        return random.choice(completion)
    return None
