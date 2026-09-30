// Library export/import, a portable JSON snapshot of games, for backups
// or moving to a new server. Scoped to game data only, not screenshots/
// saves, see backend/src/api/routes/export_import.py.

export interface ImportResult {
  created: number;
  skipped: number;
  errors: string[];
}

export async function fetchLibraryExport(): Promise<unknown> {
  const response = await fetch("/api/export/library", {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to export library: ${response.status} ${response.statusText}`,
    );
  }
  return await response.json();
}

export interface BackupStatus {
  enabled: boolean;
  interval_hours: number;
  backups_kept: number;
  last_backup_at: number | null;
  backup_count: number;
}

export async function fetchBackupStatus(): Promise<BackupStatus> {
  const response = await fetch("/api/export/backup-status", {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch backup status: ${response.status} ${response.statusText}`,
    );
  }
  return await response.json();
}

export async function importLibrary(games: unknown[]): Promise<ImportResult> {
  const response = await fetch("/api/import/library", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(games),
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to import library: ${response.status} ${response.statusText} ${message}`,
    );
  }
  return await response.json();
}

export interface MalImportResult {
  created: number;
  updated: number;
  kept: number;
  assumed_complete?: number;
  total_in_file: number;
  details_filled: number;
  details_not_found: number;
  details_lookup_failed?: number;
  // movie and TV list imports
  skipped_other?: number;
  details_unavailable?: boolean;
  details_source?: string | null;
  seasons_assumed_watched?: number;
}

export interface MalDifference {
  field: string;
  site: string | null;
  mal: string;
}
export interface MalExisting {
  mal_id: string;
  title: string;
  site_title: string;
  differences: MalDifference[];
}
export interface MalPreview {
  total: number;
  new_count: number;
  new_titles: string[];
  existing: MalExisting[];
  identical: number;
  skipped_other?: number;
}

async function postMal(
  path: string,
  file: File,
  extra: Record<string, string> = {},
): Promise<Response> {
  const body = new FormData();
  body.append("file", file);
  for (const [key, value] of Object.entries(extra)) body.append(key, value);
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    body,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return response;
}

// Reads a MyAnimeList export (the .xml or .xml.gz from MAL's export page)
// and reports what it would add or change, without changing anything.
export async function previewMal(file: File): Promise<MalPreview> {
  return await (await postMal("/api/import/mal/preview", file)).json();
}

// Adds the new titles. A title already on the site stays exactly as it is
// unless its MAL id is in `useMal`, in which case MAL's data is applied.
export async function importMal(
  file: File,
  useMal: string[],
  fetchDetails: boolean,
): Promise<MalImportResult> {
  return await (
    await postMal("/api/import/mal", file, {
      overwrite: JSON.stringify(useMal),
      fetch_details: String(fetchDetails),
    })
  ).json();
}

export type ImportSource = "mal" | "letterboxd" | "imdb" | "yamtrack";

// Sites other than MyAnimeList (Letterboxd, IMDb): the same review-then-import
// flow, for movies and TV shows.
export async function previewList(
  file: File,
  source: Exclude<ImportSource, "mal">,
): Promise<MalPreview> {
  return await (
    await postMal("/api/import/list/preview", file, { source })
  ).json();
}
export async function importList(
  file: File,
  source: Exclude<ImportSource, "mal">,
  useKeys: string[],
  fetchDetails: boolean,
): Promise<MalImportResult> {
  return await (
    await postMal("/api/import/list", file, {
      source,
      overwrite: JSON.stringify(useKeys),
      fetch_details: String(fetchDetails),
    })
  ).json();
}

export async function fetchMediaCsv(): Promise<Blob> {
  const response = await fetch("/api/export/media.csv", {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to export the CSV: ${response.status} ${response.statusText}`,
    );
  }
  return await response.blob();
}

export interface MediaRestoreResult {
  created: Record<string, number>;
  skipped: Record<string, number>;
  errors: string[];
}

// The app's own library export (or a backup file): movies, TV shows and
// anime come back with their seasons and episode progress.
export async function restoreMedia(file: File): Promise<MediaRestoreResult> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/import/media", {
    method: "POST",
    credentials: "include",
    body,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return await response.json();
}

export interface YamtrackImportResult {
  created: Record<string, number>;
  skipped: Record<string, number>;
  total_rows: number;
  total_items: number;
  seasons_created: number;
  episodes_created: number;
  errors: string[];
}

export async function importYamtrack(file: File): Promise<YamtrackImportResult> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/import/yamtrack", {
    method: "POST",
    credentials: "include",
    body,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return await response.json();
}
