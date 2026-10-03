"""API routes for Bounties — personal goals and challenges. Independent
from Achievements/Mastery/Cards/Prestige, but a bounty may optionally
target a game, a specific achievement, or a named collection to compute
its own progress automatically. Bounties never create those other
records; at most they read from them."""

import time
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user
from src.database.models.achievement import Achievement
from src.database.models.bounty import (
    AUTOMATIC_BOUNTY_TYPES,
    BOUNTY_DIFFICULTIES,
    BOUNTY_EVIDENCE_KINDS,
    BOUNTY_OBJECTIVE_KINDS,
    BOUNTY_PROGRESS_MODES,
    BOUNTY_STATUSES,
    BOUNTY_TYPES,
    Bounty,
    BountyEvidence,
    BountyJournalEntry,
    BountyObjective,
    BountyPointTransaction,
)
from src.database.models.game import Game, GameStatus
from src.database.models.media_item import MediaItem
from src.database.models.user import User
from src.database.session import get_db
from src.features.bounties.auto_propose import pick_bounty_proposal

router = APIRouter(
    prefix="/api/bounties", tags=["bounties"], dependencies=[Depends(get_current_user)]
)

_FINISHED_GAME_STATUSES = (GameStatus.BEATEN, GameStatus.MASTERED)

# how the timer-gated auto-proposal is throttled — at most this many
# system-proposed bounties active at once, and at least this long since
# the last one, so the board doesn't flood with suggestions
AUTO_PROPOSE_INTERVAL_SECONDS = 7 * 24 * 60 * 60
MAX_ACTIVE_AUTO_BOUNTIES = 2

# the type dictates how progress is measured for the 4 automatic types —
# not a user choice, since e.g. "mastery" is inherently a percentage and
# "completion" is inherently a yes/no
_AUTOMATIC_PROGRESS_MODES = {
    "completion": "binary",
    "mastery": "percentage",
    "achievement": "binary",
    "collection": "numeric",
}


class BountyCreate(BaseModel):
    title: str
    description: str | None = None
    type: str = "custom"
    difficulty: str | None = None
    status: str = "active"
    game_id: UUID | None = None
    # the achievement's current row id — achievements are deleted and
    # reinserted whole on every sync, so this id is resolved to the
    # (provider, external_id) pair once at creation time and only that
    # stable pair is stored
    target_achievement_id: UUID | None = None
    target_collection_name: str | None = None
    progress_mode: str = "binary"
    progress_target: Decimal | None = None
    points_reward: int = Field(default=0, ge=0)
    target_date: int | None = None
    required_evidence_kinds: list[str] = Field(default_factory=list)


class BountyUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    difficulty: str | None = None
    points_reward: int | None = Field(default=None, ge=0)
    target_date: int | None = None
    progress_value: Decimal | None = None
    progress_target: Decimal | None = None
    required_evidence_kinds: list[str] | None = None


class ObjectiveCreate(BaseModel):
    title: str
    kind: str = "checkbox"
    progress_target: Decimal | None = None
    target_achievement_id: UUID | None = None


class ObjectiveUpdate(BaseModel):
    title: str | None = None
    done: bool | None = None
    progress_value: Decimal | None = None
    progress_target: Decimal | None = None


class EvidenceCreate(BaseModel):
    kind: str
    media_item_id: UUID | None = None
    text: str | None = None
    url: str | None = None


class JournalCreate(BaseModel):
    text: str


def _validate_choice(value: str, allowed: tuple[str, ...], field: str) -> None:
    if value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field} '{value}'. Must be one of: {', '.join(allowed)}.",
        )


