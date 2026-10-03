from __future__ import annotations

import time
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, BigInteger, Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base

# built-in bounty types — kept small and generic on purpose (rule: "we
# shouldn't constantly need to change the application when you invent a
# weird goal") rather than one enum value per possible goal shape
BOUNTY_TYPES = (
    "completion",
    "mastery",
    "achievement",
    "collection",
    "challenge",
    "watch",
    "custom",
)
BOUNTY_DIFFICULTIES = ("easy", "normal", "hard", "extreme")
BOUNTY_STATUSES = ("not_started", "active", "paused", "completed", "abandoned")
BOUNTY_PROGRESS_MODES = ("binary", "percentage", "numeric")

# which types compute their own progress from real data vs. rely on the
# user updating progress_value by hand
AUTOMATIC_BOUNTY_TYPES = ("completion", "mastery", "achievement", "collection")

BOUNTY_OBJECTIVE_KINDS = ("checkbox", "numeric", "achievement")
BOUNTY_EVIDENCE_KINDS = ("screenshot", "clip", "document", "note", "link")


class Bounty(Base):
    """A personal goal — 'finish Elden Ring', 'master Pokémon Platinum',
    'earn this achievement', 'play 10 backlog games' — independent from
    Achievements/Mastery/Cards/Prestige but optionally pointing at one of
    them via a target. Bounties never create those other records; at most
    they read from them to compute their own progress.

    Card and Prestige systems don't exist in this app yet, so there's
    intentionally no card_id/prestige_challenge_id column here — add those
    as nullable FKs when those systems are built, rather than carrying
    dead columns now."""

    __tablename__ = "bounties"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="custom")
    difficulty: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    # --- target — a relationship, never a copy of the target's data -----
    # optional: a bounty can target nothing (a fully custom, manually
    # tracked goal) or exactly one of the shapes below, matching `type`
    game_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # achievements are fully deleted + reinserted on every library sync, so
    # their row id isn't stable across syncs — target by the pair a sync
    # actually preserves instead of a raw FK
    target_achievement_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_achievement_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # collections are just a name shared across games' `collections` arrays
    # (see Game.collections) — no separate Collection table to point a FK at
    target_collection_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # --- progress ---------------------------------------------------------
    progress_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="binary")
    progress_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    # percentage mode implies a target of 100; numeric mode needs its own
    # target (e.g. 10 for "play 10 backlog games"); binary mode ignores both
    progress_target: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # --- reward -------------------------------------------------------
    points_reward: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # informational only — displayed as a hint ("Required evidence:
    # Screenshot"), never enforced as a block on completion. Empty list
    # means the bounty doesn't ask for anything in particular.
    required_evidence_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    # --- dates ----------------------------------------------------------
    target_date: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
    started_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    completed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # True for a bounty the system proposed on its own (see
    # features/bounties/auto_propose.py) rather than one the user typed in
    # themselves — lets the picker avoid re-proposing the same target and
    # lets the UI label it distinctly
    auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BountyPointTransaction(Base):
    """A permanent point-award record. A bounty's total points are never a
    stored/editable number on the bounty itself — always
    SUM(BountyPointTransaction.amount) — so history stays trustworthy even
    if the bounty's reward value is edited afterward. The unique
    `bounty_id` guarantees a bounty can award its points exactly once."""

    __tablename__ = "bounty_point_transactions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bounty_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bounties.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)


class BountyObjective(Base):
    """One checklist line inside a bounty — 'earn 3 badges', 'collect 10
    items', 'unlock this achievement'. Purely optional; a bounty with none
    still tracks its own progress_value/progress_target as before. Once a
    bounty has objectives, its overall progress is derived from how many
    of them are done rather than from `type`'s automatic logic."""

    __tablename__ = "bounty_objectives"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    bounty_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bounties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="checkbox")
    # checkbox kind — toggled by hand
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # numeric kind — updated by hand, e.g. 7 of 10
    progress_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    progress_target: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # achievement kind — same stable (provider, external_id) pattern as a
    # bounty's own achievement target, since achievement rows aren't stable
    # across syncs
    target_achievement_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_achievement_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)


class BountyEvidence(Base):
    """Documentation attached to a bounty — a screenshot/clip already in
    the game's media library, a free-text note, or an external link.
    Never proof of validity by itself, just an attached record."""

    __tablename__ = "bounty_evidence"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    bounty_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bounties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    # screenshot/clip/document — an existing MediaItem already uploaded to
    # the target game's gallery, never a second copy of the file
    media_item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("media_items.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # note kind, or a caption on any kind
    url: Mapped[str | None] = mapped_column(Text, nullable=True)  # link kind
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)


class BountyJournalEntry(Base):
    """A dated free-text note on a bounty's own timeline — 'started the
    run', 'lost the run', 'completed it'. Not a social feature, just a
    running log kept on the bounty itself."""

    __tablename__ = "bounty_journal_entries"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    bounty_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bounties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=time.time)
