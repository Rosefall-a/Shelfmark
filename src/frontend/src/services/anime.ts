import { failedRequest } from "./apiError";
import type { PaginatedResponse } from "../types/pagination";
import type {
  Anime,
  AnimeEpisode,
  AnimeSeason,
  AnimeStatus,
} from "../types/anime";

// The exact shape FastAPI sends, snake_case, matching the Python model
// field-for-field. Nothing outside this file should ever see raw backend
// data directly.
interface BackendEpisode {
  id: string;
  season_id: string;
  episode_number: number;
  title: string | null;
  description: string | null;
  air_date: string | null;
  runtime_minutes: number | null;
  still_url: string | null;
  watched: boolean;
  rating: number | string | null;
  note: string | null;
  created_at: number;
  updated_at: number;
}

interface BackendSeason {
  id: string;
  show_id: string;
  season_number: number;
  name: string | null;
  episode_count: number | null;
  episodes_watched: number;
  status: string;
  air_date: string | null;
  poster_url: string | null;
  episodes?: BackendEpisode[];
  created_at: number;
  updated_at: number;
}

export interface BackendAnime {
  id: string;
  user_id: string;
  title: string;
  title_english?: string | null;
  title_romaji?: string | null;
  title_native?: string | null;
  sort_title: string;
  description: string | null;
  first_air_date: string | null;
  episode_runtime_minutes: number | null;
  studios: string[];
  countries: string[];
  languages: string[];
  genres: string[];
  tags: string[];
  features: string[];
  age_rating: string | null;
  format: string | null;
  anilist_score: number | string | null;
  mal_score: number | string | null;
  source: string | null;
  external_id: string | null;
  anilist_id: string | null;
  poster_url: string | null;
  backdrop_url: string | null;
  status: string;
  priority: string | null;
  favorite: boolean;
  rewatches: number;
  note: string | null;
  start_date: string | null;
  end_date: string | null;
  rating_story: number | string | null;
  rating_performance: number | string | null;
  rating_soundtrack: number | string | null;
  rating_overall: number | string | null;
  personal_rank: number | null;
  locked_fields: string[];
  seasons: BackendSeason[];
  // unix timestamps in seconds, not ISO strings
  created_at: number;
  updated_at: number;

  kitsu_id: string | null;
  is_airing: boolean | null;
  next_episode_air_at: number | null;
  next_episode_number: number | null;
  airing_interval_days: number | null;
  linked_tv_show_id: string | null;
  linked_movie_id: string | null;
}

import { createEntityCache } from "../utils/entityCache";
const animeCache = createEntityCache<Anime>();
export const peekAnime = animeCache.peek;
export const peekAllAnimes = (): Anime[] | null =>
  animeCache.listLoaded() ? animeCache.all() : null;
// every entity that passes through here is remembered for instant reopening
function mapBackendAnime(raw: Parameters<typeof mapBackendAnimeRaw>[0]): Anime {
  return animeCache.put(mapBackendAnimeRaw(raw));
}

// Pydantic can serialize a Decimal as either a JSON number or a string
// depending on config, handle both rather than assume one
function toNumberOrNull(value: number | string | null): number | null {
  return value === null ? null : Number(value);
}

function unixSecondsToIso(seconds: number): string {
  return new Date(seconds * 1000).toISOString();
}

// backend sends "IN_PROGRESS", "WISHLIST", etc., frontend expects
// 'in progress', 'wishlist' (lowercase, spaces not underscores)
function normalizeStatus(raw: string): AnimeStatus {
  return raw.toLowerCase().replace(/_/g, " ") as AnimeStatus;
}
// inverse of normalizeStatus, 'in progress' -> 'IN_PROGRESS'
function denormalizeStatus(status: AnimeStatus): string {
  return status.toUpperCase().replace(/ /g, "_");
}