async def _recompute_automatic_progress(db: AsyncSession, bounty: Bounty) -> None:
    """Refreshes progress_value/progress_target on an automatic-type
    bounty from real data. Read-only with respect to everything except
    the bounty row itself — never touches the underlying game/achievement."""
    if bounty.type == "completion":
        if bounty.game_id is None:
            return
        game = await db.get(Game, bounty.game_id)
        bounty.progress_value = (
            Decimal(100) if game and game.status in _FINISHED_GAME_STATUSES else Decimal(0)
        )
        bounty.progress_target = Decimal(100)

    elif bounty.type == "mastery":
        if bounty.game_id is None:
            return
        total = await db.scalar(select(func.count()).where(Achievement.game_id == bounty.game_id))
        unlocked = await db.scalar(
            select(func.count()).where(
                Achievement.game_id == bounty.game_id, Achievement.unlocked.is_(True)
            )
        )
        total = total or 0
        unlocked = unlocked or 0
        bounty.progress_target = Decimal(100)
        bounty.progress_value = (
            (Decimal(unlocked) / Decimal(total) * 100) if total > 0 else Decimal(0)
        )

    elif bounty.type == "achievement":
        if not (
            bounty.game_id
            and bounty.target_achievement_provider
            and bounty.target_achievement_external_id
        ):
            return
        achievement = await db.scalar(
            select(Achievement).where(
                Achievement.game_id == bounty.game_id,
                Achievement.provider == bounty.target_achievement_provider,
                Achievement.external_id == bounty.target_achievement_external_id,
            )
        )
        bounty.progress_target = Decimal(100)
        bounty.progress_value = Decimal(100) if achievement and achievement.unlocked else Decimal(0)

    elif bounty.type == "collection":
        if not bounty.target_collection_name:
            return
        result = await db.execute(
            select(Game.status).where(
                Game.user_id == bounty.user_id,
                Game.deleted_at.is_(None),
                Game.collections.any(bounty.target_collection_name),  # type: ignore[arg-type]  # ARRAY.any(scalar) is valid at runtime; mypy resolves the relationship .any() overload instead
            )
        )
        statuses = result.scalars().all()
        total = len(statuses)
        done = sum(1 for s in statuses if s in _FINISHED_GAME_STATUSES)
        bounty.progress_target = Decimal(total)
        bounty.progress_value = Decimal(done)


async def _load_objectives(db: AsyncSession, bounty_id: UUID) -> list[BountyObjective]:
    result = await db.execute(
        select(BountyObjective)
        .where(BountyObjective.bounty_id == bounty_id)
        .order_by(BountyObjective.created_at)
    )
    return list(result.scalars().all())


async def _objective_is_done(db: AsyncSession, bounty: Bounty, objective: BountyObjective) -> bool:
    if objective.kind == "checkbox":
        return objective.done
    if objective.kind == "numeric":
        return (
            objective.progress_target is not None
            and objective.progress_target > 0
            and objective.progress_value >= objective.progress_target
        )
    if objective.kind == "achievement":
        if not (
            bounty.game_id
            and objective.target_achievement_provider
            and objective.target_achievement_external_id
        ):
            return False
        achievement = await db.scalar(
            select(Achievement).where(
                Achievement.game_id == bounty.game_id,
                Achievement.provider == objective.target_achievement_provider,
                Achievement.external_id == objective.target_achievement_external_id,
            )
        )
        return bool(achievement and achievement.unlocked)
    return False


async def _sync_progress_from_objectives(
    db: AsyncSession, bounty: Bounty, objectives: list[BountyObjective]
) -> None:
    """Objectives, when present, always drive the bounty's overall
    progress — overriding whatever `type`'s own automatic logic would
    otherwise compute. A bounty with objectives is progressed by checking
    them off, regardless of what it targets."""
    total = len(objectives)
    done_count = sum([1 for o in objectives if await _objective_is_done(db, bounty, o)])
    bounty.progress_mode = "numeric"
    bounty.progress_target = Decimal(total)
    bounty.progress_value = Decimal(done_count)


def _is_progress_complete(bounty: Bounty) -> bool:
    if bounty.progress_mode == "binary":
        return bounty.progress_value >= 100
    if bounty.progress_target is None or bounty.progress_target <= 0:
        return False
    return bounty.progress_value >= bounty.progress_target


