# pylint: disable=missing-function-docstring
"""Custom lists across movies, TV shows and anime: manual lists (ordered,
with a pickable cover) and smart lists (a saved filter evaluated against
the whole library on every read — the media-side twin of the Games
side's Smart Collections)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.media_extras import _MODEL_BY_TYPE, _resolve_media
from src.api.schemas.media_extras import (
    MediaListCreate,
    MediaListDetailRead,
    MediaListItemCreate,
    MediaListItemRead,
    MediaListRead,
    MediaListReorder,
    MediaListsOrder,
    MediaListUpdate,
)
from src.core.auth import get_current_user
from src.core.preferences import load_preferences
from src.core.titles import display_title
from src.database.models.media_extras import MediaList, MediaListItem, MediaType
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(prefix="/api", tags=["media-lists"], dependencies=[Depends(get_current_user)])

# Same collapse the frontend's utils/mediaStatus.ts does — a smart rule
# speaks in the five buckets users actually see, not the 8 raw statuses.
_BUCKET_STATUSES: dict[str, set[str]] = {
    "plan": {"WISHLIST", "WATCHLIST"},
    "hold": {"BACKLOG"},
    "watching": {"IN_PROGRESS", "REWATCH"},
    "completed": {"WATCHED", "FAVORITE"},
    "dropped": {"DROPPED"},
}


def _status_str(media: Any) -> str:
    return media.status.value if hasattr(media.status, "value") else str(media.status)


def _item_dict(
    item_id: UUID, media_type: str, media: Any, added_at: int, language: str = "english"
) -> dict:
    return {
        "id": item_id,
        "media_type": media_type,
        "media_id": media.id,
        "title": display_title(media, language),
        "poster_url": media.poster_url,
        "status": _status_str(media),
        "added_at": added_at,
    }


async def _resolve_smart_items(
    rule: dict, user_id: UUID, db: AsyncSession, language: str
) -> list[dict]:
    wanted_types = rule.get("media_types") or list(_MODEL_BY_TYPE)
    allowed_statuses: set[str] | None = None
    if rule.get("status_buckets"):
        allowed_statuses = set()
        for bucket in rule["status_buckets"]:
            allowed_statuses |= _BUCKET_STATUSES.get(bucket, set())
    genre = (rule.get("genre") or "").strip().lower()
    min_score = rule.get("min_score")
    favorite = rule.get("favorite")

    result: list[dict] = []
    for media_type in wanted_types:
        model = _MODEL_BY_TYPE.get(media_type)
        if model is None:
            continue
        rows = (
            (
                await db.execute(
                    select(model).where(model.user_id == user_id, model.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        for media in rows:
            if allowed_statuses is not None and _status_str(media) not in allowed_statuses:
                continue
            if favorite is not None and bool(media.favorite) != favorite:
                continue
            if genre and genre not in [g.lower() for g in (media.genres or [])]:
                continue
            if min_score is not None and (
                media.rating_overall is None or float(media.rating_overall) < min_score
            ):
                continue
            # a smart list has no membership rows, so the media's own id
            # stands in for the item id
            result.append(_item_dict(media.id, media_type, media, 0, language))
    result.sort(key=lambda i: i["title"].lower())
    return result


async def _resolve_manual_items(lst: MediaList, db: AsyncSession, language: str) -> list[dict]:
    items = (
        (
            await db.execute(
                select(MediaListItem)
                .where(MediaListItem.list_id == lst.id)
                .order_by(MediaListItem.position.asc(), MediaListItem.added_at.desc())
            )
        )
        .scalars()
        .all()
    )
    resolved: list[dict] = []
    for item in items:
        model = _MODEL_BY_TYPE.get(item.media_type)
        media = await db.scalar(select(model).where(model.id == item.media_id)) if model else None
        if media is None or getattr(media, "deleted_at", None) is not None:
            continue
        resolved.append(_item_dict(item.id, item.media_type, media, item.added_at, language))
    return resolved


async def _resolve_items(lst: MediaList, user_id: UUID, db: AsyncSession) -> list[dict]:
    language = str((await load_preferences(db, user_id))["title_language"])
    if lst.smart_rule is not None:
        return await _resolve_smart_items(lst.smart_rule, user_id, db, language)
    return await _resolve_manual_items(lst, db, language)


def _summary(lst: MediaList, items: list[dict]) -> dict:
    ordered = list(items)
    if lst.cover_media_id is not None:
        ordered.sort(key=lambda i: 0 if i["media_id"] == lst.cover_media_id else 1)
    return {
        "id": lst.id,
        "name": lst.name,
        "description": lst.description,
        "item_count": len(items),
        "is_smart": lst.smart_rule is not None,
        "is_system": lst.is_system,
        "pinned": lst.pinned,
        "position": lst.position,
        "type_counts": {
            t: sum(1 for i in items if i["media_type"] == t) for t in ("movie", "tv", "anime")
        },
        "smart_rule": lst.smart_rule,
        "cover_media_id": lst.cover_media_id,
        "preview_posters": [i["poster_url"] for i in ordered[:4]],
        "created_at": lst.created_at,
        "updated_at": lst.updated_at,
    }


async def _get_list_or_404(list_id: UUID, user_id: UUID, db: AsyncSession) -> MediaList:
    lst = await db.scalar(
        select(MediaList).where(MediaList.id == list_id, MediaList.user_id == user_id)
    )
    if lst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"List {list_id} not found"
        )
    return lst


async def _ensure_favorites_list(user_id: UUID, db: AsyncSession) -> None:
    """Everyone gets a Favorites list that fills itself from the favorite
    flag on every title, so starring something is enough to file it."""
    exists = await db.scalar(
        select(MediaList.id)
        .where(MediaList.user_id == user_id, MediaList.is_system.is_(True))
        .limit(1)
    )
    if exists is not None:
        return
    # two requests can get here together (the lists page fires several at
    # once); the unique name makes the loser a no-op instead of an error
    await db.execute(
        pg_insert(MediaList)
        .values(
            user_id=user_id,
            name="Favorites",
            description="Everything you have marked as a favorite",
            smart_rule={"favorite": True},
            is_system=True,
        )
        .on_conflict_do_nothing(constraint="uq_media_lists_user_id_name")
    )
    # a list the user made by hand under the same name blocked the insert:
    # when it is the same favorites filter, it becomes the system list
    own = await db.scalar(
        select(MediaList).where(
            MediaList.user_id == user_id,
            MediaList.name == "Favorites",
            MediaList.is_system.is_(False),
        )
    )
    if own is not None and own.smart_rule == {"favorite": True}:
        own.is_system = True
    await db.commit()


@router.get("/lists", response_model=list[MediaListRead])
async def list_media_lists(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    await _ensure_favorites_list(current_user.id, db)
    lists = (
        (
            await db.execute(
                select(MediaList)
                .where(MediaList.user_id == current_user.id)
                .order_by(
                    MediaList.pinned.desc(),
                    MediaList.position,
                    MediaList.is_system.desc(),
                    MediaList.name,
                )
            )
        )
        .scalars()
        .all()
    )
    return [_summary(lst, await _resolve_items(lst, current_user.id, db)) for lst in lists]


@router.get("/lists/membership")
async def get_list_membership(
    media_type: str = Query(...),
    media_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Which of the user's manual lists already contain this title, and
    the item row's own id — powers the checkmarks in the "Add to list"
    popover so it reads as a toggle (add/remove). Smart lists have no
    membership rows, so they never appear here."""
    rows = (
        await db.execute(
            select(MediaListItem.list_id, MediaListItem.id)
            .join(MediaList, MediaList.id == MediaListItem.list_id)
            .where(
                MediaList.user_id == current_user.id,
                MediaListItem.media_type == media_type,
                MediaListItem.media_id == media_id,
            )
        )
    ).all()
    return [{"list_id": list_id, "item_id": item_id} for list_id, item_id in rows]


