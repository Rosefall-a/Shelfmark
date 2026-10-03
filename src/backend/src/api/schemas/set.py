from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.api.schemas.card import CardRead


class SetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    target_total: int | None = Field(default=None, ge=1)


class SetUpdate(BaseModel):
    """Partial update — every field optional."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    target_total: int | None = Field(default=None, ge=1)


class SetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    description: str | None
    target_total: int | None
    created_at: int
    updated_at: int

    # computed, not stored — see api/routes/set.py
    card_count: int = Field(description="Number of cards currently assigned to this set.")
    is_complete: bool = Field(
        description="True only when target_total is set and card_count >= target_total."
    )


class SetDetailRead(SetRead):
    cards: list[CardRead] = Field(default_factory=list)
