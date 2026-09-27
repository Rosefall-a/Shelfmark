import { mockGames } from "../data/mockGames";
import type {
  Achievement,
  AchievementsProvider,
  Game,
  GameStatus,
  GameLink,
  GameOwnership,
  GameRelationshipType,
} from "../types/game";

// The exact shape FastAPI sends, snake_case, matching the Python model
// field-for-field. This is deliberately a separate type from `Game`:
// nothing outside this file should ever see raw backend data directly.
export interface BackendGame {
  id: string;
  title: string;
  sort_title: string;
  description: string | null;
  release_date: string | null;
  developer: string | null;
  publisher: string | null;
  series: string | null;
  tags: string[];
  features: string[];
  source: string | null;
  age_rating: string | null;
  parent_game_id: string | null;
  relationship_type: GameRelationshipType | null;
  time_to_beat_hours: number | string | null;
  status: string;
  priority: string | null;
  favorite: boolean;
  notes: string | null;
  resume_note: string | null;
  playtime_seconds: number;
  purchase_date: number | null;
  completion_date: number | null;
  purchase_price: number | string | null;
  purchase_price_currency_code: string | null;
  physical_condition: string | null;
  rating_story: number | string | null;
  rating_gameplay: number | string | null;
  rating_soundtrack: number | string | null;
  rating_overall: number | string | null;
  personal_rank: number | null;
  // unix timestamps in seconds, not ISO strings
  created_at: number;
  updated_at: number;
  folder_location: string;
  last_played_at: number | null;
  stale_since: number | null;
  profiles_enabled: boolean;
  osrs_stats_enabled: boolean;
  collections: string[];
  links: GameLink[];
}

// Pydantic can serialize a Decimal as either a JSON number or a string
// depending on config, handle both rather than assume one
function toNumberOrNull(value: number | string | null): number | null {
  return value === null ? null : Number(value);
}

function unixSecondsToIso(seconds: number | null): string | null {
  return seconds === null ? null : new Date(seconds * 1000).toISOString();
}

function unixSecondsToDateInput(seconds: number | null): string | null {
  return seconds === null
    ? null
    : new Date(seconds * 1000).toISOString().slice(0, 10);
}

function dateInputToUnixSeconds(dateStr: string | null): number | null {
  if (!dateStr) return null;
  return Math.floor(new Date(dateStr).getTime() / 1000);
}

// backend sends "ON_HOLD", "WISHLIST", etc., frontend expects
// 'on hold', 'wishlist' (lowercase, spaces not underscores)
function normalizeStatus(raw: string): GameStatus {
  return raw.toLowerCase().replace(/_/g, " ") as GameStatus;
}
// inverse of normalizeStatus, 'on hold' -> 'ON_HOLD'
function denormalizeStatus(status: GameStatus): string {
  return status.toUpperCase().replace(/ /g, "_");
}

