// The random game picker (#33): narrow the library down by status, platform,
// genre, length and priority, then pick one, optionally favouring the games
// with a higher priority.

import type { Game, GameStatus } from "../types/game";
import { normalizePlatformFamily } from "./platforms";
import { activePriority } from "./priority";

export interface PickerFilters {
  // empty means any status that isn't finished
  statuses: GameStatus[];
  // a platform family ("PC", "PlayStation"...) or "all"
  platform: string;
  // a genre tag or "all"
  genre: string;
  // time to beat upper bound in hours, null for no limit
  maxHours: number | null;
  // whether games with no known time to beat pass a length limit
  includeUnknownLength: boolean;
  // only games with this priority or higher (1 is highest), null for any,
  // including games with no priority
  maxPriority: number | null;
  // pick higher-priority games more often instead of uniformly
  weightByPriority: boolean;
}

export const DEFAULT_PICKER_FILTERS: PickerFilters = {
  statuses: ["backlog", "playing", "on hold"],
  platform: "all",
  genre: "all",
  maxHours: null,
  includeUnknownLength: true,
  maxPriority: null,
  weightByPriority: true,
};

const FINISHED: GameStatus[] = ["beaten", "mastered", "played", "dropped"];

export function matchesPickerFilters(game: Game, f: PickerFilters): boolean {
  if (f.statuses.length) {
    if (!f.statuses.includes(game.status)) return false;
  } else if (FINISHED.includes(game.status)) {
    return false;
  }
  if (
    f.platform !== "all" &&
    !game.platforms.some(
      (p) => normalizePlatformFamily(p.platform) === f.platform,
    )
  ) {
    return false;
  }
  if (f.genre !== "all" && !game.tags.includes(f.genre)) return false;
  if (f.maxHours !== null) {
    if (game.timeToBeatHours === null) {
      if (!f.includeUnknownLength) return false;
    } else if (game.timeToBeatHours > f.maxHours) {
      return false;
    }
  }
  if (f.maxPriority !== null) {
    const rank = activePriority(game);
    if (rank === null || rank > f.maxPriority) return false;
  }
  return true;
}

// priority 1 is five times as likely as priority 5 or no priority
export function pickWeight(game: Game, weightByPriority: boolean): number {
  if (!weightByPriority) return 1;
  const rank = activePriority(game);
  return rank === null ? 1 : 6 - rank;
}

export function pickRandomGame(
  games: Game[],
  filters: PickerFilters,
  random: () => number = Math.random,
  exclude?: string | null,
): Game | null {
  let pool = games.filter((g) => matchesPickerFilters(g, filters));
  // "pick again" shouldn't land on the same game when there's a choice
  if (exclude && pool.length > 1) pool = pool.filter((g) => g.id !== exclude);
  if (!pool.length) return null;
  const weights = pool.map((g) => pickWeight(g, filters.weightByPriority));
  const total = weights.reduce((sum, w) => sum + w, 0);
  let roll = random() * total;
  for (let i = 0; i < pool.length; i++) {
    roll -= weights[i];
    if (roll < 0) return pool[i];
  }
  return pool[pool.length - 1];
}
