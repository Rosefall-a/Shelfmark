from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Plain strings on the DB side (see database/models/card.py), validated
# here so a typo doesn't silently create a new, slightly-different value.
# A new tier/status is a code change, never a migration.
CardRarity = Literal["common", "uncommon", "rare", "legendary", "mythic"]
CardStatus = Literal["draft", "approved", "printed", "archived"]


class CardCreate(BaseModel):
    game_id: UUID
    set_id: UUID | None = None
    rarity: CardRarity | None = None
    card_customization: dict | None = None


class CardUpdate(BaseModel):
    """Partial update — every field optional. archive_number is never
    here, it's permanent once assigned at creation. bounty_id is never
    here either — it's only ever set by
    POST /cards/{card_id}/prestige-challenge."""

    set_id: UUID | None = None
    rarity: CardRarity | None = None
    card_customization: dict | None = None
    status: CardStatus | None = None


class CardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    game_id: UUID
    archive_number: int | None
    set_id: UUID | None
    rarity: CardRarity | None
    bounty_id: UUID | None
    card_customization: dict | None
    status: CardStatus
    created_at: int
    updated_at: int