export function mapBackendGame(raw: BackendGame): Game {
  return {
    id: raw.id,
    title: raw.title,
    // placeholders, the backend has no artwork yet
    coverColor: "#2a2a2a",
    coverImageUrl: `/api/game/${raw.id}/assets/key_art`,
    bannerImageUrl: `/api/game/${raw.id}/assets/banner`,
    status: normalizeStatus(raw.status),
    ratingOverall: toNumberOrNull(raw.rating_overall),
    ratingStory: toNumberOrNull(raw.rating_story),
    ratingGameplay: toNumberOrNull(raw.rating_gameplay),
    ratingSound: toNumberOrNull(raw.rating_soundtrack),
    // real per-game counts come from a separate bulk summary call
    // (fetchAchievementsSummary) merged in by GameLibrary.vue, a single
    // game's full achievement list is fetched separately (GameDetail.vue)
    achievementPercent: 0,
    achievementTotal: 0,
    achievements: [],
    description: raw.description,
    developer: raw.developer,
    publisher: raw.publisher,
    series: raw.series,
    parentGameId: raw.parent_game_id,
    relationshipType: raw.relationship_type,
    dateAdded: unixSecondsToIso(raw.created_at),
    updatedAt: raw.updated_at,
    resumeNote: raw.resume_note,
    lastPlayedAt: unixSecondsToIso(raw.last_played_at),
    staleSince: unixSecondsToIso(raw.stale_since),
    profilesEnabled: raw.profiles_enabled,
    osrsStatsEnabled: raw.osrs_stats_enabled,
    completionDate: unixSecondsToDateInput(raw.completion_date),
    folderLocation: raw.folder_location,
    releaseDate: raw.release_date,
    source: raw.source,
    ageRating: raw.age_rating,
    timeToBeatHours: toNumberOrNull(raw.time_to_beat_hours),
    region: null,
    language: null,
    achievementsProvider: null,
    links: raw.links,
    ownership: {
      // no backend column for digital-vs-physical, inferred from whether
      // a physical condition was recorded, otherwise left unset
      format: raw.physical_condition ? "physical" : null,
      purchaseDate: unixSecondsToDateInput(raw.purchase_date),
      price: toNumberOrNull(raw.purchase_price),
      priceCurrency: raw.purchase_price_currency_code,
      condition: raw.physical_condition,
    },
    tags: raw.tags,
    features: raw.features,
    favorite: raw.favorite,
    collections: raw.collections,
    // the backend only tracks one flat playtime total, not real per-platform
    // data, synthesize a single entry labeled by where the game actually
    // came from (Steam/GOG/PlayStation/etc.), falling back to "PC" only for
    // manually-added games with no known source
    platforms: [
      {
        platform: raw.source || "PC",
        playtimeMinutes: Math.round(raw.playtime_seconds / 60),
        completionPercent: null,
        lastPlayedAt: unixSecondsToIso(raw.last_played_at),
      },
    ],
  };
}

// /api/game/list caps a single page at 200, page through until a page
// comes back short, otherwise only the first 50 (the endpoint's default)
// ever reached the library view once a synced library grew past that.
const GAMES_PAGE_SIZE = 200;

export async function fetchGames(): Promise<Game[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return mockGames;
  }
  const all: BackendGame[] = [];
  let skip = 0;
  while (true) {
    const response = await fetch(
      `/api/game/list?skip=${skip}&limit=${GAMES_PAGE_SIZE}`,
      { credentials: "include" },
    );
    if (!response.ok) {
      throw new Error(
        `Failed to fetch games: ${response.status} ${response.statusText}`,
      );
    }
    const page: BackendGame[] = await response.json();
    all.push(...page);
    if (page.length < GAMES_PAGE_SIZE) break;
    skip += GAMES_PAGE_SIZE;
  }
  return all.map(mapBackendGame);
}

interface BackendAchievement {
  id: string;
  provider: string;
  name: string;
  description: string | null;
  icon_url: string | null;
  unlocked: boolean;
  unlocked_at: number | null;
}

export interface FieldChange {
  id: string;
  fieldName: string;
  oldValue: string | null;
  newValue: string | null;
  changedAt: string;
}
interface BackendFieldChange {
  id: string;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  changed_at: number;
}
export async function fetchGameFieldChanges(
  id: string,
): Promise<FieldChange[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return [];
  }
  const response = await fetch(`/api/game/${id}/field-changes`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch metadata history: ${response.status} ${response.statusText}`,
    );
  }
  const raw: BackendFieldChange[] = await response.json();
  return raw.map((c) => ({
    id: c.id,
    fieldName: c.field_name,
    oldValue: c.old_value,
    newValue: c.new_value,
    changedAt: unixSecondsToIso(c.changed_at) as string,
  }));
}

export async function fetchGameAchievements(
  id: string,
): Promise<Achievement[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return [];
  }
  const response = await fetch(`/api/game/${id}/achievements`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch achievements: ${response.status} ${response.statusText}`,
    );
  }
  const raw: BackendAchievement[] = await response.json();
  return raw.map((a) => ({
    id: a.id,
    name: a.name,
    description: a.description,
    unlockedAt: a.unlocked ? unixSecondsToIso(a.unlocked_at) : null,
  }));
}

export interface AchievementsSummaryEntry {
  total: number;
  unlocked: number;
}