async def _award_points_once(db: AsyncSession, bounty: Bounty) -> None:
    if bounty.points_reward <= 0:
        return
    # checked explicitly rather than caught as an IntegrityError, so a
    # duplicate-award attempt never rolls back the status/completed_at
    # changes already staged alongside it in the same transaction
    existing = await db.scalar(
        select(BountyPointTransaction.id).where(BountyPointTransaction.bounty_id == bounty.id)
    )
    if existing is not None:
        return
    db.add(
        BountyPointTransaction(
            user_id=bounty.user_id,
            bounty_id=bounty.id,
            amount=bounty.points_reward,
            reason=bounty.title,
        )
    )


async def _complete_bounty(db: AsyncSession, bounty: Bounty) -> None:
    bounty.status = "completed"
    bounty.completed_at = int(time.time())
    await _award_points_once(db, bounty)
    await db.commit()


async def _sync_bounty(
    db: AsyncSession, bounty: Bounty, objectives: list[BountyObjective] | None = None
) -> list[BountyObjective]:
    """Called lazily whenever a bounty is read, and right after any
    objective is mutated. A bounty with objectives gets its progress
    derived from how many are done; otherwise an automatic-type bounty
    still refreshes from real data as before. Either way, reaching the
    target auto-completes it — no manual checkmark, no scheduled job.
    Returns the objectives it loaded/used, so callers building a response
    don't have to fetch them again."""
    if objectives is None:
        objectives = await _load_objectives(db, bounty.id)
    if bounty.status != "active":
        return objectives
    if objectives:
        await _sync_progress_from_objectives(db, bounty, objectives)
    elif bounty.type in AUTOMATIC_BOUNTY_TYPES:
        await _recompute_automatic_progress(db, bounty)
    else:
        return objectives
    if _is_progress_complete(bounty):
        await _complete_bounty(db, bounty)
    else:
        await db.commit()
    return objectives


async def _objective_to_dict(db: AsyncSession, bounty: Bounty, objective: BountyObjective) -> dict:
    return {
        "id": str(objective.id),
        "title": objective.title,
        "kind": objective.kind,
        "done": await _objective_is_done(db, bounty, objective),
        "progress_value": float(objective.progress_value),
        "progress_target": float(objective.progress_target)
        if objective.progress_target is not None
        else None,
        "target_achievement_provider": objective.target_achievement_provider,
        "target_achievement_external_id": objective.target_achievement_external_id,
        "created_at": objective.created_at,
    }


async def _load_evidence(db: AsyncSession, bounty_id: UUID) -> list[BountyEvidence]:
    result = await db.execute(
        select(BountyEvidence)
        .where(BountyEvidence.bounty_id == bounty_id)
        .order_by(BountyEvidence.created_at)
    )
    return list(result.scalars().all())


async def _evidence_to_dict(
    db: AsyncSession, evidence: BountyEvidence, game_id: UUID | None
) -> dict:
    media_url = None
    media_filename = None
    if evidence.media_item_id is not None:
        media_item = await db.get(MediaItem, evidence.media_item_id)
        if media_item is not None and game_id is not None:
            media_filename = media_item.filename
            media_url = f"/api/game/{game_id}/screenshots/{media_item.kind}/{media_item.filename}"
    return {
        "id": str(evidence.id),
        "kind": evidence.kind,
        "media_item_id": str(evidence.media_item_id) if evidence.media_item_id else None,
        "media_url": media_url,
        "media_filename": media_filename,
        "text": evidence.text,
        "url": evidence.url,
        "created_at": evidence.created_at,
    }


async def _load_journal(db: AsyncSession, bounty_id: UUID) -> list[BountyJournalEntry]:
    result = await db.execute(
        select(BountyJournalEntry)
        .where(BountyJournalEntry.bounty_id == bounty_id)
        .order_by(BountyJournalEntry.created_at)
    )
    return list(result.scalars().all())


def _journal_to_dict(entry: BountyJournalEntry) -> dict:
    return {"id": str(entry.id), "text": entry.text, "created_at": entry.created_at}