@router.put("/lists/order", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def order_media_lists(
    payload: MediaListsOrder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Saves the user's own order of their lists: each id's place in the
    request becomes its position. Ids that are not the caller's are ignored,
    and lists left out of the request keep their relative order after them."""
    lists = (
        (await db.execute(select(MediaList).where(MediaList.user_id == current_user.id)))
        .scalars()
        .all()
    )
    by_id = {lst.id: lst for lst in lists}
    ordered = [by_id[i] for i in dict.fromkeys(payload.list_ids) if i in by_id]
    left_out = sorted(
        (lst for lst in lists if lst not in ordered), key=lambda lst: (lst.position, lst.name)
    )
    for position, lst in enumerate([*ordered, *left_out]):
        lst.position = position
    await db.commit()


@router.post("/lists", response_model=MediaListRead, status_code=status.HTTP_201_CREATED)
async def create_media_list(
    payload: MediaListCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    last = await db.scalar(
        select(func.max(MediaList.position)).where(MediaList.user_id == current_user.id)
    )
    lst = MediaList(
        user_id=current_user.id,
        position=(last or 0) + 1,
        name=payload.name,
        description=payload.description,
        smart_rule=payload.smart_rule.model_dump(exclude_none=True) if payload.smart_rule else None,
    )
    db.add(lst)
    await db.commit()
    await db.refresh(lst)
    return _summary(lst, await _resolve_items(lst, current_user.id, db))


@router.patch("/lists/{list_id}", response_model=MediaListRead)
async def update_media_list(
    list_id: UUID,
    payload: MediaListUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    lst = await _get_list_or_404(list_id, current_user.id, db)
    updates = payload.model_dump(exclude_unset=True)
    if lst.is_system and ({"name", "smart_rule"} & updates.keys()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Favorites is kept by the app; only its description and cover can change.",
        )
    if "smart_rule" in updates:
        rule = payload.smart_rule
        updates["smart_rule"] = rule.model_dump(exclude_none=True) if rule else None
    if updates.get("pinned", True) is None:
        del updates["pinned"]
    for field, value in updates.items():
        setattr(lst, field, value)
    await db.commit()
    await db.refresh(lst)
    return _summary(lst, await _resolve_items(lst, current_user.id, db))


@router.delete("/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_media_list(
    list_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    lst = await _get_list_or_404(list_id, current_user.id, db)
    if lst.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Favorites can't be deleted."
        )
    await db.delete(lst)
    await db.commit()


@router.get("/lists/{list_id}", response_model=MediaListDetailRead)
async def get_media_list(
    list_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    lst = await _get_list_or_404(list_id, current_user.id, db)
    items = await _resolve_items(lst, current_user.id, db)
    return {**_summary(lst, items), "items": items}


@router.post(
    "/lists/{list_id}/items", response_model=MediaListItemRead, status_code=status.HTTP_201_CREATED
)
async def add_list_item(
    list_id: UUID,
    payload: MediaListItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    lst = await _get_list_or_404(list_id, current_user.id, db)
    if lst.smart_rule is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A smart list fills itself from its rule — titles can't be added by hand.",
        )
    media = await _resolve_media(payload.media_type, payload.media_id, current_user.id, db)
    item = await db.scalar(
        select(MediaListItem).where(
            MediaListItem.list_id == list_id,
            MediaListItem.media_type == payload.media_type,
            MediaListItem.media_id == payload.media_id,
        )
    )
    if item is None:
        # new titles go to the end of a hand-ordered list
        last = await db.scalar(
            select(MediaListItem.position)
            .where(MediaListItem.list_id == list_id)
            .order_by(MediaListItem.position.desc())
            .limit(1)
        )
        item = MediaListItem(
            list_id=list_id,
            media_type=MediaType(payload.media_type),
            media_id=payload.media_id,
            position=(last or 0) + 1,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
    language = str((await load_preferences(db, current_user.id))["title_language"])
    return _item_dict(item.id, item.media_type, media, item.added_at, language)


@router.put("/lists/{list_id}/order", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def reorder_list_items(
    list_id: UUID,
    payload: MediaListReorder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Sets the manual order: `item_ids` is the full desired sequence."""
    await _get_list_or_404(list_id, current_user.id, db)
    items = (
        (await db.execute(select(MediaListItem).where(MediaListItem.list_id == list_id)))
        .scalars()
        .all()
    )
    by_id = {i.id: i for i in items}
    for position, item_id in enumerate(payload.item_ids):
        item = by_id.get(item_id)
        if item is not None:
            item.position = position
    await db.commit()


@router.delete(
    "/lists/{list_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def remove_list_item(
    list_id: UUID,
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await _get_list_or_404(list_id, current_user.id, db)
    item = await db.scalar(
        select(MediaListItem).where(MediaListItem.id == item_id, MediaListItem.list_id == list_id)
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"List item {item_id} not found"
        )
    await db.delete(item)
    await db.commit()