// one grouped query for every game's {total, unlocked} counts, used to
// show a completion badge on library/card views without an N+1 request
// per game (fetchGameAchievements above is for the single-game detail page)
export async function fetchAchievementsSummary(): Promise<
  Record<string, AchievementsSummaryEntry>
> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return {};
  }
  const response = await fetch("/api/game/achievements-summary", {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch achievements summary: ${response.status} ${response.statusText}`,
    );
  }
  return await response.json();
}

export async function fetchGame(id: string): Promise<Game | null> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return mockGames.find((g) => g.id === id) ?? null;
  }
  const response = await fetch(`/api/game/get/${id}`, {
    credentials: "include",
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(
      `Failed to fetch game ${id}: ${response.status} ${response.statusText}`,
    );
  }
  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
}

// every game whose parentGameId points at this one, e.g. Minecraft's
// variants list showing GTNH, Vanilla, Create Pack, etc.
export async function fetchGameVariants(id: string): Promise<Game[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return mockGames.filter((g) => g.parentGameId === id);
  }
  const response = await fetch(`/api/game/${id}/variants`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch variants for game ${id}: ${response.status} ${response.statusText}`,
    );
  }
  const raw: BackendGame[] = await response.json();
  return raw.map(mapBackendGame);
}

export interface MetadataSearchResult {
  provider: string;
  provider_id: string;
  title: string;
  description: string | null;
  release_date: string | null;
  developer: string | null;
  publisher: string | null;
  series: string | null;
  age_rating: string | null;
  time_to_beat_hours: number | string | null;
  tags: string[];
  features: string[];
  links: GameLink[];
  key_art_url: string | null;
  key_art_urls: string[];
  banner_url: string | null;
  banner_urls: string[];
  logo_url: string | null;
  logo_urls: string[];
  icon_url: string | null;
  icon_urls: string[];
}

export interface MetadataSearchResponse {
  results: MetadataSearchResult[];
  steamgriddb_configured: boolean;
  provider_errors: string[];
}

export async function searchGameMetadata(
  query: string,
): Promise<MetadataSearchResponse> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return { results: [], steamgriddb_configured: false, provider_errors: [] };
  }
  const response = await fetch(
    `/api/game/metadata/search?query=${encodeURIComponent(query)}`,
    {
      credentials: "include",
    },
  );
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`Metadata search failed: ${response.status} ${message}`);
  }
  return await response.json();
}


export type RefreshMetadataResult = "updated" | "no-match" | "error";

export interface RefreshMetadataOutcome {
  status: RefreshMetadataResult;
  provider: string | null;
  providerErrors: string[];
  changedFields: string[];
  skippedLockedFields: string[];
  keyArtAdded: boolean;
  bannerAdded: boolean;
  gameUpdatedAt: number;
}

export interface RefreshMetadataOptions {
  updateText: boolean;
  fillMissingArt: boolean;
  overwriteExistingArt: boolean;
}

export const DEFAULT_REFRESH_OPTIONS: RefreshMetadataOptions = {
  updateText: true,
  fillMissingArt: true,
  overwriteExistingArt: false,
};

export interface RefreshMetadataPreview {
  status: RefreshMetadataResult;
  provider: string | null;
  providerErrors: string[];
  changedFields: string[];
  skippedLockedFields: string[];
  wouldAddKeyArt: boolean;
  wouldAddBanner: boolean;
  gameUpdatedAt: number;
}

interface BackendMetadataRefreshResponse {
  status: RefreshMetadataResult;
  provider: string | null;
  provider_errors: string[];
  changed_fields: string[];
  skipped_locked_fields: string[];
  would_add_key_art: boolean;
  would_add_banner: boolean;
  game_updated_at: number;
}

async function requestGameMetadataRefresh(
  game: Game,
  options: RefreshMetadataOptions,
  dryRun: boolean,
): Promise<BackendMetadataRefreshResponse> {
  const response = await fetch(`/api/game/${game.id}/metadata/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      dry_run: dryRun,
      update_text: options.updateText,
      fill_missing_art: options.fillMissingArt,
      overwrite_existing_art: options.overwriteExistingArt,
      ...(dryRun || game.updatedAt === undefined
        ? {}
        : { expected_updated_at: game.updatedAt }),
    }),
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Metadata refresh failed: ${response.status} ${response.statusText} ${message}`,
    );
  }
  return await response.json();
}