async def _load_evidence_batch(
    db: AsyncSession, bounty_ids: list[UUID]
) -> dict[UUID, list[BountyEvidence]]:
    if not bounty_ids:
        return {}
    result = await db.execute(
        select(BountyEvidence)
        .where(BountyEvidence.bounty_id.in_(bounty_ids))
        .order_by(BountyEvidence.created_at)
    )
    by_bounty: dict[UUID, list[BountyEvidence]] = {}
    for row in result.scalars().all():
        by_bounty.setdefault(row.bounty_id, []).append(row)
    return by_bounty


async def _load_journal_batch(
    db: AsyncSession, bounty_ids: list[UUID]
) -> dict[UUID, list[BountyJournalEntry]]:
    if not bounty_ids:
        return {}
    result = await db.execute(
        select(BountyJournalEntry)
        .where(BountyJournalEntry.bounty_id.in_(bounty_ids))
        .order_by(BountyJournalEntry.created_at)
    )
    by_bounty: dict[UUID, list[BountyJournalEntry]] = {}
    for row in result.scalars().all():
        by_bounty.setdefault(row.bounty_id, []).append(row)
    return by_bounty


async def _bounty_to_dict(
    db: AsyncSession,
    bounty: Bounty,
    game: Game | None,
    achievement_name: str | None = None,
    objectives: list[BountyObjective] | None = None,
    evidence: list[BountyEvidence] | None = None,
    journal: list[BountyJournalEntry] | None = None,
) -> dict:
    if objectives is None:
        objectives = await _load_objectives(db, bounty.id)
    if evidence is None:
        evidence = await _load_evidence(db, bounty.id)
    if journal is None:
        journal = await _load_journal(db, bounty.id)
    return {
        "id": str(bounty.id),
        "title": bounty.title,
        "description": bounty.description,
        "type": bounty.type,
        "difficulty": bounty.difficulty,
        "status": bounty.status,
        "auto_generated": bounty.auto_generated,
        "game_id": str(bounty.game_id) if bounty.game_id else None,
        "game_title": game.title if game else None,
        "target_achievement_provider": bounty.target_achievement_provider,
        "target_achievement_external_id": bounty.target_achievement_external_id,
        "target_achievement_name": achievement_name,
        "target_collection_name": bounty.target_collection_name,
        "progress_mode": bounty.progress_mode,
        "progress_value": float(bounty.progress_value),
        "progress_target": float(bounty.progress_target)
        if bounty.progress_target is not None
        else None,
        "points_reward": bounty.points_reward,
        "required_evidence_kinds": bounty.required_evidence_kinds,
        "target_date": bounty.target_date,
        "created_at": bounty.created_at,
        "started_at": bounty.started_at,
        "completed_at": bounty.completed_at,
        "objectives": [await _objective_to_dict(db, bounty, o) for o in objectives],
        "evidence": [await _evidence_to_dict(db, e, bounty.game_id) for e in evidence],
        "journal": [_journal_to_dict(j) for j in journal],
    }


async def _load_games(db: AsyncSession, bounties: list[Bounty]) -> dict[UUID, Game]:
    game_ids = {b.game_id for b in bounties if b.game_id is not None}
    if not game_ids:
        return {}
    result = await db.execute(select(Game).where(Game.id.in_(game_ids)))
    return {g.id: g for g in result.scalars().all()}


async def _load_achievement_name(db: AsyncSession, bounty: Bounty) -> str | None:
    if (
        bounty.type != "achievement"
        or not bounty.game_id
        or not bounty.target_achievement_external_id
    ):
        return None
    achievement = await db.scalar(
        select(Achievement).where(
            Achievement.game_id == bounty.game_id,
            Achievement.provider == bounty.target_achievement_provider,
            Achievement.external_id == bounty.target_achievement_external_id,
        )
    )
    return achievement.name if achievement else None