function mapBackendEpisode(raw: BackendEpisode): AnimeEpisode {
  return {
    id: raw.id,
    seasonId: raw.season_id,
    episodeNumber: raw.episode_number,
    title: raw.title,
    description: raw.description,
    airDate: raw.air_date,
    runtimeMinutes: raw.runtime_minutes,
    stillUrl: raw.still_url,
    watched: raw.watched,
    rating: toNumberOrNull(raw.rating),
    note: raw.note ?? null,
    createdAt: unixSecondsToIso(raw.created_at),
    updatedAt: unixSecondsToIso(raw.updated_at),
  };
}

function mapBackendSeason(raw: BackendSeason): AnimeSeason {
  return {
    id: raw.id,
    showId: raw.show_id,
    seasonNumber: raw.season_number,
    name: raw.name,
    episodeCount: raw.episode_count,
    episodesWatched: raw.episodes_watched,
    status: normalizeStatus(raw.status),
    airDate: raw.air_date,
    posterUrl: raw.poster_url,
    episodes: (raw.episodes ?? []).map(mapBackendEpisode),
    createdAt: unixSecondsToIso(raw.created_at),
    updatedAt: unixSecondsToIso(raw.updated_at),
  };
}

export function mapBackendAnimeRaw(raw: BackendAnime): Anime {
  return {
    id: raw.id,
    userId: raw.user_id,
    title: raw.title,
    titleEnglish: raw.title_english ?? null,
    titleRomaji: raw.title_romaji ?? null,
    titleNative: raw.title_native ?? null,
    sortTitle: raw.sort_title,
    description: raw.description,
    firstAirDate: raw.first_air_date,
    episodeRuntimeMinutes: raw.episode_runtime_minutes,
    studios: raw.studios,
    countries: raw.countries,
    languages: raw.languages,
    genres: raw.genres,
    tags: raw.tags,
    features: raw.features,
    ageRating: raw.age_rating,
    format: raw.format,
    anilistScore: toNumberOrNull(raw.anilist_score),
    malScore: toNumberOrNull(raw.mal_score),
    source: raw.source,
    externalId: raw.external_id,
    anilistId: raw.anilist_id,
    posterUrl: raw.poster_url,
    backdropUrl: raw.backdrop_url,
    status: normalizeStatus(raw.status),
    priority: raw.priority,
    favorite: raw.favorite,
    rewatches: raw.rewatches,
    note: raw.note,
    startDate: raw.start_date,
    endDate: raw.end_date,
    ratingStory: toNumberOrNull(raw.rating_story),
    ratingPerformance: toNumberOrNull(raw.rating_performance),
    ratingSoundtrack: toNumberOrNull(raw.rating_soundtrack),
    ratingOverall: toNumberOrNull(raw.rating_overall),
    personalRank: raw.personal_rank,
    lockedFields: raw.locked_fields,
    seasons: raw.seasons.map(mapBackendSeason),
    createdAt: unixSecondsToIso(raw.created_at),
    updatedAt: unixSecondsToIso(raw.updated_at),
    kitsuId: raw.kitsu_id,
    isAiring: raw.is_airing,
    nextEpisodeAirAt: raw.next_episode_air_at,
    nextEpisodeNumber: raw.next_episode_number,
    airingIntervalDays: raw.airing_interval_days ?? null,
    linkedTvShowId: raw.linked_tv_show_id,
    linkedMovieId: raw.linked_movie_id,
  };
}

async function handle<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    console.warn(`Failed to ${action}: ${response.status}`);
    throw await failedRequest(response);
  }
  return response.json();
}

export async function fetchAnimePage(
  offset = 0,
  limit = 100,
  search = "",
): Promise<{
  items: Anime[];
  total: number;
  offset: number;
  limit: number;
  statusCounts: Record<string, number>;
}> {
  const params = new URLSearchParams({
    skip: String(offset),
    limit: String(limit),
  });
  if (search.trim()) params.set("search", search.trim());
  const response = await fetch(`/api/anime/list?${params}`, {
    credentials: "include",
  });
  const page = await handle<PaginatedResponse<BackendAnime>>(
    response,
    "fetch anime",
  );
  return {
    items: page.items.map(mapBackendAnime),
    total: page.total,
    offset: page.offset,
    limit: page.limit,
    statusCounts: page.status_counts,
  };
}

