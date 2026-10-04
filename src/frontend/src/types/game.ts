export type GameStatus =
  | "wishlist"
  | "backlog"
  | "playing"
  | "on hold"
  | "beaten"
  | "played"
  | "dropped"
  | "mastered";

export type AchievementTier = "bronze" | "silver" | "gold";

// a game's relationship to its parentGameId, kept in sync with the
// backend's GameRelationshipType (api/schemas/game.py); adding a new value
// is a code change on both sides, never a migration
export type GameRelationshipType =
  | "mod"
  | "modpack"
  | "expansion"
  | "dlc"
  | "standalone_expansion"
  | "total_conversion";

// where a game's achievement tracking comes from, 'retroachievements' means
// synced via retroachievements.org, common for emulated/retro platforms
export type AchievementsProvider = "native" | "retroachievements" | null;

export interface Achievement {
  id: string;
  name: string;
  description?: string | null;
  unlockedAt: string | null;
  hidden?: boolean;
  rarityPercent?: number | null;
  tierOverride?: AchievementTier | null;
  progressCurrent?: number | null;
  progressTarget?: number | null;
  notes?: string | null;
  media?: string[];
}

export interface GamePlatform {
  platform: string;
  playtimeMinutes: number;
  completionPercent: number | null;
  lastPlayedAt: string | null;
}

export interface Game {
  id: string;
  title: string;
  coverColor: string;
  // real placeholder image for the detail page's hero + blurred backdrop.
  // temporary, will point at real IGDB artwork once that sync exists
  coverImageUrl: string;
  bannerImageUrl: string;
  status: GameStatus;
  ratingOverall: number | null;
  ratingStory: number | null;
  ratingGameplay: number | null;
  ratingSound: number | null;
  lastPlayedAt: string | null;
  // set by a library sync the moment it no longer sees this game in the
  // account's owned-games pull (uninstalled, refunded, etc.), null means
  // currently present or never synced from an account. Purely informational;
  // nothing auto-deletes because of this.
  staleSince: string | null;
  // opt-in, per game (default off), shows the account/profile switcher on
  // this game's Notes checklist and Screenshots gallery. Off by default
  // since most games never need more than one account tracked separately.
  profilesEnabled: boolean;
  // second, independent opt-in, accounts work for any game (checklist +
  // media grouping), but WiseOldMan sync/skill-boss icons on the Stats
  // card are OSRS-specific and would be noise on every other game
  osrsStatsEnabled: boolean;
  // when this game was first 100%-completed (Mastered), set once
  // automatically, editable afterward like purchaseDate
  completionDate: string | null;
  // a modpack/mod/expansion/DLC/total conversion is its own full Game row,
  // linked to the game it's a variant of, NOT a boolean is_modded, since
  // "modded" and "DLC/expansion" are related but distinct, and one base
  // game can have several kinds of variant
  parentGameId: string | null;
  relationshipType: GameRelationshipType | null;
  achievementPercent: number;
  // count of achievements tracked for this game (0 if never synced),
  // independent of achievementPercent, since a game can have achievements
  // tracked with 0% unlocked so far
  achievementTotal: number;
  achievements: Achievement[];
  description: string | null;
  developer: string | null;
  publisher: string | null;
  series: string | null;
  dateAdded: string | null;
  // "where I left off", a short freeform note about what to do when you
  // pick this game back up. Separate from the full Notes tab (named,
  // multi-note documents) since this is meant to be the one thing shown
  // right on the overview, not something you have to go looking for
  resumeNote: string | null;
  folderLocation: string | null;
  releaseDate: string | null;
  source: string | null;
  // the system it's played on, separate from `source` (where the copy came
  // from), optional so hand-built/mock games don't need it
  platform?: string | null;
  // "1" (highest) .. "5" (lowest), see utils/priority.ts
  priority?: string | null;
  // the name the library sorts by; blank means the title
  sortTitle?: string | null;
  ageRating: string | null;
  timeToBeatHours: number | null;
  region: string | null;
  language: string | null;
  achievementsProvider: AchievementsProvider;
  links: GameLink[];
  ownership: GameOwnership;
  favorite: boolean;
  collections: string[];
  tags: string[];
  // capability/technical tags (Achievements, Co-op, Multiplayer...), different from `tags`,
  // which are genre/style descriptors
  features: string[];
  platforms: GamePlatform[];
}

export interface GameLink {
  label: string;
  url: string;
}

export interface GameOwnership {
  format: "digital" | "physical" | null;
  purchaseDate: string | null;
  price: number | null;
  priceCurrency: string | null;
  condition: string | null;
}