async def _maybe_auto_propose(db: AsyncSession, user_id: UUID) -> None:
    """Checked lazily whenever the caller lists their bounties — no
    scheduled job/worker, matching how this feature has worked from the
    start, but now genuinely time-gated: proposes at most one new bounty
    per AUTO_PROPOSE_INTERVAL_SECONDS, and never more than
    MAX_ACTIVE_AUTO_BOUNTIES active system-proposed bounties at once.

    Two tabs/requests can call this within the same instant (e.g. two
    widgets both listing bounties on page load) — an advisory lock scoped
    to this transaction and this user serializes those so the cooldown
    check and the insert it guards can't both pass in a race, which would
    otherwise let two proposals slip through in one moment instead of
    one every INTERVAL as intended."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:uid))"), {"uid": str(user_id)})

    active_auto_count = await db.scalar(
        select(func.count()).where(
            Bounty.user_id == user_id, Bounty.auto_generated.is_(True), Bounty.status == "active"
        )
    )
    if (active_auto_count or 0) >= MAX_ACTIVE_AUTO_BOUNTIES:
        return

    last_auto_at = await db.scalar(
        select(func.max(Bounty.created_at)).where(
            Bounty.user_id == user_id, Bounty.auto_generated.is_(True)
        )
    )
    if last_auto_at is not None and int(time.time()) - last_auto_at < AUTO_PROPOSE_INTERVAL_SECONDS:
        return

    proposal = await pick_bounty_proposal(db, user_id)
    if proposal is None:
        return

    bounty = Bounty(
        user_id=user_id,
        title=proposal.title,
        type=proposal.type,
        game_id=proposal.game_id,
        progress_mode=_AUTOMATIC_PROGRESS_MODES[proposal.type],
        points_reward=proposal.points_reward,
        status="active",
        started_at=int(time.time()),
        auto_generated=True,
    )
    db.add(bounty)
    await db.commit()


@router.get("")
async def list_bounties(
    status_query: str | None = Query(default=None, alias="status"),
    type_query: str | None = Query(default=None, alias="type"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _maybe_auto_propose(db, current_user.id)

    query = select(Bounty).where(Bounty.user_id == current_user.id)
    if status_query:
        query = query.where(Bounty.status == status_query)
    if type_query:
        query = query.where(Bounty.type == type_query)
    query = query.order_by(Bounty.created_at.desc())
    bounties = list((await db.execute(query)).scalars().all())

    objectives_by_bounty: dict[UUID, list[BountyObjective]] = {}
    for bounty in bounties:
        objectives_by_bounty[bounty.id] = await _sync_bounty(db, bounty)

    bounty_ids = [b.id for b in bounties]
    games_by_id = await _load_games(db, bounties)
    evidence_by_bounty = await _load_evidence_batch(db, bounty_ids)
    journal_by_bounty = await _load_journal_batch(db, bounty_ids)
    return {
        "bounties": [
            await _bounty_to_dict(
                db,
                b,
                games_by_id.get(b.game_id) if b.game_id is not None else None,
                await _load_achievement_name(db, b),
                objectives_by_bounty.get(b.id),
                evidence_by_bounty.get(b.id, []),
                journal_by_bounty.get(b.id, []),
            )
            for b in bounties
        ]
    }


@router.get("/points/total")
async def get_points_total(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    total = await db.scalar(
        select(func.coalesce(func.sum(BountyPointTransaction.amount), 0)).where(
            BountyPointTransaction.user_id == current_user.id
        )
    )
    return {"total": int(total or 0)}


@router.get("/points/history")
async def get_points_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    result = await db.execute(
        select(BountyPointTransaction)
        .where(BountyPointTransaction.user_id == current_user.id)
        .order_by(BountyPointTransaction.created_at.desc())
    )
    transactions = result.scalars().all()
    return {
        "transactions": [
            {
                "id": str(t.id),
                "bounty_id": str(t.bounty_id),
                "amount": t.amount,
                "reason": t.reason,
                "created_at": t.created_at,
            }
            for t in transactions
        ]
    }


@router.get("/random")
async def get_random_bounty_proposal(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """The Random Bounty / reroll button — runs the same picker the timer
    uses, but on demand and without the cooldown/cap, and returns a
    preview rather than persisting anything. Calling it again ('Reroll')
    just runs the picker again; accepting it is a normal POST /api/bounties
    with these fields."""
    proposal = await pick_bounty_proposal(db, current_user.id)
    if proposal is None:
        return {"proposal": None}
    game = await db.get(Game, proposal.game_id)
    return {
        "proposal": {
            "title": proposal.title,
            "type": proposal.type,
            "game_id": str(proposal.game_id),
            "game_title": game.title if game else None,
            "points_reward": proposal.points_reward,
        }
    }


@router.get("/{bounty_id}")
async def get_bounty(
    bounty_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await db.scalar(
        select(Bounty).where(Bounty.id == bounty_id, Bounty.user_id == current_user.id)
    )
    if bounty is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bounty not found.")
    objectives = await _sync_bounty(db, bounty)
    game = await db.get(Game, bounty.game_id) if bounty.game_id else None
    return {
        "bounty": await _bounty_to_dict(
            db, bounty, game, await _load_achievement_name(db, bounty), objectives
        )
    }


@router.post("")
async def create_bounty(
    body: BountyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required.")
    _validate_choice(body.type, BOUNTY_TYPES, "type")
    _validate_choice(body.status, BOUNTY_STATUSES, "status")
    progress_mode = _AUTOMATIC_PROGRESS_MODES.get(body.type, body.progress_mode)
    _validate_choice(progress_mode, BOUNTY_PROGRESS_MODES, "progress_mode")
    if body.difficulty is not None:
        _validate_choice(body.difficulty, BOUNTY_DIFFICULTIES, "difficulty")
    for kind in body.required_evidence_kinds:
        _validate_choice(kind, BOUNTY_EVIDENCE_KINDS, "required_evidence_kinds")

    game = None
    if body.game_id is not None:
        game = await db.get(Game, body.game_id)
        if game is None or game.deleted_at is not None or game.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found.")

    if body.type in AUTOMATIC_BOUNTY_TYPES and body.game_id is None and body.type != "collection":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{body.type}' bounties need a target game.",
        )
    if body.type == "collection" and not body.target_collection_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collection bounties need a target collection.",
        )

    target_achievement_provider = None
    target_achievement_external_id = None
    if body.type == "achievement":
        if body.target_achievement_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Achievement bounties need a target achievement.",
            )
        achievement = await db.get(Achievement, body.target_achievement_id)
        if achievement is None or achievement.game_id != body.game_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Achievement not found for that game."
            )
        target_achievement_provider = achievement.provider
        target_achievement_external_id = achievement.external_id

    bounty = Bounty(
        user_id=current_user.id,
        title=title,
        description=body.description,
        type=body.type,
        difficulty=body.difficulty,
        status=body.status,
        game_id=body.game_id,
        target_achievement_provider=target_achievement_provider,
        target_achievement_external_id=target_achievement_external_id,
        target_collection_name=body.target_collection_name,
        progress_mode=progress_mode,
        progress_target=body.progress_target,
        points_reward=body.points_reward,
        target_date=body.target_date,
        required_evidence_kinds=body.required_evidence_kinds,
        started_at=int(time.time()) if body.status == "active" else None,
    )
    db.add(bounty)
    await db.commit()
    await db.refresh(bounty)
    objectives = await _sync_bounty(db, bounty)
    return {
        "bounty": await _bounty_to_dict(
            db, bounty, game, await _load_achievement_name(db, bounty), objectives
        )
    }


@router.patch("/{bounty_id}")
async def update_bounty(
    bounty_id: UUID,
    body: BountyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await db.scalar(
        select(Bounty).where(Bounty.id == bounty_id, Bounty.user_id == current_user.id)
    )
    if bounty is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bounty not found.")
    if bounty.status in ("completed", "abandoned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Can't edit a finished bounty."
        )

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required."
            )
        bounty.title = title
    if body.description is not None:
        bounty.description = body.description
    if body.difficulty is not None:
        _validate_choice(body.difficulty, BOUNTY_DIFFICULTIES, "difficulty")
        bounty.difficulty = body.difficulty
    if body.points_reward is not None:
        bounty.points_reward = body.points_reward
    if body.target_date is not None:
        bounty.target_date = body.target_date
    if body.required_evidence_kinds is not None:
        for kind in body.required_evidence_kinds:
            _validate_choice(kind, BOUNTY_EVIDENCE_KINDS, "required_evidence_kinds")
        bounty.required_evidence_kinds = body.required_evidence_kinds
    # manual progress only makes sense for a bounty with no objectives and
    # a non-automatic type — anything else gets overwritten on next read
    existing_objectives = await _load_objectives(db, bounty.id)
    if not existing_objectives and bounty.type not in AUTOMATIC_BOUNTY_TYPES:
        if body.progress_value is not None:
            bounty.progress_value = body.progress_value
        if body.progress_target is not None:
            bounty.progress_target = body.progress_target

    await db.commit()
    game = await db.get(Game, bounty.game_id) if bounty.game_id else None
    return {
        "bounty": await _bounty_to_dict(
            db, bounty, game, await _load_achievement_name(db, bounty), existing_objectives
        )
    }


async def _get_own_bounty(db: AsyncSession, bounty_id: UUID, user_id: UUID) -> Bounty:
    bounty = await db.scalar(
        select(Bounty).where(Bounty.id == bounty_id, Bounty.user_id == user_id)
    )
    if bounty is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bounty not found.")
    return bounty


@router.post("/{bounty_id}/complete")
async def complete_bounty(
    bounty_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    await _complete_bounty(db, bounty)
    return {"status": "completed", "id": str(bounty_id)}


@router.post("/{bounty_id}/pause")
async def pause_bounty(
    bounty_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    if bounty.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only an active bounty can be paused."
        )
    bounty.status = "paused"
    await db.commit()
    return {"status": "paused", "id": str(bounty_id)}


@router.post("/{bounty_id}/resume")
async def resume_bounty(
    bounty_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    if bounty.status not in ("paused", "not_started"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only a paused bounty can be resumed."
        )
    bounty.status = "active"
    if bounty.started_at is None:
        bounty.started_at = int(time.time())
    await db.commit()
    return {"status": "active", "id": str(bounty_id)}


@router.post("/{bounty_id}/abandon")
async def abandon_bounty(
    bounty_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    bounty.status = "abandoned"
    await db.commit()
    return {"status": "abandoned", "id": str(bounty_id)}


@router.delete("/{bounty_id}")
async def delete_bounty(
    bounty_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    if bounty.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completed bounties are kept for history — abandon it instead if you want it out of the way.",
        )
    await db.delete(bounty)
    await db.commit()
    return {"status": "deleted", "id": str(bounty_id)}


# --- objectives -----------------------------------------------------------


@router.post("/{bounty_id}/objectives")
async def create_objective(
    bounty_id: UUID,
    body: ObjectiveCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    title = body.title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Objective title is required."
        )
    _validate_choice(body.kind, BOUNTY_OBJECTIVE_KINDS, "kind")

    target_achievement_provider = None
    target_achievement_external_id = None
    if body.kind == "achievement":
        if body.target_achievement_id is None or bounty.game_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Achievement objectives need the bounty to have a target game and an achievement picked.",
            )
        achievement = await db.get(Achievement, body.target_achievement_id)
        if achievement is None or achievement.game_id != bounty.game_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Achievement not found for that game."
            )
        target_achievement_provider = achievement.provider
        target_achievement_external_id = achievement.external_id

    objective = BountyObjective(
        bounty_id=bounty.id,
        title=title,
        kind=body.kind,
        progress_target=body.progress_target,
        target_achievement_provider=target_achievement_provider,
        target_achievement_external_id=target_achievement_external_id,
    )
    db.add(objective)
    await db.commit()
    await db.refresh(objective)

    objectives = await _sync_bounty(db, bounty)
    game = await db.get(Game, bounty.game_id) if bounty.game_id else None
    return {
        "objective": await _objective_to_dict(db, bounty, objective),
        "bounty": await _bounty_to_dict(
            db, bounty, game, await _load_achievement_name(db, bounty), objectives
        ),
    }


@router.patch("/{bounty_id}/objectives/{objective_id}")
async def update_objective(
    bounty_id: UUID,
    objective_id: UUID,
    body: ObjectiveUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    objective = await db.scalar(
        select(BountyObjective).where(
            BountyObjective.id == objective_id, BountyObjective.bounty_id == bounty.id
        )
    )
    if objective is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found.")

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Objective title is required."
            )
        objective.title = title
    if body.done is not None and objective.kind == "checkbox":
        objective.done = body.done
    if body.progress_value is not None and objective.kind == "numeric":
        objective.progress_value = body.progress_value
    if body.progress_target is not None and objective.kind == "numeric":
        objective.progress_target = body.progress_target
    await db.commit()

    objectives = await _sync_bounty(db, bounty)
    game = await db.get(Game, bounty.game_id) if bounty.game_id else None
    return {
        "objective": await _objective_to_dict(db, bounty, objective),
        "bounty": await _bounty_to_dict(
            db, bounty, game, await _load_achievement_name(db, bounty), objectives
        ),
    }


@router.delete("/{bounty_id}/objectives/{objective_id}")
async def delete_objective(
    bounty_id: UUID,
    objective_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    objective = await db.scalar(
        select(BountyObjective).where(
            BountyObjective.id == objective_id, BountyObjective.bounty_id == bounty.id
        )
    )
    if objective is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found.")
    await db.delete(objective)
    await db.commit()
    await _sync_bounty(db, bounty)
    return {"status": "deleted", "id": str(objective_id)}


# --- evidence ---------------------------------------------------------


@router.post("/{bounty_id}/evidence")
async def create_evidence(
    bounty_id: UUID,
    body: EvidenceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    _validate_choice(body.kind, BOUNTY_EVIDENCE_KINDS, "kind")

    if body.kind in ("screenshot", "clip", "document"):
        if body.media_item_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{body.kind}' evidence needs a media item.",
            )
        media_item = await db.get(MediaItem, body.media_item_id)
        if (
            media_item is None
            or media_item.deleted_at is not None
            or media_item.game_id != bounty.game_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Media item not found for that game."
            )
    elif body.kind == "note":
        if not body.text or not body.text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Note evidence needs text."
            )
    elif body.kind == "link":
        if not body.url or not body.url.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Link evidence needs a URL."
            )

    evidence = BountyEvidence(
        bounty_id=bounty.id,
        kind=body.kind,
        media_item_id=body.media_item_id,
        text=body.text,
        url=body.url,
    )
    db.add(evidence)
    await db.commit()
    await db.refresh(evidence)
    return {"evidence": await _evidence_to_dict(db, evidence, bounty.game_id)}


@router.delete("/{bounty_id}/evidence/{evidence_id}")
async def delete_evidence(
    bounty_id: UUID,
    evidence_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    evidence = await db.scalar(
        select(BountyEvidence).where(
            BountyEvidence.id == evidence_id, BountyEvidence.bounty_id == bounty.id
        )
    )
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found.")
    await db.delete(evidence)
    await db.commit()
    return {"status": "deleted", "id": str(evidence_id)}


# --- journal ------------------------------------------------------------


@router.post("/{bounty_id}/journal")
async def create_journal_entry(
    bounty_id: UUID,
    body: JournalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    text = body.text.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Journal entry can't be empty."
        )
    entry = BountyJournalEntry(bounty_id=bounty.id, text=text)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {"entry": _journal_to_dict(entry)}


@router.delete("/{bounty_id}/journal/{entry_id}")
async def delete_journal_entry(
    bounty_id: UUID,
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bounty = await _get_own_bounty(db, bounty_id, current_user.id)
    entry = await db.scalar(
        select(BountyJournalEntry).where(
            BountyJournalEntry.id == entry_id, BountyJournalEntry.bounty_id == bounty.id
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Journal entry not found."
        )
    await db.delete(entry)
    await db.commit()
    return {"status": "deleted", "id": str(entry_id)}
