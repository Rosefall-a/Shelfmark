"""API routes for Sets — a real, position-aware grouping of Cards (not
Games directly, see database/models/set.py and card.py), distinct from the
unrelated Collections smart-grouping feature on Game."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.set import SetCreate, SetDetailRead, SetRead, SetUpdate
from src.core.auth import get_current_user
from src.database.models.card import Card
from src.database.models.set import Set
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(prefix="/api/sets", tags=["sets"], dependencies=[Depends(get_current_user)])


async def _get_set_or_404(set_id: UUID, db: AsyncSession, user_id: UUID) -> Set:
    set_row = await db.scalar(select(Set).where(Set.id == set_id, Set.user_id == user_id))
    if set_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Set {set_id} not found")
    return set_row


async def _card_counts(db: AsyncSession, set_ids: list[UUID]) -> dict[UUID, int]:
    if not set_ids:
        return {}
    stmt = (
        select(Card.set_id, func.count(Card.id))
        .where(Card.set_id.in_(set_ids))
        .group_by(Card.set_id)
    )
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


def _to_read(set_row: Set, card_count: int) -> SetRead:
    is_complete = set_row.target_total is not None and card_count >= set_row.target_total
    return SetRead(
        id=set_row.id,
        user_id=set_row.user_id,
        name=set_row.name,
        description=set_row.description,
        target_total=set_row.target_total,
        created_at=set_row.created_at,
        updated_at=set_row.updated_at,
        card_count=card_count,
        is_complete=is_complete,
    )


@router.get("", response_model=list[SetRead])
async def list_sets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SetRead]:
    result = await db.execute(select(Set).where(Set.user_id == current_user.id).order_by(Set.name))
    all_sets = result.scalars().all()
    counts = await _card_counts(db, [s.id for s in all_sets])
    return [_to_read(s, counts.get(s.id, 0)) for s in all_sets]


@router.post("", response_model=SetRead, status_code=status.HTTP_201_CREATED)
async def create_set(
    payload: SetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SetRead:
    set_row = Set(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        target_total=payload.target_total,
    )
    db.add(set_row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A set named '{payload.name}' already exists.",
        ) from exc
    await db.refresh(set_row)
    return _to_read(set_row, 0)


async def _get_set_detail(set_id: UUID, db: AsyncSession, user_id: UUID) -> SetDetailRead:
    set_row = await _get_set_or_404(set_id, db, user_id)
    cards_result = await db.execute(
        select(Card)
        .where(Card.set_id == set_id, Card.user_id == user_id)
        .order_by(Card.archive_number)
    )
    cards = cards_result.scalars().all()
    base = _to_read(set_row, len(cards))
    return SetDetailRead(**base.model_dump(), cards=cards)  # type: ignore[arg-type]


@router.get("/{set_id}", response_model=SetDetailRead)
async def get_set(
    set_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SetDetailRead:
    return await _get_set_detail(set_id, db, current_user.id)


@router.patch("/{set_id}", response_model=SetRead)
async def update_set(
    set_id: UUID,
    payload: SetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SetRead:
    set_row = await _get_set_or_404(set_id, db, current_user.id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(set_row, field, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A set named '{set_row.name}' already exists.",
        ) from exc
    await db.refresh(set_row)

    counts = await _card_counts(db, [set_row.id])
    return _to_read(set_row, counts.get(set_row.id, 0))


@router.delete("/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_set(
    set_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    set_row = await _get_set_or_404(set_id, db, current_user.id)
    await db.delete(set_row)
    await db.commit()
