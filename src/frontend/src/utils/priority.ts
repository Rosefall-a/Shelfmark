import type { GameStatus } from "../types/game";

// Game priority (#32): "1" is the most wanted, "5" the least, the same
// direction as the AniList import's 1 = HIGH. Stored as a string because the
// backend column is shared with anime/TV/movies, which use HIGH/MEDIUM/LOW.
export const PRIORITY_OPTIONS = [
  { value: "1", label: "1 · Highest" },
  { value: "2", label: "2 · High" },
  { value: "3", label: "3 · Medium" },
  { value: "4", label: "4 · Low" },
  { value: "5", label: "5 · Lowest" },
] as const;

const LEGACY_PRIORITY: Record<string, number> = {
  HIGH: 1,
  MEDIUM: 3,
  LOW: 5,
};

// Finished (or abandoned) games drop out of priority: there's nothing left
// to prioritize, so they neither show a priority nor get picked or ranked
// by it.
export const FINISHED_STATUSES: ReadonlySet<GameStatus> = new Set([
  "beaten",
  "mastered",
  "played",
  "dropped",
]);

export function isFinished(status: GameStatus): boolean {
  return FINISHED_STATUSES.has(status);
}

// 1..5, or null when unset/unrecognised.
export function priorityRank(
  priority: string | null | undefined,
): number | null {
  if (!priority) return null;
  const numeric = Number(priority);
  if (Number.isInteger(numeric) && numeric >= 1 && numeric <= 5) return numeric;
  return LEGACY_PRIORITY[priority.toUpperCase()] ?? null;
}

// Priority as it matters today: null for a finished game even if a
// priority was set before it was finished.
export function activePriority(game: {
  status: GameStatus;
  priority?: string | null;
}): number | null {
  return isFinished(game.status) ? null : priorityRank(game.priority);
}

export function priorityLabel(rank: number): string {
  return PRIORITY_OPTIONS[rank - 1]?.label ?? String(rank);
}