export async function fetchAnime(search = ""): Promise<Anime[]> {
  const all: Anime[] = [];
  let offset = 0;
  const limit = 100;
  while (true) {
    const page = await fetchAnimePage(offset, limit, search);
    all.push(...page.items);
    if (all.length >= page.total || page.items.length === 0) break;
    offset += page.items.length;
  }
  animeCache.markListLoaded();
  return all;
}

export async function getAnime(id: string): Promise<Anime> {
  const response = await fetch(`/api/anime/get/${id}`, {
    credentials: "include",
  });
  const raw = await handle<BackendAnime>(response, `fetch anime ${id}`);
  return mapBackendAnime(raw);
}

export interface SeasonInput {
  seasonNumber: number;
  name?: string | null;
  episodeCount?: number | null;
  airDate?: string | null;
  posterUrl?: string | null;
}

function seasonInputToBody(input: SeasonInput): Record<string, unknown> {
  return {
    season_number: input.seasonNumber,
    name: input.name ?? null,
    episode_count: input.episodeCount ?? null,
    air_date: input.airDate ?? null,
    poster_url: input.posterUrl ?? null,
  };
}

export interface AnimeInput {
  title: string;
  description?: string | null;
  firstAirDate?: string | null;
  episodeRuntimeMinutes?: number | null;
  studios?: string[];
  countries?: string[];
  languages?: string[];
  genres?: string[];
  tags?: string[];
  features?: string[];
  ageRating?: string | null;
  format?: string | null;
  anilistScore?: number | null;
  malScore?: number | null;
  source?: string | null;
  externalId?: string | null;
  anilistId?: string | null;
  posterUrl?: string | null;
  backdropUrl?: string | null;
  status?: AnimeStatus;
  priority?: string | null;
  favorite?: boolean;
  rewatches?: number;
  note?: string | null;
  startDate?: string | null;
  endDate?: string | null;
  ratingStory?: number | null;
  ratingPerformance?: number | null;
  ratingSoundtrack?: number | null;
  ratingOverall?: number | null;
  personalRank?: number | null;
  // days between episodes; null/absent = the weekly default
  airingIntervalDays?: number | null;
  linkedTvShowId?: string | null;
  linkedMovieId?: string | null;
  // omitted entirely (not just an empty array) means "auto-create a
  // default Season 1" — see create_anime on the backend
  seasons?: SeasonInput[];
}

// Round-trips a loaded Anime back into AnimeInput shape — used when a
// caller needs to change one field (e.g. toggling favorite from the
// detail page) without reopening the full edit form, since updateAnime
// always sends every field rather than a true partial patch.
export function animeToInput(show: Anime): AnimeInput {
  return {
    title: show.title,
    description: show.description,
    firstAirDate: show.firstAirDate,
    episodeRuntimeMinutes: show.episodeRuntimeMinutes,
    studios: show.studios,
    countries: show.countries,
    languages: show.languages,
    genres: show.genres,
    tags: show.tags,
    features: show.features,
    ageRating: show.ageRating,
    format: show.format,
    anilistScore: show.anilistScore,
    malScore: show.malScore,
    source: show.source,
    externalId: show.externalId,
    anilistId: show.anilistId,
    posterUrl: show.posterUrl,
    backdropUrl: show.backdropUrl,
    status: show.status,
    priority: show.priority,
    favorite: show.favorite,
    rewatches: show.rewatches,
    note: show.note,
    startDate: show.startDate,
    endDate: show.endDate,
    ratingStory: show.ratingStory,
    ratingPerformance: show.ratingPerformance,
    ratingSoundtrack: show.ratingSoundtrack,
    ratingOverall: show.ratingOverall,
    personalRank: show.personalRank,
    airingIntervalDays: show.airingIntervalDays,
    linkedTvShowId: show.linkedTvShowId,
    linkedMovieId: show.linkedMovieId,
  };
}

