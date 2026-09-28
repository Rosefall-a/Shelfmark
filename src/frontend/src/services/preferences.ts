// Server-side per-user preferences (calendar options, notification
// toggles). Defaults live on the server; this only carries the shape.

export type NotificationKind = "episode_aired" | "season_started" | "sequel_announced" | "movie_released";

export interface Preferences {
  calendar_game_releases: boolean;
  calendar_game_history: boolean;
  calendar_default_view: "month" | "week" | "agenda";
  calendar_week_start: 0 | 1;
  calendar_hide_games: boolean;
  calendar_show_estimated: boolean;
  notify_episode_aired: boolean;
  notify_season_started: boolean;
  notify_sequel_announced: boolean;
  notify_movie_released: boolean;
  notification_provider_routes: Record<string, NotificationKind[]>;
  notify_statuses: ("watching" | "plan" | "hold")[];
  calendar_airing_statuses: ("watching" | "plan" | "hold")[];
  notify_media_types: ("anime" | "tv" | "movie")[];
  notification_retention_days: 0 | 7 | 14 | 30 | 90;
  library_default_layout: "list" | "shelf" | "board";
  lists_default_sort: "custom" | "name" | "count" | "recent";
  title_language: "english" | "romaji" | "native";
  stats_include_plan: boolean;
  anilist_import_enabled: boolean;
  anilist_import_username: string;
  anilist_import_interval_minutes: number;
  anilist_import_update_existing: boolean;
  anilist_import_last_run_at: number | null;
}

export const DEFAULT_PREFERENCES: Preferences = {
  calendar_game_releases: true,
  calendar_game_history: true,
  calendar_default_view: "month",
  calendar_week_start: 0,
  calendar_hide_games: false,
  calendar_show_estimated: true,
  calendar_airing_statuses: ["watching", "plan", "hold"],
  notify_episode_aired: true,
  notify_season_started: true,
  notify_sequel_announced: true,
  notify_movie_released: true,
  notification_provider_routes: {
    smtp: ["episode_aired", "season_started", "sequel_announced", "movie_released"],
    discord: ["episode_aired", "season_started", "sequel_announced", "movie_released"],
  },
  notify_statuses: ["watching", "plan", "hold"],
  notify_media_types: ["anime", "tv", "movie"],
  notification_retention_days: 30,
  library_default_layout: "list",
  lists_default_sort: "custom",
  title_language: "english",
  stats_include_plan: true,
};

export async function fetchPreferences(): Promise<Preferences> {
  const response = await fetch("/api/preferences", { credentials: "include" });
  if (!response.ok) throw new Error(`Failed to load preferences: ${response.status}`);
  return { ...DEFAULT_PREFERENCES, ...(await response.json()) };
}

export async function updatePreferences(changes: Partial<Preferences>): Promise<Preferences> {
  const response = await fetch("/api/preferences", {
    method: "PATCH", credentials: "include", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!response.ok) throw new Error(`Failed to save preferences: ${response.status}`);
  return { ...DEFAULT_PREFERENCES, ...(await response.json()) };
}

let saveQueue: Promise<unknown> = Promise.resolve();
let saving = 0;
export function queuePreferences(changes: Partial<Preferences>): Promise<{ prefs: Preferences; latest: boolean }> {
  saving += 1;
  const run = saveQueue.then(() => updatePreferences(changes));
  saveQueue = run.catch(() => undefined);
  return run.then((prefs) => { saving -= 1; return { prefs, latest: saving === 0 }; }, (err) => { saving -= 1; throw err; });
}