export async function applyGameMetadataRefresh(
  game: Game,
  options: RefreshMetadataOptions = DEFAULT_REFRESH_OPTIONS,
): Promise<RefreshMetadataOutcome> {
  const raw = await requestGameMetadataRefresh(game, options, false);
  return {
    status: raw.status,
    provider: raw.provider,
    providerErrors: raw.provider_errors ?? [],
    changedFields: raw.changed_fields ?? [],
    skippedLockedFields: raw.skipped_locked_fields ?? [],
    keyArtAdded: raw.would_add_key_art,
    bannerAdded: raw.would_add_banner,
    gameUpdatedAt: raw.game_updated_at,
  };
}

export async function refreshGameMetadata(
  game: Game,
  options: RefreshMetadataOptions = DEFAULT_REFRESH_OPTIONS,
): Promise<RefreshMetadataOutcome> {
  try {
    const raw = await requestGameMetadataRefresh(game, options, false);
    return {
      status: raw.status,
      provider: raw.provider,
      providerErrors: raw.provider_errors ?? [],
      changedFields: raw.changed_fields ?? [],
      skippedLockedFields: raw.skipped_locked_fields ?? [],
      keyArtAdded: raw.would_add_key_art,
      bannerAdded: raw.would_add_banner,
      gameUpdatedAt: raw.game_updated_at,
    };
  } catch {
    return {
      status: "error",
      provider: null,
      providerErrors: [],
      changedFields: [],
      skippedLockedFields: [],
      keyArtAdded: false,
      bannerAdded: false,
      gameUpdatedAt: game.updatedAt ?? 0,
    };
  }
}

export async function previewGameMetadataRefresh(
  game: Game,
  options: RefreshMetadataOptions = DEFAULT_REFRESH_OPTIONS,
): Promise<RefreshMetadataPreview> {
  try {
    const raw = await requestGameMetadataRefresh(game, options, true);
    return {
      status: raw.status,
      provider: raw.provider,
      providerErrors: raw.provider_errors ?? [],
      changedFields: raw.changed_fields ?? [],
      skippedLockedFields: raw.skipped_locked_fields ?? [],
      wouldAddKeyArt: raw.would_add_key_art,
      wouldAddBanner: raw.would_add_banner,
      gameUpdatedAt: raw.game_updated_at,
    };
  } catch {
    return {
      status: "error",
      provider: null,
      providerErrors: [],
      changedFields: [],
      skippedLockedFields: [],
      wouldAddKeyArt: false,
      wouldAddBanner: false,
      gameUpdatedAt: game.updatedAt ?? 0,
    };
  }
}

export interface NewGameInput {
  title: string;
  sortTitle: string | null;
  folderLocation: string;
  status: GameStatus;
  description: string | null;
  developer: string | null;
  publisher: string | null;
  series: string | null;
  parentGameId: string | null;
  relationshipType: GameRelationshipType | null;
  releaseDate: string | null;
  dateAdded: string | null;
  completionDate: string | null;
  source: string | null;
  ageRating: string | null;
  timeToBeatHours: number | null;
  region: string | null;
  language: string | null;
  achievementsProvider: AchievementsProvider;
  ratingOverall: number | null;
  ratingStory: number | null;
  ratingGameplay: number | null;
  ratingSound: number | null;
  tags: string[];
  features: string[];
  links: GameLink[];
  ownership: GameOwnership;
  favorite: boolean;
  collections: string[];
  profilesEnabled: boolean;
  osrsStatsEnabled: boolean;
}