function inputToBody(input: AnimeInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    title: input.title,
    description: input.description ?? null,
    first_air_date: input.firstAirDate ?? null,
    episode_runtime_minutes: input.episodeRuntimeMinutes ?? null,
    studios: input.studios ?? [],
    countries: input.countries ?? [],
    languages: input.languages ?? [],
    genres: input.genres ?? [],
    tags: input.tags ?? [],
    features: input.features ?? [],
    age_rating: input.ageRating ?? null,
    format: input.format ?? null,
    anilist_score: input.anilistScore ?? null,
    mal_score: input.malScore ?? null,
    source: input.source ?? null,
    external_id: input.externalId ?? null,
    anilist_id: input.anilistId ?? null,
    poster_url: input.posterUrl ?? null,
    backdrop_url: input.backdropUrl ?? null,
    priority: input.priority ?? null,
    favorite: input.favorite ?? false,
    rewatches: input.rewatches ?? 0,
    note: input.note ?? null,
    start_date: input.startDate ?? null,
    end_date: input.endDate ?? null,
    rating_story: input.ratingStory ?? null,
    rating_performance: input.ratingPerformance ?? null,
    rating_soundtrack: input.ratingSoundtrack ?? null,
    rating_overall: input.ratingOverall ?? null,
    personal_rank: input.personalRank ?? null,
    linked_tv_show_id: input.linkedTvShowId ?? null,
    linked_movie_id: input.linkedMovieId ?? null,
  };
  if (input.airingIntervalDays !== undefined)
    body.airing_interval_days = input.airingIntervalDays;
  if (input.status) body.status = denormalizeStatus(input.status);
  if (input.seasons) body.seasons = input.seasons.map(seasonInputToBody);
  return body;
}

export async function createAnime(input: AnimeInput): Promise<Anime> {
  const response = await fetch("/api/anime/create", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputToBody(input)),
  });
  const raw = await handle<BackendAnime>(response, "create anime");
  return mapBackendAnime(raw);
}

export async function updateAnime(
  id: string,
  input: AnimeInput,
): Promise<Anime> {
  const response = await fetch(`/api/anime/update/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputToBody(input)),
  });
  const raw = await handle<BackendAnime>(response, `update anime ${id}`);
  return mapBackendAnime(raw);
}

export async function deleteAnime(id: string): Promise<void> {
  animeCache.remove(id);
  const response = await fetch(`/api/anime/delete/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to delete anime ${id}: ${response.status}`);
  }
}

export interface TrashedAnime {
  id: string;
  title: string;
  deleted_at: number;
}

export async function fetchAnimeTrash(): Promise<TrashedAnime[]> {
  const response = await fetch("/api/anime/trash", { credentials: "include" });
  if (!response.ok) {
    throw new Error(`Failed to fetch deleted anime: ${response.status}`);
  }
  return await response.json();
}

export async function restoreAnime(id: string): Promise<Anime> {
  const response = await fetch(`/api/anime/${id}/restore`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Failed to restore anime ${id}: ${response.status}`);
  }
  return mapBackendAnime(await response.json());
}

