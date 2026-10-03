import time
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.database.models.user import User

# Folder name rules: letters, digits, underscore, hyphen only — no spaces,
# no path separators, no reserved filesystem characters. Adjust the
# character class here and in schemas/game.py if you want to allow more.
FOLDER_NAME_PATTERN = r"^[A-Za-z0-9_-]+$"
FOLDER_NAME_MAX_LENGTH = 150


class GameStatus(str, Enum):
    """Game status aligned with Playnite."""

    DROPPED = "DROPPED"
    WISHLIST = "WISHLIST"
    BACKLOG = "BACKLOG"
    ON_HOLD = "ON_HOLD"
    PLAYING = "PLAYING"
    PLAYED = "PLAYED"
    BEATEN = "BEATEN"
    MASTERED = "MASTERED"


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        # folder names only need to be unique within a user's storage
        # namespace. Different users can therefore safely use the same
        # folder name while still keeping active games unique per user.
        Index(
            "ix_games_user_folder_location_active",
            "user_id",
            "folder_location",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user: Mapped["User"] = relationship()

    folder_location: Mapped[str] = mapped_column(
        String(FOLDER_NAME_MAX_LENGTH),
        nullable=False,
    )

    # Optional identifier of the corresponding Playnite library entry.
    # This is deliberately not unique: the same app account can receive
    # imports from multiple Playnite libraries, while ordinary app-created
    # games simply leave this unset.
    playnite_guid: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
    )

    # set instead of actually deleting the row — see features/trash/sweep.py,
    # which purges the row and moves the on-disk folder to trash for good
    # after 7 days. NULL means active/not deleted.
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # ------------------------------------------------------------------
    # Basic metadata
    # ------------------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    sort_title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Metadata fields a user has deliberately changed in the game editor.
    # Provider refreshes skip these values rather than silently replacing a manual override.
    locked_fields: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
    )

    release_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    developer: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    publisher: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    series: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
    )

    features: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
    )

    # collection names this game belongs to — plain names, same shape as
    # tags/features, not a join table. A collection with zero games still
    # only exists client-side (localStorage) until a game is added to it.
    collections: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
    )

    age_rating: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    time_to_beat_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 1),
        nullable=True,
    )

    # eager (selectin, not the default lazy) — unlike every other
    # relationship on this model, GameRead serializes `links` straight into
    # the API response, and a lazy load can't run once the async session
    # that produced the row is out of the request's await context
    links: Mapped[list["GameLink"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    source: Mapped[str | None] = mapped_column(  # source (string — e.g. "Steam", "GOG", "physical")
        String(50),
        nullable=True,
    )

    # a library-sync provider's own stable id for this game (Steam appid,
    # RetroAchievements GameID, PSN npCommunicationId) — NULL for
    # manually-added/search-added games. A title alone isn't a stable
    # identity: Steam occasionally reports a different display name for the
    # same appid across calls (e.g. briefly appending "- GOTY Edition"),
    # which was creating duplicate rows for the same real game on re-sync.
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # epoch seconds a library sync (Steam/RetroAchievements/PlayStation)
    # first noticed this game missing from the account's current
    # owned-games/library pull; NULL means either not synced from an
    # account or still present there. Never causes a deletion or an
    # overwrite by itself — a sync only sets/clears this flag so the user
    # can review and decide (uninstalled vs. refunded vs. temporarily
    # delisted are all indistinguishable from the API alone).
    stale_since: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # per-game opt-in for the account/profile switcher (Notes checklist +
    # Screenshots gallery scoping) — off by default since most games never
    # need more than one account; a multi-account game like OSRS turns it
    # on for just that game instead of a global setting cluttering every
    # other game's page.
    profiles_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # a second, independent opt-in — accounts/profiles work for any game
    # (checklist + media grouping, no game-specific assumptions), but the
    # WiseOldMan sync/stat-icon/skill-boss-grouping UI on the Stats card is
    # OSRS-specific and would be nonsense noise on every other game's
    # accounts. Off by default, same as profiles_enabled.
    osrs_stats_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ------------------------------------------------------------------
    # Modpack / mod / DLC / expansion relationships
    # ------------------------------------------------------------------
    # A generic self-referential tree, not a boolean is_modded — "modded"
    # and "DLC/expansion" are related but distinct concepts (GTNH is a
    # MODPACK of Minecraft; Phantom Liberty is an EXPANSION of Cyberpunk
    # 2077), and a title can have several of these off the same base game.
    # Each variant (a modpack, a DLC, a total conversion...) is its own
    # full Game row — not a sub-object — so saves/achievements/screenshots
    # already scope correctly to it via their existing game_id FK, with no
    # separate "configuration" layer needed. relationship_type is a plain
    # string, not a hard DB enum: new relationship kinds should never need
    # a migration, just a code change to the allowed set in the schema.
    parent_game_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # "mod" | "modpack" | "expansion" | "dlc" | "standalone_expansion" |
    # "total_conversion" — meaningless (should be NULL) when parent_game_id
    # is NULL, i.e. for a base/standalone game
    relationship_type: Mapped[str | None] = mapped_column(String(30), nullable=True)

    parent_game: Mapped["Game | None"] = relationship(
        remote_side=[id], back_populates="child_games"
    )
    child_games: Mapped[list["Game"]] = relationship(back_populates="parent_game")

    # ------------------------------------------------------------------
    # Personal library state
    # ------------------------------------------------------------------

    status: Mapped[GameStatus] = mapped_column(
        SAEnum(GameStatus, native_enum=False, length=30),
        nullable=False,
        default=GameStatus.WISHLIST,
    )

    priority: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    favorite: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    resume_note: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )

    playtime_seconds: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )
    # epoch seconds — populated from Steam's rtime_last_played during a
    # library sync; NULL when unknown (manually-added games, or a provider
    # that doesn't report this, e.g. RetroAchievements/PSN today)
    last_played_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # epoch seconds (midnight = no time set, just a date — same convention
    # as purchase_date below) — set automatically the first time a game's
    # status transitions to Mastered (see update_game/library_sync.py), but
    # user-editable too in case that auto-set date needs correcting
    completion_date: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # ownership ({ format: "digital" | "physical", purchase_date, price, condition })

    purchase_date: Mapped[int | None] = (
        mapped_column(  # Unix timestamp, midnight = no time set just date
            BigInteger,
            nullable=True,
        )
    )

    purchase_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    purchase_price_currency_code: Mapped[str | None] = mapped_column(  # ISO 4217 currency code
        String(3),  # Should always be uppercase
        nullable=True,
    )

    physical_condition: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Ratings
    # ------------------------------------------------------------------

    rating_story: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        nullable=True,
    )

    rating_gameplay: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        nullable=True,
    )

    rating_soundtrack: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        nullable=True,
    )

    rating_overall: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Personal ranking
    # ------------------------------------------------------------------

    personal_rank: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------

    created_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
    )

    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )


##########################
#          Links         #
##########################


class GameLink(Base):
    __tablename__ = "game_links"

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    game_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("games.id"),
        nullable=False,
    )

    label: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    url: Mapped[str] = mapped_column(
        String(2_048),
        nullable=False,
    )

    game: Mapped["Game"] = relationship(
        back_populates="links",
    )