export async function createGame(input: NewGameInput): Promise<Game> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const newGame: Game = {
      id: crypto.randomUUID(),
      title: input.title,
      coverColor: "#2a2a2a",
      coverImageUrl: `https://picsum.photos/seed/${input.title}/1200/1800`,
      bannerImageUrl: `https://picsum.photos/seed/${input.title}-banner/1600/500`,
      status: input.status,
      ratingOverall: input.ratingOverall,
      ratingStory: input.ratingStory,
      ratingGameplay: input.ratingGameplay,
      ratingSound: input.ratingSound,
      achievementPercent: 0,
      achievementTotal: 0,
      achievements: [],
      description: input.description,
      developer: input.developer,
      publisher: input.publisher,
      series: input.series,
      parentGameId: input.parentGameId,
      relationshipType: input.relationshipType,
      dateAdded: input.dateAdded,
      resumeNote: null,
      lastPlayedAt: null,
      staleSince: null,
      profilesEnabled: input.profilesEnabled,
      osrsStatsEnabled: input.osrsStatsEnabled,
      completionDate: input.completionDate,
      tags: input.tags,
      features: input.features,
      folderLocation: input.folderLocation || null,
      releaseDate: input.releaseDate,
      source: input.source,
      ageRating: input.ageRating,
      timeToBeatHours: input.timeToBeatHours,
      region: input.region,
      language: input.language,
      achievementsProvider: input.achievementsProvider,
      links: input.links,
      ownership: input.ownership,
      platforms: [],
      favorite: input.favorite,
      collections: input.collections,
    };
    mockGames.push(newGame);
    return newGame;
  }

  const response = await fetch("/api/game/create", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title,
      sort_title: input.sortTitle,
      folder_location: input.folderLocation,
      status: denormalizeStatus(input.status),
      favorite: input.favorite,
      profiles_enabled: input.profilesEnabled,
      osrs_stats_enabled: input.osrsStatsEnabled,
      description: input.description,
      developer: input.developer,
      publisher: input.publisher,
      series: input.series,
      parent_game_id: input.parentGameId,
      relationship_type: input.relationshipType,
      release_date: input.releaseDate,
      source: input.source,
      age_rating: input.ageRating,
      time_to_beat_hours: input.timeToBeatHours,
      rating_overall: input.ratingOverall,
      rating_story: input.ratingStory,
      rating_gameplay: input.ratingGameplay,
      rating_soundtrack: input.ratingSound,
      tags: input.tags,
      features: input.features,
      links: input.links,
      purchase_date: dateInputToUnixSeconds(input.ownership.purchaseDate),
      completion_date: dateInputToUnixSeconds(input.completionDate),
      purchase_price: input.ownership.price,
      purchase_price_currency_code: input.ownership.priceCurrency,
      physical_condition: input.ownership.condition,
    }),
  });

  if (response.status === 409) {
    const body = await response.json();
    throw new Error(
      body.detail?.message ?? "A game with that folder name already exists.",
    );
  }

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to create game: ${response.status} ${response.statusText} ${message}`,
    );
  }

  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
}
function stripEmpty<T extends Record<string, unknown>>(obj: T): Partial<T> {
  const result: Partial<T> = {};
  for (const key in obj) {
    const value = obj[key];
    const isEmpty =
      value === null ||
      value === "" ||
      (Array.isArray(value) && value.length === 0);
    if (!isEmpty) result[key] = value;
  }
  return result;
}

export async function updateGame(
  id: string,
  input: NewGameInput,
): Promise<Game> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const index = mockGames.findIndex((g) => g.id === id);
    if (index === -1) throw new Error(`Game ${id} not found`);
    const updated: Game = {
      ...mockGames[index],
      title: input.title,
      status: input.status,
      ratingOverall: input.ratingOverall,
      ratingStory: input.ratingStory,
      ratingGameplay: input.ratingGameplay,
      ratingSound: input.ratingSound,
      description: input.description,
      developer: input.developer,
      publisher: input.publisher,
      series: input.series,
      parentGameId: input.parentGameId,
      relationshipType: input.relationshipType,
      dateAdded: input.dateAdded,
      lastPlayedAt: mockGames[index].lastPlayedAt,
      staleSince: mockGames[index].staleSince,
      profilesEnabled: input.profilesEnabled,
      osrsStatsEnabled: input.osrsStatsEnabled,
      completionDate: input.completionDate,
      tags: input.tags,
      folderLocation: input.folderLocation || null,
      releaseDate: input.releaseDate,
      source: input.source,
      ageRating: input.ageRating,
      timeToBeatHours: input.timeToBeatHours,
      region: input.region,
      language: input.language,
      achievementsProvider: input.achievementsProvider,
      links: input.links,
      ownership: input.ownership,
      features: input.features,
    };
    mockGames[index] = updated;
    return updated;
  }

  const body = stripEmpty({
    title: input.title,
    sort_title: input.sortTitle,
    folder_location: input.folderLocation,
    status: denormalizeStatus(input.status),
    favorite: input.favorite,
    profiles_enabled: input.profilesEnabled,
    osrs_stats_enabled: input.osrsStatsEnabled,
    description: input.description,
    developer: input.developer,
    publisher: input.publisher,
    series: input.series,
    parent_game_id: input.parentGameId,
    relationship_type: input.relationshipType,
    release_date: input.releaseDate,
    source: input.source,
    age_rating: input.ageRating,
    time_to_beat_hours: input.timeToBeatHours,
    rating_overall: input.ratingOverall,
    rating_story: input.ratingStory,
    rating_gameplay: input.ratingGameplay,
    rating_soundtrack: input.ratingSound,
    tags: input.tags,
    features: input.features,
    links: input.links,
    collections: input.collections,
    purchase_date: dateInputToUnixSeconds(input.ownership.purchaseDate),
    purchase_price: input.ownership.price,
    purchase_price_currency_code: input.ownership.priceCurrency,
    physical_condition: input.ownership.condition,
  });

  const response = await fetch(`/api/game/update/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (response.status === 409) {
    const errBody = await response.json();
    throw new Error(
      errBody.detail?.message ?? "A game with that folder name already exists.",
    );
  }

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to update game ${id}: ${response.status} ${response.statusText} ${message}`,
    );
  }

  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
}

export interface GameNoteListResponse {
  notes: string[];
}

export interface GameNoteWritePayload {
  content: string;
}

export interface GameNoteActionResponse {
  game_id: string;
  note_name: string;
  path?: string;
  status: "saved" | "deleted";
}

// per-game note storage for mock mode, resets on page reload, same as mockGames itself
const mockNotesStore = new Map<string, Map<string, string>>();
function getMockNoteMap(gameId: string): Map<string, string> {
  if (!mockNotesStore.has(gameId)) mockNotesStore.set(gameId, new Map());
  return mockNotesStore.get(gameId)!;
}

export async function listGameNotes(gameId: string): Promise<string[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return Array.from(getMockNoteMap(gameId).keys());
  }

  const response = await fetch(`/api/game/${gameId}/notes`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to list notes for game ${gameId}: ${response.status} ${response.statusText}`,
    );
  }

  const data: GameNoteListResponse = await response.json();
  return data.notes ?? [];
}