export async function purgeAnime(id: string): Promise<void> {
  const response = await fetch(`/api/anime/${id}/purge`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to purge anime ${id}: ${response.status}`);
  }
}

export async function createSeason(
  showId: string,
  input: SeasonInput,
): Promise<Anime> {
  const response = await fetch(`/api/anime/${showId}/seasons`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(seasonInputToBody(input)),
  });
  const raw = await handle<BackendAnime>(response, "create season");
  return mapBackendAnime(raw);
}

export interface SeasonUpdateInput {
  seasonNumber?: number;
  name?: string | null;
  episodeCount?: number | null;
  episodesWatched?: number;
  airDate?: string | null;
  posterUrl?: string | null;
  status?: AnimeStatus;
}

export async function updateSeason(
  showId: string,
  seasonId: string,
  input: SeasonUpdateInput,
): Promise<Anime> {
  const body: Record<string, unknown> = {};
  if ("seasonNumber" in input) body.season_number = input.seasonNumber;
  if ("name" in input) body.name = input.name;
  if ("episodeCount" in input) body.episode_count = input.episodeCount;
  if ("episodesWatched" in input) body.episodes_watched = input.episodesWatched;
  if ("airDate" in input) body.air_date = input.airDate;
  if ("posterUrl" in input) body.poster_url = input.posterUrl;
  if (input.status) body.status = denormalizeStatus(input.status);

  const response = await fetch(`/api/anime/${showId}/seasons/${seasonId}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const raw = await handle<BackendAnime>(response, "update season");
  return mapBackendAnime(raw);
}

// First call syncs the season's episodes in from Jikan if none exist yet
// (needs the show's externalId — set at creation from a Jikan search
// result); every later call just reads what's already stored.
export async function fetchEpisodes(
  showId: string,
  seasonId: string,
): Promise<Anime> {
  const response = await fetch(
    `/api/anime/${showId}/seasons/${seasonId}/episodes`,
    {
      credentials: "include",
    },
  );
  const raw = await handle<BackendAnime>(response, "fetch episodes");
  return mapBackendAnime(raw);
}

export interface EpisodeUpdateInput {
  watched?: boolean;
  rating?: number | null;
  note?: string | null;
}

export async function updateEpisode(
  showId: string,
  seasonId: string,
  episodeId: string,
  input: EpisodeUpdateInput,
): Promise<Anime> {
  const body: Record<string, unknown> = {};
  if ("watched" in input) body.watched = input.watched;
  if ("rating" in input) body.rating = input.rating;
  if ("note" in input) body.note = input.note;

  const response = await fetch(
    `/api/anime/${showId}/seasons/${seasonId}/episodes/${episodeId}`,
    {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  const raw = await handle<BackendAnime>(response, "update episode");
  return mapBackendAnime(raw);
}

// Sets `watched` on many episodes in one request — a shift-click range
// select or "mark watched up to here" would otherwise cost one PATCH per
// episode.
export async function bulkSetEpisodesWatched(
  showId: string,
  seasonId: string,
  episodeIds: string[],
  watched: boolean,
): Promise<Anime> {
  const response = await fetch(
    `/api/anime/${showId}/seasons/${seasonId}/episodes/bulk-watched`,
    {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_ids: episodeIds, watched }),
    },
  );
  const raw = await handle<BackendAnime>(response, "bulk-update episodes");
  return mapBackendAnime(raw);
}

export async function deleteSeason(
  showId: string,
  seasonId: string,
): Promise<Anime> {
  const response = await fetch(`/api/anime/${showId}/seasons/${seasonId}`, {
    method: "DELETE",
    credentials: "include",
  });
  const raw = await handle<BackendAnime>(response, "delete season");
  return mapBackendAnime(raw);
}

// A raw metadata search result, straight from whichever provider
// (AniList or MyAnimeList) found it — already snake_case-to-camelCase
// mapped here since these never round-trip back to the backend the way
// BackendAnime does. No `seasons` field: unlike TMDB for TV, neither
// AniList nor Jikan returns a season breakdown, so a new anime always
// gets the backend's auto-created default season instead.
export interface AnimeMetadataResult {
  provider: string;
  providerId: string;
  title: string;
  description: string | null;
  firstAirDate: string | null;
  episodeRuntimeMinutes: number | null;
  episodeCount: number | null;
  studios: string[];
  countries: string[];
  genres: string[];
  posterUrl: string | null;
  backdropUrl: string | null;
  format: string | null;
  anilistScore: number | null;
  malScore: number | null;
  // Jikan's own id, kept separate from providerId (which is whichever
  // provider matched first, usually AniList) — episode sync specifically
  // needs this one to call back into Jikan.
  malId: string | null;
  url: string | null;
}

export interface AnimeMetadataSearchResponse {
  query: string;
  providers: string[];
  providerErrors: string[];
  results: AnimeMetadataResult[];
}

interface BackendAnimeMetadataResult {
  provider: string;
  provider_id: string;
  title: string;
  description: string | null;
  first_air_date: string | null;
  episode_runtime_minutes: number | null;
  episode_count: number | null;
  studios: string[];
  countries: string[];
  genres: string[];
  poster_url: string | null;
  backdrop_url: string | null;
  format: string | null;
  anilist_score: number | string | null;
  mal_score: number | string | null;
  mal_id: string | null;
  url: string | null;
}

interface BackendAnimeMetadataSearchResponse {
  query: string;
  providers: string[];
  provider_errors: string[];
  results: BackendAnimeMetadataResult[];
}

function mapBackendAnimeMetadataResult(
  r: BackendAnimeMetadataResult,
): AnimeMetadataResult {
  return {
    provider: r.provider,
    providerId: r.provider_id,
    title: r.title,
    description: r.description,
    firstAirDate: r.first_air_date,
    episodeRuntimeMinutes: r.episode_runtime_minutes,
    episodeCount: r.episode_count,
    studios: r.studios,
    countries: r.countries,
    genres: r.genres,
    posterUrl: r.poster_url,
    backdropUrl: r.backdrop_url,
    format: r.format,
    anilistScore: toNumberOrNull(r.anilist_score),
    malScore: toNumberOrNull(r.mal_score),
    malId: r.mal_id,
    url: r.url,
  };
}

export async function searchAnimeMetadata(
  query: string,
  limit = 8,
): Promise<AnimeMetadataSearchResponse> {
  const params = new URLSearchParams({ query, limit: String(limit) });
  const response = await fetch(`/api/anime/metadata/search?${params}`, {
    credentials: "include",
  });
  const raw = await handle<BackendAnimeMetadataSearchResponse>(
    response,
    "search anime metadata",
  );
  return {
    query: raw.query,
    providers: raw.providers,
    providerErrors: raw.provider_errors,
    results: raw.results.map(mapBackendAnimeMetadataResult),
  };
}

// Looks up one exact AniList entry by id — used when adding a title from
// the Related/Recommended graph, which already carries a real AniList id
// (unlike a fresh text search, this can't miss or mismatch on an unusual
// title). Returns null if AniList has nothing for that id.
export async function fetchAnimeMetadataByAnilistId(
  anilistId: number,
): Promise<AnimeMetadataResult | null> {
  const response = await fetch(`/api/anime/metadata/by-id/${anilistId}`, {
    credentials: "include",
  });
  const raw = await handle<BackendAnimeMetadataResult | null>(
    response,
    "look up anime metadata by id",
  );
  return raw ? mapBackendAnimeMetadataResult(raw) : null;
}

// Related/Recommended titles — a plain item, not a full Anime: these
// exist only to render a graph node or a poster tile and link back to
// AniList, never round-tripped into this app's own data.
export interface RelatedAnime {
  id: number;
  title: string;
  format: string | null;
  posterUrl: string | null;
  episodeCount: number | null;
  year: number | null;
  relationLabel?: string;
}

// A season/entry in the full prequel-sequel chain this anime belongs
// to (not just its own direct neighbor) — `isCurrent` marks which one
// is the entry actually in the library.
export interface AnimeChainNode extends RelatedAnime {
  isCurrent: boolean;
}

// An off-chain relation (adaptation, side story, source manga/novel,
// etc.) attached to whichever chain entry it's actually connected to,
// via `anchorId` (that chain entry's AniList id).
export interface AnimeRelationBranch extends RelatedAnime {
  relationLabel: string;
  anchorId: number;
  // "show" (the default) anchors to a chain entry; "branch" anchors to
  // another branch's id instead — e.g. two compilation movies that are
  // themselves a sequel pair, not directly chained to the show.
  anchorKind: "show" | "branch";
  // the entry whose page is open — a movie/OVA opened from the library
  // is a branch of its franchise's root series, not a chain link
  isCurrent: boolean;
}

export interface AnimeRelationsResponse {
  chain: AnimeChainNode[];
  branches: AnimeRelationBranch[];
  configured: boolean;
}

interface BackendRelatedAnime {
  id: number;
  title: string;
  format: string | null;
  poster_url: string | null;
  episode_count: number | null;
  year: number | null;
  relation_label?: string;
}

interface BackendAnimeChainNode extends BackendRelatedAnime {
  is_current: boolean;
}

interface BackendAnimeRelationBranch extends BackendRelatedAnime {
  relation_label: string;
  anchor_id: number;
  anchor_kind: "show" | "branch";
  is_current?: boolean;
}

interface BackendAnimeRelationsResponse {
  chain: BackendAnimeChainNode[];
  branches: BackendAnimeRelationBranch[];
  configured: boolean;
}

function mapRelatedAnime(r: BackendRelatedAnime): RelatedAnime {
  return {
    id: r.id,
    title: r.title,
    format: r.format,
    posterUrl: r.poster_url,
    episodeCount: r.episode_count,
    year: r.year,
    relationLabel: r.relation_label,
  };
}

const relationsCache = new Map<string, AnimeRelationsResponse>();
export const peekAnimeRelations = (
  id: string,
): AnimeRelationsResponse | undefined => relationsCache.get(id);

export async function fetchAnimeRelations(
  id: string,
): Promise<AnimeRelationsResponse> {
  const response = await fetch(`/api/anime/${id}/relations`, {
    credentials: "include",
  });
  const raw = await handle<BackendAnimeRelationsResponse>(
    response,
    "fetch anime relations",
  );
  const result: AnimeRelationsResponse = {
    chain: raw.chain.map((n) => ({
      ...mapRelatedAnime(n),
      isCurrent: n.is_current,
    })),
    branches: raw.branches.map((b) => ({
      ...mapRelatedAnime(b),
      relationLabel: b.relation_label,
      anchorId: b.anchor_id,
      anchorKind: b.anchor_kind,
      isCurrent: b.is_current ?? false,
    })),
    configured: raw.configured,
  };
  relationsCache.set(id, result);
  return result;
}

export interface AnimeRecommendedResponse {
  recommended: RelatedAnime[];
  configured: boolean;
}

interface BackendAnimeRecommendedResponse {
  recommended: BackendRelatedAnime[];
  configured: boolean;
}

export async function fetchAnimeRecommended(
  id: string,
): Promise<AnimeRecommendedResponse> {
  const response = await fetch(`/api/anime/${id}/recommended`, {
    credentials: "include",
  });
  const raw = await handle<BackendAnimeRecommendedResponse>(
    response,
    "fetch anime recommended",
  );
  return {
    recommended: raw.recommended.map(mapRelatedAnime),
    configured: raw.configured,
  };
}

// Runs the airing check for just this title now (the background loop only
// comes around every 30 minutes) and returns the refreshed record.
export async function refreshAnimeAiring(id: string): Promise<Anime> {
  const response = await fetch(`/api/anime/${id}/refresh-airing`, {
    method: "POST",
    credentials: "include",
  });
  const raw = await handle<BackendAnime>(response, "refresh airing schedule");
  return mapBackendAnime(raw);
}

// Looks up the English, romaji and Japanese spelling of every anime that has
// none stored yet (AniList, in batches). Only blank title fields are set.
export interface FillTitlesResult {
  filled: number;
  without_id: number;
  lookup_failed: number;
  checked: number;
}
export async function fillAlternateTitles(): Promise<FillTitlesResult> {
  const response = await fetch("/api/anime/fill-titles", {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok)
    throw new Error(`Failed to look up titles: ${response.status}`);
  return await response.json();
}
