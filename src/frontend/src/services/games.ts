import { mockGames } from "../data/mockGames";
import { failedRequest } from "./apiError";
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
  platform: string | null;
  region: string | null;
  language: string | null;
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

// mirrors the backend's _derive_sort_title ('The Witcher 3' -> 'witcher 3'),
// so a derived sorting name isn't shown back to the user as a custom one
function deriveSortTitle(title: string): string {
  return title
    .replace(/^(the|a|an)\s+/i, "")
    .trim()
    .toLowerCase();
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
    resumeNote: raw.resume_note,
    lastPlayedAt: unixSecondsToIso(raw.last_played_at),
    staleSince: unixSecondsToIso(raw.stale_since),
    profilesEnabled: raw.profiles_enabled,
    osrsStatsEnabled: raw.osrs_stats_enabled,
    completionDate: unixSecondsToDateInput(raw.completion_date),
    folderLocation: raw.folder_location,
    releaseDate: raw.release_date,
    source: raw.source,
    platform: raw.platform,
    priority: raw.priority,
    // only a sorting name someone chose, not the one derived from the title
    sortTitle:
      raw.sort_title === deriveSortTitle(raw.title) ? null : raw.sort_title,
    ageRating: raw.age_rating,
    timeToBeatHours: toNumberOrNull(raw.time_to_beat_hours),
    region: raw.region ?? null,
    language: raw.language ?? null,
    // not stored per game: a RetroAchievements library sync is the one
    // source whose achievements come from somewhere other than the store
    achievementsProvider:
      raw.source?.toLowerCase() === "retroachievements"
        ? "retroachievements"
        : null,
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
    // data, synthesize a single entry labeled by the platform the game is
    // played on, else where it came from (Steam/GOG/PlayStation/etc.),
    // falling back to "PC" only when neither is known
    platforms: [
      {
        platform: raw.platform || raw.source || "PC",
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
  if (!response.ok) throw await failedRequest(response);
  return await response.json();
}

// Providers return results grouped by provider, not by how well they match,
// so an exact title match could sit below a dozen loose ones. Exact matches
// first, then titles starting with the query, then containing it, keeping
// the providers' own order within each group.
export function rankMetadataResults<T extends { title: string }>(
  results: T[],
  query: string,
): T[] {
  const q = normalizeTitleForMatch(query);
  const rank = (title: string): number => {
    const t = normalizeTitleForMatch(title);
    if (!q) return 0;
    if (t === q) return 0;
    if (t.startsWith(q)) return 1;
    if (t.includes(q)) return 2;
    return 3;
  };
  return results
    .map((result, index) => ({ result, index, rank: rank(result.title) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map(({ result }) => result);
}

export type RefreshMetadataResult = "updated" | "no-match" | "error";

export interface RefreshMetadataOutcome {
  status: RefreshMetadataResult;
  keyArtAdded: boolean;
  bannerAdded: boolean;
}

export interface RefreshMetadataOptions {
  // re-fetch description/developer/publisher/release date/age rating/tags/
  // features, always a full refresh, replacing whatever's already there.
  // Unlike art, text has no "did a person put this here on purpose" case:
  // it's either provider data or something you typed in the edit form, and
  // a refresh is explicitly asking for the provider's current answer. (A
  // fresh result that comes back blank still never blanks an existing
  // value, see mergeField below, that's a "provider didn't have this
  // field" case, not a "the truth is now blank" case.)
  updateText: boolean;
  // fetch cover + banner art for games that currently have none
  fillMissingArt: boolean;
  // replace art even on games that already have some, off by default since
  // this is the one setting that can actually destroy something you set
  // deliberately (a manually-uploaded cover, art from an earlier refresh)
  overwriteExistingArt: boolean;
}

export const DEFAULT_REFRESH_OPTIONS: RefreshMetadataOptions = {
  updateText: true,
  fillMissingArt: true,
  overwriteExistingArt: false,
};

// never actively replaces an existing value with a blank fresh one, the
// bug this exists to fix: refreshing metadata could wipe out a field the
// user had set/edited just because this particular search result didn't
// happen to include it
function mergeField<T>(
  existing: T | null | undefined,
  fresh: T | null | undefined,
  overwrite: boolean,
): T | null {
  const existingValue = existing ?? null;
  const freshValue = fresh ?? null;
  if (overwrite) return freshValue ?? existingValue;
  return existingValue ?? freshValue;
}

async function gameAssetExists(
  gameId: string,
  assetKind: "key_art" | "banner",
): Promise<boolean> {
  const response = await fetch(`/api/game/${gameId}/assets/${assetKind}`, {
    credentials: "include",
  });
  return response.ok;
}

// Steam's storefront search routinely includes ™/® in the marketing title
// (e.g. "Apex Legends™") while a library-synced game's title rarely does,
// comparing raw strings silently failed the exact-match gate below for a
// large fraction of perfectly normal titles.
function normalizeTitleForMatch(title: string): string {
  return title.replace(/[™®©]/g, "").trim().toLowerCase();
}

// Re-pulls metadata for one game from Steam (+ SteamGridDB art data) and
// applies whichever pieces `options` asks for. Only applies anything when a
// result's title matches the game's current title exactly (case-insensitive)
//, a fuzzy/no match is reported back rather than guessing. Never touches
// notes (a wholly separate API this never calls). Image behavior is fully
// opt-in per `options`: by default a currently-blank slot can be filled in,
// but nothing already set is replaced unless overwriteExistingArt is on.
export async function refreshGameMetadata(
  game: Game,
  options: RefreshMetadataOptions = DEFAULT_REFRESH_OPTIONS,
): Promise<RefreshMetadataOutcome> {
  const outcome: RefreshMetadataOutcome = {
    status: "error",
    keyArtAdded: false,
    bannerAdded: false,
  };
  try {
    const { results } = await searchGameMetadata(game.title);
    const match = results.find(
      (r) =>
        normalizeTitleForMatch(r.title) === normalizeTitleForMatch(game.title),
    );
    if (!match) {
      outcome.status = "no-match";
      return outcome;
    }

    if (options.updateText) {
      // text is always a full refresh (see RefreshMetadataOptions.updateText)
      //, mergeField/mergeArr still refuse to blank a field the fresh
      // result simply didn't have, they just always prefer fresh when it's
      // there
      const overwrite = true;
      const mergeArr = (
        existing: string[] | undefined,
        fresh: string[] | undefined,
      ): string[] => {
        const e = existing?.length ? existing : [];
        const f = fresh?.length ? fresh : [];
        return f.length ? f : e;
      };
      const input: NewGameInput = {
        title: game.title,
        folderLocation: game.folderLocation ?? "",
        status: game.status,
        description: mergeField(game.description, match.description, overwrite),
        developer: mergeField(game.developer, match.developer, overwrite),
        publisher: mergeField(game.publisher, match.publisher, overwrite),
        series: mergeField(game.series, match.series, overwrite),
        parentGameId: game.parentGameId,
        relationshipType: game.relationshipType,
        releaseDate: mergeField(
          game.releaseDate,
          match.release_date,
          overwrite,
        ),
        dateAdded: game.dateAdded,
        completionDate: game.completionDate,
        // never touched by a metadata refresh, this is "how the game got
        // into the library" (Steam sync, GOG sync, manual...), not "which
        // provider happened to match this search," and overwriting it here
        // used to silently break the library-sync game counts in Settings
        source: game.source,
        ageRating: mergeField(game.ageRating, match.age_rating, overwrite),
        timeToBeatHours: mergeField(
          game.timeToBeatHours,
          toNumberOrNull(match.time_to_beat_hours),
          overwrite,
        ),
        region: game.region,
        language: game.language,
        achievementsProvider: game.achievementsProvider,
        ratingOverall: game.ratingOverall,
        ratingStory: game.ratingStory,
        ratingGameplay: game.ratingGameplay,
        ratingSound: game.ratingSound,
        tags: mergeArr(game.tags, match.tags),
        features: mergeArr(game.features, match.features),
        links: match.links?.length ? match.links : game.links,
        ownership: game.ownership,
        favorite: game.favorite,
        collections: game.collections,
        profilesEnabled: game.profilesEnabled,
        osrsStatsEnabled: game.osrsStatsEnabled,
      };
      await updateGame(game.id, input);
    }
    outcome.status = "updated";

    if (
      import.meta.env.VITE_USE_MOCK_DATA !== "true" &&
      (options.fillMissingArt || options.overwriteExistingArt)
    ) {
      if (
        match.key_art_url &&
        (options.overwriteExistingArt ||
          !(await gameAssetExists(game.id, "key_art")))
      ) {
        await attachGameAssetFromUrl(game.id, "key_art", match.key_art_url);
        outcome.keyArtAdded = true;
      }
      if (
        match.banner_url &&
        (options.overwriteExistingArt ||
          !(await gameAssetExists(game.id, "banner")))
      ) {
        await attachGameAssetFromUrl(game.id, "banner", match.banner_url);
        outcome.bannerAdded = true;
      }
    }

    return outcome;
  } catch {
    outcome.status = "error";
    return outcome;
  }
}

export interface RefreshMetadataPreview {
  status: RefreshMetadataResult;
  // human-readable field names that would actually change, computed the
  // same way refreshGameMetadata would apply them, but nothing is written
  changedFields: string[];
  wouldAddKeyArt: boolean;
  wouldAddBanner: boolean;
}

// Read-only dry run of refreshGameMetadata: same search + same exact-title
// match + same merge logic, but never calls updateGame/attachGameAssetFromUrl
//, used to show "this is what refreshing would actually change" before the
// user commits to a real bulk refresh.
export async function previewGameMetadataRefresh(
  game: Game,
  options: RefreshMetadataOptions = DEFAULT_REFRESH_OPTIONS,
): Promise<RefreshMetadataPreview> {
  const preview: RefreshMetadataPreview = {
    status: "error",
    changedFields: [],
    wouldAddKeyArt: false,
    wouldAddBanner: false,
  };
  try {
    const { results } = await searchGameMetadata(game.title);
    const match = results.find(
      (r) =>
        normalizeTitleForMatch(r.title) === normalizeTitleForMatch(game.title),
    );
    if (!match) {
      preview.status = "no-match";
      return preview;
    }
    preview.status = "updated";

    if (options.updateText) {
      const textChecks: [
        string,
        string | number | null | undefined,
        string | number | null | undefined,
      ][] = [
        ["description", game.description, match.description],
        ["developer", game.developer, match.developer],
        ["publisher", game.publisher, match.publisher],
        ["series", game.series, match.series],
        ["release date", game.releaseDate, match.release_date],
        ["age rating", game.ageRating, match.age_rating],
        [
          "time to beat",
          game.timeToBeatHours,
          toNumberOrNull(match.time_to_beat_hours),
        ],
      ];
      for (const [label, existing, fresh] of textChecks) {
        if (fresh != null && fresh !== (existing ?? null))
          preview.changedFields.push(label);
      }
      if (
        match.tags?.length &&
        JSON.stringify(match.tags) !== JSON.stringify(game.tags)
      )
        preview.changedFields.push("tags");
      if (
        match.features?.length &&
        JSON.stringify(match.features) !== JSON.stringify(game.features)
      )
        preview.changedFields.push("features");
    }

    if (
      import.meta.env.VITE_USE_MOCK_DATA !== "true" &&
      (options.fillMissingArt || options.overwriteExistingArt)
    ) {
      if (
        match.key_art_url &&
        (options.overwriteExistingArt ||
          !(await gameAssetExists(game.id, "key_art")))
      ) {
        preview.wouldAddKeyArt = true;
      }
      if (
        match.banner_url &&
        (options.overwriteExistingArt ||
          !(await gameAssetExists(game.id, "banner")))
      ) {
        preview.wouldAddBanner = true;
      }
    }
    return preview;
  } catch {
    preview.status = "error";
    return preview;
  }
}

export interface NewGameInput {
  title: string;
  // undefined leaves the saved sorting name alone, null resets it to the title
  sortTitle?: string | null;
  // undefined leaves the saved value alone on update
  platform?: string | null;
  priority?: string | null;
  // unix seconds; only sent when set, to back-date when the game was added
  createdAt?: number | null;
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
      platform: input.platform ?? null,
      priority: input.priority ?? null,
      region: input.region,
      language: input.language,
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
      ...(input.createdAt != null ? { created_at: input.createdAt } : {}),
    }),
  });

  // 409 (folder name taken) carries its own message, see friendlyError
  if (!response.ok) throw await failedRequest(response);

  const raw: BackendGame = await response.json();
  return mapBackendGame(raw);
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

  // Every field is sent, including nulls and empty lists, so clearing a
  // field in the form actually clears it (dropping empty values used to make
  // that impossible). Fields the caller leaves undefined are left alone.
  const body: Record<string, unknown> = {
    title: input.title,
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
    region: input.region,
    language: input.language,
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
    completion_date: dateInputToUnixSeconds(input.completionDate),
    purchase_price: input.ownership.price,
    purchase_price_currency_code: input.ownership.priceCurrency,
    physical_condition: input.ownership.condition,
  };
  // blank means "keep the current folder" (see the edit form's placeholder)
  if (input.folderLocation) body.folder_location = input.folderLocation;
  if (input.sortTitle !== undefined) body.sort_title = input.sortTitle;
  if (input.platform !== undefined) body.platform = input.platform;
  if (input.priority !== undefined) body.priority = input.priority;
  if (input.createdAt != null) body.created_at = input.createdAt;

  const response = await fetch(`/api/game/update/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) throw await failedRequest(response);

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
    throw new Error("The game notes could not be loaded.");
  }

  const data: GameNoteListResponse = await response.json();
  return data.notes ?? [];
}

async function noteErrorMessage(
  response: Response,
  action: "create" | "save" | "rename" | "load" | "delete",
  noteName: string,
): Promise<string> {
  if (response.status === 409) {
    return `A note titled "${noteName}" already exists. Choose a different title or cancel the operation.`;
  }
  if (response.status === 400) {
    return `The note title "${noteName}" is not valid. Use a normal title without path separators or control characters.`;
  }
  if (response.status === 404) {
    return action === "load"
      ? `The note "${noteName}" could not be found.`
      : `The note "${noteName}" no longer exists.`;
  }
  if (action === "rename")
    return `The note "${noteName}" could not be renamed.`;
  if (action === "delete")
    return `The note "${noteName}" could not be deleted.`;
  if (action === "load") return `The note "${noteName}" could not be loaded.`;
  return `The note "${noteName}" could not be saved.`;
}

export async function fetchGameNote(
  gameId: string,
  noteName: string,
): Promise<string> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return getMockNoteMap(gameId).get(noteName) ?? "";
  }
  const response = await fetch(
    `/api/game/${gameId}/notes/${encodeURIComponent(noteName)}`,
    {
      credentials: "include",
    },
  );
  if (!response.ok)
    throw new Error(await noteErrorMessage(response, "load", noteName));
  return await response.text();
}

export async function createGameNote(
  gameId: string,
  noteName: string,
  content: string,
): Promise<GameNoteActionResponse> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const notes = getMockNoteMap(gameId);
    if (notes.has(noteName))
      throw new Error(
        `A note titled "${noteName}" already exists. Choose a different title or cancel the operation.`,
      );
    notes.set(noteName, content);
    return { game_id: gameId, note_name: noteName, status: "saved" };
  }
  const response = await fetch(
    `/api/game/${gameId}/notes/${encodeURIComponent(noteName)}`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
  if (!response.ok)
    throw new Error(await noteErrorMessage(response, "create", noteName));
  return await response.json();
}

export async function saveGameNote(
  gameId: string,
  noteName: string,
  content: string,
): Promise<GameNoteActionResponse> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const notes = getMockNoteMap(gameId);
    if (!notes.has(noteName))
      throw new Error(`The note "${noteName}" no longer exists.`);
    notes.set(noteName, content);
    return { game_id: gameId, note_name: noteName, status: "saved" };
  }
  const response = await fetch(
    `/api/game/${gameId}/notes/${encodeURIComponent(noteName)}`,
    {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
  if (!response.ok)
    throw new Error(await noteErrorMessage(response, "save", noteName));
  return await response.json();
}

export async function renameGameNote(
  gameId: string,
  noteName: string,
  newName: string,
): Promise<GameNoteActionResponse> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    const notes = getMockNoteMap(gameId);
    if (!notes.has(noteName))
      throw new Error(`The note "${noteName}" no longer exists.`);
    if (noteName !== newName && notes.has(newName)) {
      throw new Error(
        `A note titled "${newName}" already exists. Choose a different title or cancel the operation.`,
      );
    }
    const content = notes.get(noteName) ?? "";
    if (noteName !== newName) {
      notes.delete(noteName);
      notes.set(newName, content);
    }
    return { game_id: gameId, note_name: newName, status: "saved" };
  }
  const response = await fetch(
    `/api/game/${gameId}/notes/${encodeURIComponent(noteName)}/rename`,
    {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: newName }),
    },
  );
  if (!response.ok)
    throw new Error(await noteErrorMessage(response, "rename", newName));
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

  const response = await fetch(
    `/api/game/${gameId}/notes/${encodeURIComponent(noteName)}`,
    {
      method: "DELETE",
      credentials: "include",
    },
  );

  if (!response.ok) {
    throw new Error(await noteErrorMessage(response, "delete", noteName));
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
  platform?: string | null;
  priority?: string | null;
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
  if (fields.platform !== undefined) payload.platform = fields.platform;
  if (fields.priority !== undefined) payload.priority = fields.priority;
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
  if (!response.ok) throw await failedRequest(response);
  const result: { updated: number } = await response.json();
  return result.updated;
}

// PATCHes `collections` alone rather than the whole game through updateGame,
// so adding/removing a collection can't overwrite an edit made elsewhere in
// the meantime.
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
  if (!response.ok) throw await failedRequest(response);
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