export async function fetchGameNote(
  gameId: string,
  noteName: string,
): Promise<string> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return getMockNoteMap(gameId).get(noteName) ?? "";
  }

  const response = await fetch(`/api/game/${gameId}/notes/${noteName}`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch note ${noteName}: ${response.status} ${response.statusText}`,
    );
  }

  return await response.text();
}

export async function saveGameNote(
  gameId: string,
  noteName: string,
  content: string,
): Promise<GameNoteActionResponse> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    getMockNoteMap(gameId).set(noteName, content);
    return { game_id: gameId, note_name: noteName, status: "saved" };
  }

  const response = await fetch(`/api/game/${gameId}/notes/${noteName}`, {
    method: "PUT",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ content }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to save note ${noteName}: ${response.status} ${response.statusText} ${message}`,
    );
  }

  return await response.json();
}

export async function deleteGameNote(
  gameId: string,
  noteName: string,
): Promise<GameNoteActionResponse> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    getMockNoteMap(gameId).delete(noteName);
    return { game_id: gameId, note_name: noteName, status: "deleted" };
  }

  const response = await fetch(`/api/game/${gameId}/notes/${noteName}`, {
    method: "DELETE",
    credentials: "include",
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to delete note ${noteName}: ${response.status} ${response.statusText} ${message}`,
    );
  }

  return await response.json();
}

export interface GameAssetUploadResponse {
  game_id: string;
  asset_kind: string;
  path: string;
  status: string;
}

export async function uploadGameAsset(
  gameId: string,
  assetKind: "key_art" | "banner" | "logo" | "icon",
  file: File,
): Promise<GameAssetUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`/api/game/${gameId}/assets/${assetKind}`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to upload ${assetKind}: ${response.status} ${response.statusText} ${message}`,
    );
  }

  return await response.json();
}

