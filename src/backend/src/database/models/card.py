from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.database.models.bounty import Bounty
    from src.database.models.game import Game
    from src.database.models.set import Set

# draft | approved | printed | archived — plain string, not a DB enum,
# same convention as every other tier/reason field in this codebase. Not
# enforced anywhere yet (no "warn before editing a Printed card" UI this
# pass), just stored so it's not a future migration.
CARD_STATUSES = ("draft", "approved", "printed", "archived")


class Card(Base):
    """A Collector Card — its own entity, separate from Game, so a game can
    eventually have more than one card for genuinely different
    accomplishments (a normal 100% completion vs. a separate Prestige
    challenge run), each with its own permanent archive_number. A card can
    optionally belong to a Set (set_id) — the set relates to cards, not to
    the game directly, since "07/24" is footer information printed on the
    card itself."""

    __tablename__ = "cards"
    __table_args__ = (
        # an archive number belongs to one card per user
        Index(
            "ix_cards_archive_number_user_active",
            "user_id",
            "archive_number",
            unique=True,
            postgresql_where=text("archive_number IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    game_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    game: Mapped["Game"] = relationship()

    # assigned once, at creation, and never reassigned afterward — even a
    # full redesign keeps the same number. Unique per user via a partial
    # index (see the migration), not globally.
    archive_number: Mapped[int | None] = mapped_column(nullable=True)

    set_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    set_entry: Mapped["Set | None"] = relationship()

    # common | uncommon | rare | legendary | mythic
    rarity: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # prestige is a second, deliberate challenge run done after the normal
    # 100% completion — never a manual toggle. NULL means no prestige
    # challenge exists yet for this card; once the game's achievements hit
    # 100%, the system auto-generates one Bounty (see
    # features/cards/prestige_challenge.py) and links it here. Whether the
    # card is actually "prestiged" is never stored — it's always derived
    # from bounty.status == "completed" at read time.
    bounty_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bounties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    bounty: Mapped["Bounty | None"] = relationship()

    # template/back template/accent/border color/card face/symbol choices —
    # one blob instead of a column per knob, so new customization options
    # are a frontend-only change
    card_customization: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    updated_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=time.time, onupdate=time.time
    )
