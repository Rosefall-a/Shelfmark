"""API routes for Collector Cards — a first-class entity separate from
Game (see database/models/card.py). A card represents one accomplishment
on one game; a game can eventually carry more than one card for genuinely
different accomplishments, though no UI builds that flow yet."""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.card import CardCreate, CardRead, CardUpdate
from src.core.auth import get_current_user
from src.database.models.achievement import Achievement
from src.database.models.bounty import Bounty
from src.database.models.card import Card
from src.database.models.game import Game, GameStatus
from src.database.models.user import User
from src.database.session import get_db
from src.features.cards.prestige_challenge import generate_prestige_challenge

router = APIRouter(prefix="/api/cards", tags=["cards"], dependencies=[Depends(get_current_user)])

_COMPLETED_STATUSES = (GameStatus.BEATEN, GameStatus.MASTERED)


async def _get_owned_game_or_404(game_id: UUID, db: AsyncSession, user_id: UUID) -> Game:
    game = await db.scalar(
        select(Game).where(Game.id == game_id, Game.user_id == user_id, Game.deleted_at.is_(None))
    )
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Game {game_id} not found"
        )
    return game


async def _get_card_or_404(card_id: UUID, db: AsyncSession, user_id: UUID) -> Card:
    card = await db.scalar(select(Card).where(Card.id == card_id, Card.user_id == user_id))
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Card {card_id} not found"
        )
    return card


@router.get("", response_model=list[CardRead])
async def list_cards(
    game_id: UUID | None = Query(default=None),
    set_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Card]:
    stmt = select(Card).where(Card.user_id == current_user.id)
    if game_id is not None:
        stmt = stmt.where(Card.game_id == game_id)
    if set_id is not None:
        stmt = stmt.where(Card.set_id == set_id)
    stmt = stmt.order_by(Card.archive_number)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=CardRead, status_code=status.HTTP_201_CREATED)
async def create_card(
    payload: CardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Card:
    game = await _get_owned_game_or_404(payload.game_id, db, current_user.id)
    if game.status not in _COMPLETED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A card can only be created for a game marked Beaten or Mastered.",
        )

    next_number = await db.scalar(
        select(func.coalesce(func.max(Card.archive_number), 0) + 1).where(
            Card.user_id == current_user.id
        )
    )
    card = Card(
        user_id=current_user.id,
        game_id=payload.game_id,
        set_id=payload.set_id,
        archive_number=next_number,
        rarity=payload.rarity,
        card_customization=payload.card_customization,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


@router.get("/{card_id}", response_model=CardRead)
async def get_card(
    card_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Card:
    return await _get_card_or_404(card_id, db, current_user.id)


@router.post("/{card_id}/prestige-challenge", response_model=CardRead)
async def generate_card_prestige_challenge(
    card_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Card:
    """Auto-generates the one Prestige challenge for this card and links
    it as a real Bounty — see features/cards/prestige_challenge.py. Never
    takes any input: the challenge is entirely system-picked from the
    game's own data, not typed or chosen by the user or by us per call."""
    card = await _get_card_or_404(card_id, db, current_user.id)
    if card.bounty_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This card already has a prestige challenge.",
        )

    game = await _get_owned_game_or_404(card.game_id, db, current_user.id)
    achievements = list(
        (await db.execute(select(Achievement).where(Achievement.game_id == game.id)))
        .scalars()
        .all()
    )
    if not achievements:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This game has no tracked achievements, so 100% completion can't be verified.",
        )
    if any(not a.unlocked for a in achievements):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Every achievement must be unlocked before a prestige challenge can be generated.",
        )

    challenge = generate_prestige_challenge(game, achievements)
    bounty = Bounty(
        user_id=current_user.id,
        title=challenge.title,
        description=challenge.description,
        type="challenge",
        game_id=game.id,
        progress_mode="binary",
        status="active",
        started_at=int(time.time()),
        auto_generated=True,
    )
    db.add(bounty)
    await db.flush()
    card.bounty_id = bounty.id
    card.updated_at = int(time.time())
    await db.commit()
    await db.refresh(card)
    return card


@router.patch("/{card_id}", response_model=CardRead)
async def update_card(
    card_id: UUID,
    payload: CardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Card:
    card = await _get_card_or_404(card_id, db, current_user.id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(card, field, value)
    card.updated_at = int(time.time())
    await db.commit()
    await db.refresh(card)
    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(
    card_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    card = await _get_card_or_404(card_id, db, current_user.id)
    await db.delete(card)
    await db.commit()