export async function attachGameAssetFromUrl(
  gameId: string,
  assetKind: "key_art" | "banner" | "logo" | "icon",
  url: string,
): Promise<GameAssetUploadResponse> {
  const response = await fetch(
    `/api/game/${gameId}/assets/${assetKind}/from-url`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    },
  );

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to fetch ${assetKind} from URL: ${response.status} ${response.statusText} ${message}`,
    );
  }

  return await response.json();
}

export async function setFavorite(
  gameId: string,
  favorite: boolean,
): Promise<Game> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const index = mockGames.findIndex((g) => g.id === gameId);
    if (index === -1) throw new Error(`Game ${gameId} not found`);
    mockGames[index] = { ...mockGames[index], favorite };
    return mockGames[index];
  }

  const response = await fetch(`/api/game/update/${gameId}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ favorite }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to update favorite: ${response.status} ${response.statusText} ${message}`,
    );
  }

  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
}

export async function setResumeNote(
  gameId: string,
  resumeNote: string | null,
): Promise<Game> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const index = mockGames.findIndex((g) => g.id === gameId);
    if (index === -1) throw new Error(`Game ${gameId} not found`);
    mockGames[index] = { ...mockGames[index], resumeNote };
    return mockGames[index];
  }

  const response = await fetch(`/api/game/update/${gameId}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_note: resumeNote }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to save resume note: ${response.status} ${response.statusText} ${message}`,
    );
  }

  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
}

export async function setPlaytimeSeconds(
  gameId: string,
  playtimeSeconds: number,
): Promise<Game> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const index = mockGames.findIndex((g) => g.id === gameId);
    if (index === -1) throw new Error(`Game ${gameId} not found`);
    mockGames[index] = {
      ...mockGames[index],
      platforms: mockGames[index].platforms.map((p, i) =>
        i === 0
          ? { ...p, playtimeMinutes: Math.round(playtimeSeconds / 60) }
          : p,
      ),
    };
    return mockGames[index];
  }

  const response = await fetch(`/api/game/update/${gameId}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ playtime_seconds: playtimeSeconds }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to update playtime: ${response.status} ${response.statusText} ${message}`,
    );
  }

  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
}

export async function setStatus(
  gameId: string,
  status: GameStatus,
): Promise<Game> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const index = mockGames.findIndex((g) => g.id === gameId);
    if (index === -1) throw new Error(`Game ${gameId} not found`);
    mockGames[index] = { ...mockGames[index], status };
    return mockGames[index];
  }

  const response = await fetch(`/api/game/update/${gameId}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: denormalizeStatus(status) }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to update status: ${response.status} ${response.statusText} ${message}`,
    );
  }

  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
}

// Deliberately narrower than NewGameInput/GameUpdate, title, folder,
// notes, playtime, purchase info, and ratings are per-game by nature and
// excluded so a bulk edit can't stamp one game's specifics onto many others.
export interface BulkEditFields {
  status?: GameStatus;
  favorite?: boolean;
  developer?: string | null;
  publisher?: string | null;
  series?: string | null;
  ageRating?: string | null;
  tags?: string[];
  features?: string[];
}

export async function bulkUpdateGames(
  gameIds: string[],
  fields: BulkEditFields,
): Promise<number> {
  const payload: Record<string, unknown> = { game_ids: gameIds };
  if (fields.status !== undefined)
    payload.status = denormalizeStatus(fields.status);
  if (fields.favorite !== undefined) payload.favorite = fields.favorite;
  if (fields.developer !== undefined) payload.developer = fields.developer;
  if (fields.publisher !== undefined) payload.publisher = fields.publisher;
  if (fields.series !== undefined) payload.series = fields.series;
  if (fields.ageRating !== undefined) payload.age_rating = fields.ageRating;
  if (fields.tags !== undefined) payload.tags = fields.tags;
  if (fields.features !== undefined) payload.features = fields.features;

  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    let count = 0;
    for (const game of mockGames) {
      if (!gameIds.includes(game.id)) continue;
      if (fields.status !== undefined) game.status = fields.status;
      if (fields.favorite !== undefined) game.favorite = fields.favorite;
      if (fields.developer !== undefined) game.developer = fields.developer;
      if (fields.publisher !== undefined) game.publisher = fields.publisher;
      if (fields.series !== undefined) game.series = fields.series;
      if (fields.ageRating !== undefined) game.ageRating = fields.ageRating;
      if (fields.tags !== undefined) game.tags = fields.tags;
      if (fields.features !== undefined) game.features = fields.features;
      count++;
    }
    return count;
  }

  const response = await fetch("/api/game/bulk-update", {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to bulk-update games: ${response.status} ${response.statusText} ${message}`,
    );
  }
  const result: { updated: number } = await response.json();
  return result.updated;
}

