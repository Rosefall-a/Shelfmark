export interface StatsBreakdownEntry {
  label: string;
  count: number;
}

export interface MostPlayedEntry {
  id: string;
  title: string;
  playtime_seconds: number;
}

export interface RecentlyAddedEntry {
  month: string;
  count: number;
}

export interface StatsOverview {
  total_games: number;
  favorite_count: number;
  total_playtime_seconds: number;
  storage_used_bytes: number;
  total_spent: number;
  average_rating: number | null;
  status_breakdown: StatsBreakdownEntry[];
  source_breakdown: StatsBreakdownEntry[];
  most_played: MostPlayedEntry[];
  recently_added: RecentlyAddedEntry[];
  rating_histogram: StatsBreakdownEntry[];
  top_tags: StatsBreakdownEntry[];
  release_year_breakdown: StatsBreakdownEntry[];
  format_breakdown: StatsBreakdownEntry[];
  bounties_completed: number;
  bounties_hard_completed: number;
  bounty_points_total: number;
}

const MOCK_STATS: StatsOverview = {
  total_games: 0,
  favorite_count: 0,
  total_playtime_seconds: 0,
  storage_used_bytes: 0,
  total_spent: 0,
  average_rating: null,
  status_breakdown: [],
  source_breakdown: [],
  most_played: [],
  recently_added: [],
  rating_histogram: [],
  top_tags: [],
  release_year_breakdown: [],
  format_breakdown: [],
  bounties_completed: 0,
  bounties_hard_completed: 0,
  bounty_points_total: 0,
};

export async function fetchStatsOverview(): Promise<StatsOverview> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return { ...MOCK_STATS };
  }

  const response = await fetch("/api/stats/overview", {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch stats: ${response.status} ${response.statusText}`,
    );
  }
  return await response.json();
}

export interface WeeklyDigest {
  period_start: number;
  games_played: number;
  games_added: number;
  achievements_unlocked: number;
  metadata_changes: number;
  bounties_completed: number;
}

const MOCK_WEEKLY_DIGEST: WeeklyDigest = {
  period_start: 0,
  games_played: 0,
  games_added: 0,
  achievements_unlocked: 0,
  metadata_changes: 0,
  bounties_completed: 0,
};

export async function fetchWeeklyDigest(): Promise<WeeklyDigest> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return { ...MOCK_WEEKLY_DIGEST };
  }

  const response = await fetch("/api/stats/weekly-digest", {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch weekly digest: ${response.status} ${response.statusText}`,
    );
  }
  return await response.json();
}