// PATCHes `collections` directly rather than going through updateGame's
// NewGameInput/stripEmpty path, stripEmpty treats an empty array as "leave
// untouched", which would make removing a game's last collection silently
// no-op.
async function patchCollections(
  gameId: string,
  collections: string[],
): Promise<Game> {
  const response = await fetch(`/api/game/update/${gameId}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ collections }),
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to update collections for ${gameId}: ${response.status} ${response.statusText} ${message}`,
    );
  }
  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
}

export async function addGameToCollection(
  gameId: string,
  collectionName: string,
): Promise<Game> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const index = mockGames.findIndex((g) => g.id === gameId);
    if (index === -1) throw new Error(`Game ${gameId} not found`);
    const existing = mockGames[index].collections;
    const collections = existing.includes(collectionName)
      ? existing
      : [...existing, collectionName];
    mockGames[index] = { ...mockGames[index], collections };
    return mockGames[index];
  }

  const game = await fetchGame(gameId);
  if (!game) throw new Error(`Game ${gameId} not found`);
  if (game.collections.includes(collectionName)) return game;
  return patchCollections(gameId, [...game.collections, collectionName]);
}

export async function removeGameFromCollection(
  gameId: string,
  collectionName: string,
): Promise<Game> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const index = mockGames.findIndex((g) => g.id === gameId);
    if (index === -1) throw new Error(`Game ${gameId} not found`);
    const collections = mockGames[index].collections.filter(
      (c) => c !== collectionName,
    );
    mockGames[index] = { ...mockGames[index], collections };
    return mockGames[index];
  }

  const game = await fetchGame(gameId);
  if (!game) throw new Error(`Game ${gameId} not found`);
  return patchCollections(
    gameId,
    game.collections.filter((c) => c !== collectionName),
  );
}

export async function deleteGame(gameId: string): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const index = mockGames.findIndex((g) => g.id === gameId);
    if (index !== -1) mockGames.splice(index, 1);
    return;
  }

  const response = await fetch(`/api/game/delete/${gameId}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    const message = await response.text();
    throw new Error(
      `Failed to delete game ${gameId}: ${response.status} ${response.statusText} ${message}`,
    );
  }
}

// deleteGame is a soft-delete (see the backend route), restorable for 7
// days via these, same pattern as game archives/inbox media
export interface TrashedGame {
  id: string;
  title: string;
  deleted_at: number;
  purge_at: number;
}

export async function fetchGameTrash(): Promise<TrashedGame[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const response = await fetch("/api/game/trash", { credentials: "include" });
  if (!response.ok)
    throw new Error(
      `Failed to fetch game trash: ${response.status} ${response.statusText}`,
    );
  return await response.json();
}

export async function restoreGame(gameId: string): Promise<void> {
  const response = await fetch(`/api/game/${gameId}/restore`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to restore game: ${response.status} ${response.statusText} ${message}`,
    );
  }
}
