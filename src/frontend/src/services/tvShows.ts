import { failedRequest } from "./apiError";
import type { PaginatedResponse } from "../types/pagination";
import type { Episode, Season, TVShow, TVShowStatus } from "../types/tv_show";

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

export interface BackendTVShow {
  id: string;
  user_id: string;
  title: string;
  sort_title: string;
  description: string | null;
  first_air_date: string | null;
  episode_runtime_minutes: number | null;
  creators: string[];
  studios: string[];
  countries: string[];
  languages: string[];
  genres: string[];
  tags: string[];
  features: string[];
  age_rating: string | null;
  tmdb_score: number | string | null;
  source: string | null;
  external_id: string | null;
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

  is_airing: boolean | null;
  next_episode_air_at: number | null;
  next_episode_number: number | null;
  airing_interval_days: number | null;
}

import { createEntityCache } from "../utils/entityCache";
const tvShowCache = createEntityCache<TVShow>();
export const peekTVShow = tvShowCache.peek;
export const peekAllTVShows = (): TVShow[] | null =>
  tvShowCache.listLoaded() ? tvShowCache.all() : null;
// every entity that passes through here is remembered for instant reopening
function mapBackendTVShow(
  raw: Parameters<typeof mapBackendTVShowRaw>[0],
): TVShow {
  return tvShowCache.put(mapBackendTVShowRaw(raw));
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
function normalizeStatus(raw: string): TVShowStatus {
  return raw.toLowerCase().replace(/_/g, " ") as TVShowStatus;
}
// inverse of normalizeStatus, 'in progress' -> 'IN_PROGRESS'
function denormalizeStatus(status: TVShowStatus): string {
  return status.toUpperCase().replace(/ /g, "_");
}

function mapBackendEpisode(raw: BackendEpisode): Episode {
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

function mapBackendSeason(raw: BackendSeason): Season {
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

export function mapBackendTVShowRaw(raw: BackendTVShow): TVShow {
  return {
    id: raw.id,
    userId: raw.user_id,
    title: raw.title,
    sortTitle: raw.sort_title,
    description: raw.description,
    firstAirDate: raw.first_air_date,
    episodeRuntimeMinutes: raw.episode_runtime_minutes,
    creators: raw.creators,
    studios: raw.studios,
    countries: raw.countries,
    languages: raw.languages,
    genres: raw.genres,
    tags: raw.tags,
    features: raw.features,
    ageRating: raw.age_rating,
    tmdbScore: toNumberOrNull(raw.tmdb_score),
    source: raw.source,
    externalId: raw.external_id,
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
    isAiring: raw.is_airing,
    nextEpisodeAirAt: raw.next_episode_air_at,
    nextEpisodeNumber: raw.next_episode_number,
    airingIntervalDays: raw.airing_interval_days ?? null,
  };
}

async function handle<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    console.warn(`Failed to ${action}: ${response.status}`);
    throw await failedRequest(response);
  }
  return response.json();
}

export async function fetchTVShowsPage(
  offset = 0,
  limit = 100,
  search = "",
): Promise<{
  items: TVShow[];
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
  const response = await fetch(`/api/tv/list?${params}`, {
    credentials: "include",
  });
  const page = await handle<PaginatedResponse<BackendTVShow>>(
    response,
    "fetch TV shows",
  );
  return {
    items: page.items.map(mapBackendTVShow),
    total: page.total,
    offset: page.offset,
    limit: page.limit,
    statusCounts: page.status_counts,
  };
}

export async function fetchTVShows(search = ""): Promise<TVShow[]> {
  const all: TVShow[] = [];
  let offset = 0;
  const limit = 100;
  while (true) {
    const page = await fetchTVShowsPage(offset, limit, search);
    all.push(...page.items);
    if (all.length >= page.total || page.items.length === 0) break;
    offset += page.items.length;
  }
  tvShowCache.markListLoaded();
  return all;
}

export async function getTVShow(id: string): Promise<TVShow> {
  const response = await fetch(`/api/tv/get/${id}`, { credentials: "include" });
  const raw = await handle<BackendTVShow>(response, `fetch TV show ${id}`);
  return mapBackendTVShow(raw);
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

export interface TVShowInput {
  title: string;
  description?: string | null;
  firstAirDate?: string | null;
  episodeRuntimeMinutes?: number | null;
  creators?: string[];
  studios?: string[];
  countries?: string[];
  languages?: string[];
  genres?: string[];
  tags?: string[];
  features?: string[];
  ageRating?: string | null;
  tmdbScore?: number | null;
  source?: string | null;
  externalId?: string | null;
  posterUrl?: string | null;
  backdropUrl?: string | null;
  status?: TVShowStatus;
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
  seasons?: SeasonInput[];
}

// Round-trips a loaded TVShow back into TVShowInput shape — used when a
// caller needs to change one field (e.g. toggling favorite from the
// detail page) without reopening the full edit form, since updateTVShow
// always sends every field rather than a true partial patch.
export function tvShowToInput(show: TVShow): TVShowInput {
  return {
    title: show.title,
    description: show.description,
    firstAirDate: show.firstAirDate,
    episodeRuntimeMinutes: show.episodeRuntimeMinutes,
    creators: show.creators,
    studios: show.studios,
    countries: show.countries,
    languages: show.languages,
    genres: show.genres,
    tags: show.tags,
    features: show.features,
    ageRating: show.ageRating,
    tmdbScore: show.tmdbScore,
    source: show.source,
    externalId: show.externalId,
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
  };
}

function inputToBody(input: TVShowInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    title: input.title,
    description: input.description ?? null,
    first_air_date: input.firstAirDate ?? null,
    episode_runtime_minutes: input.episodeRuntimeMinutes ?? null,
    creators: input.creators ?? [],
    studios: input.studios ?? [],
    countries: input.countries ?? [],
    languages: input.languages ?? [],
    genres: input.genres ?? [],
    tags: input.tags ?? [],
    features: input.features ?? [],
    age_rating: input.ageRating ?? null,
    tmdb_score: input.tmdbScore ?? null,
    source: input.source ?? null,
    external_id: input.externalId ?? null,
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
  };
  if (input.airingIntervalDays !== undefined)
    body.airing_interval_days = input.airingIntervalDays;
  if (input.status) body.status = denormalizeStatus(input.status);
  if (input.seasons) body.seasons = input.seasons.map(seasonInputToBody);
  return body;
}

export async function createTVShow(input: TVShowInput): Promise<TVShow> {
  const response = await fetch("/api/tv/create", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputToBody(input)),
  });
  const raw = await handle<BackendTVShow>(response, "create TV show");
  return mapBackendTVShow(raw);
}

export async function updateTVShow(
  id: string,
  input: TVShowInput,
): Promise<TVShow> {
  const response = await fetch(`/api/tv/update/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputToBody(input)),
  });
  const raw = await handle<BackendTVShow>(response, `update TV show ${id}`);
  return mapBackendTVShow(raw);
}

export async function deleteTVShow(id: string): Promise<void> {
  tvShowCache.remove(id);
  const response = await fetch(`/api/tv/delete/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to delete TV show ${id}: ${response.status}`);
  }
}

export interface TrashedTVShow {
  id: string;
  title: string;
  deleted_at: number;
}

export async function fetchTVShowTrash(): Promise<TrashedTVShow[]> {
  const response = await fetch("/api/tv/trash", { credentials: "include" });
  if (!response.ok) {
    throw new Error(`Failed to fetch deleted shows: ${response.status}`);
  }
  return await response.json();
}

export async function restoreTVShow(id: string): Promise<TVShow> {
  const response = await fetch(`/api/tv/${id}/restore`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Failed to restore show ${id}: ${response.status}`);
  }
  return mapBackendTVShow(await response.json());
}

export async function purgeTVShow(id: string): Promise<void> {
  const response = await fetch(`/api/tv/${id}/purge`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to purge show ${id}: ${response.status}`);
  }
}

export async function createSeason(
  showId: string,
  input: SeasonInput,
): Promise<TVShow> {
  const response = await fetch(`/api/tv/${showId}/seasons`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(seasonInputToBody(input)),
  });
  const raw = await handle<BackendTVShow>(response, "create season");
  return mapBackendTVShow(raw);
}

export interface SeasonUpdateInput {
  seasonNumber?: number;
  name?: string | null;
  episodeCount?: number | null;
  episodesWatched?: number;
  airDate?: string | null;
  posterUrl?: string | null;
  status?: TVShowStatus;
}

export async function updateSeason(
  showId: string,
  seasonId: string,
  input: SeasonUpdateInput,
): Promise<TVShow> {
  const body: Record<string, unknown> = {};
  if ("seasonNumber" in input) body.season_number = input.seasonNumber;
  if ("name" in input) body.name = input.name;
  if ("episodeCount" in input) body.episode_count = input.episodeCount;
  if ("episodesWatched" in input) body.episodes_watched = input.episodesWatched;
  if ("airDate" in input) body.air_date = input.airDate;
  if ("posterUrl" in input) body.poster_url = input.posterUrl;
  if (input.status) body.status = denormalizeStatus(input.status);

  const response = await fetch(`/api/tv/${showId}/seasons/${seasonId}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const raw = await handle<BackendTVShow>(response, "update season");
  return mapBackendTVShow(raw);
}

// First call syncs the season's episodes in from TVmaze if none exist yet
// (needs the show's externalId — set at creation from a TVmaze search
// result); every later call just reads what's already stored.
export async function fetchEpisodes(
  showId: string,
  seasonId: string,
): Promise<TVShow> {
  const response = await fetch(
    `/api/tv/${showId}/seasons/${seasonId}/episodes`,
    {
      credentials: "include",
    },
  );
  const raw = await handle<BackendTVShow>(response, "fetch episodes");
  return mapBackendTVShow(raw);
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
): Promise<TVShow> {
  const body: Record<string, unknown> = {};
  if ("watched" in input) body.watched = input.watched;
  if ("rating" in input) body.rating = input.rating;
  if ("note" in input) body.note = input.note;

  const response = await fetch(
    `/api/tv/${showId}/seasons/${seasonId}/episodes/${episodeId}`,
    {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  const raw = await handle<BackendTVShow>(response, "update episode");
  return mapBackendTVShow(raw);
}

// Sets `watched` on many episodes in one request — a shift-click range
// select or "mark watched up to here" would otherwise cost one PATCH per
// episode.
export async function bulkSetEpisodesWatched(
  showId: string,
  seasonId: string,
  episodeIds: string[],
  watched: boolean,
): Promise<TVShow> {
  const response = await fetch(
    `/api/tv/${showId}/seasons/${seasonId}/episodes/bulk-watched`,
    {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_ids: episodeIds, watched }),
    },
  );
  const raw = await handle<BackendTVShow>(response, "bulk-update episodes");
  return mapBackendTVShow(raw);
}

export async function deleteSeason(
  showId: string,
  seasonId: string,
): Promise<TVShow> {
  const response = await fetch(`/api/tv/${showId}/seasons/${seasonId}`, {
    method: "DELETE",
    credentials: "include",
  });
  const raw = await handle<BackendTVShow>(response, "delete season");
  return mapBackendTVShow(raw);
}

// A raw metadata search result, straight from whichever provider (TMDB or
// OMDb) found it — already snake_case-to-camelCase mapped here since these
// never round-trip back to the backend the way BackendTVShow does.
export interface TVShowMetadataSeason {
  seasonNumber: number;
  name: string | null;
  episodeCount: number | null;
  airDate: string | null;
  posterUrl: string | null;
}

export interface TVShowMetadataResult {
  provider: string;
  providerId: string;
  title: string;
  description: string | null;
  firstAirDate: string | null;
  episodeRuntimeMinutes: number | null;
  creators: string[];
  studios: string[];
  countries: string[];
  languages: string[];
  genres: string[];
  posterUrl: string | null;
  backdropUrl: string | null;
  tmdbScore: number | null;
  seasons: TVShowMetadataSeason[];
  url: string | null;
  // TVmaze's own id, kept separate from providerId (whichever provider
  // matched first) since episode sync/airing checks need TVmaze's id
  // specifically, regardless of which provider ended up owning the result
  tvmazeId: string | null;
}

export interface TVShowMetadataSearchResponse {
  query: string;
  providers: string[];
  providerErrors: string[];
  results: TVShowMetadataResult[];
}

interface BackendTVShowMetadataSeason {
  season_number: number;
  name: string | null;
  episode_count: number | null;
  air_date: string | null;
  poster_url: string | null;
}

interface BackendTVShowMetadataResult {
  provider: string;
  provider_id: string;
  title: string;
  description: string | null;
  first_air_date: string | null;
  episode_runtime_minutes: number | null;
  creators: string[];
  studios: string[];
  countries: string[];
  languages: string[];
  genres: string[];
  poster_url: string | null;
  backdrop_url: string | null;
  tmdb_score: number | string | null;
  seasons: BackendTVShowMetadataSeason[];
  url: string | null;
  tvmaze_id: string | null;
}

interface BackendTVShowMetadataSearchResponse {
  query: string;
  providers: string[];
  provider_errors: string[];
  results: BackendTVShowMetadataResult[];
}

export async function searchTVShowMetadata(
  query: string,
  limit = 8,
): Promise<TVShowMetadataSearchResponse> {
  const params = new URLSearchParams({ query, limit: String(limit) });
  const response = await fetch(`/api/tv/metadata/search?${params}`, {
    credentials: "include",
  });
  const raw = await handle<BackendTVShowMetadataSearchResponse>(
    response,
    "search TV show metadata",
  );
  return {
    query: raw.query,
    providers: raw.providers,
    providerErrors: raw.provider_errors,
    results: raw.results.map((r) => ({
      provider: r.provider,
      providerId: r.provider_id,
      title: r.title,
      description: r.description,
      firstAirDate: r.first_air_date,
      episodeRuntimeMinutes: r.episode_runtime_minutes,
      creators: r.creators,
      studios: r.studios,
      countries: r.countries,
      languages: r.languages,
      genres: r.genres,
      posterUrl: r.poster_url,
      backdropUrl: r.backdrop_url,
      tmdbScore: toNumberOrNull(r.tmdb_score),
      seasons: r.seasons.map((s) => ({
        seasonNumber: s.season_number,
        name: s.name,
        episodeCount: s.episode_count,
        airDate: s.air_date,
        posterUrl: s.poster_url,
      })),
      url: r.url,
      tvmazeId: r.tvmaze_id,
    })),
  };
}

// Related/Recommended titles — a plain item, not a full TVShow: these
// exist only to render a graph node or a poster tile and link back to
// their source provider, never round-tripped into this app's own data.
export interface RelatedShow {
  id: number;
  title: string;
  year: string | null;
  posterUrl: string | null;
}

export interface TVShowRelationsResponse {
  listName: string | null;
  related: RelatedShow[];
  configured: boolean;
}

interface BackendRelatedShow {
  id: number;
  title: string;
  year: string | null;
  poster_url: string | null;
}

interface BackendTVShowRelationsResponse {
  listName: string | null;
  related: BackendRelatedShow[];
  configured: boolean;
}

function mapRelatedShow(r: BackendRelatedShow): RelatedShow {
  return { id: r.id, title: r.title, year: r.year, posterUrl: r.poster_url };
}

// TheTVDB is the only real franchise source for TV — `configured: false`
// means no TVDB key is set yet, distinct from a real empty result (the
// show simply isn't part of a franchise).
export async function fetchTVShowRelations(
  id: string,
): Promise<TVShowRelationsResponse> {
  const response = await fetch(`/api/tv/${id}/relations`, {
    credentials: "include",
  });
  const raw = await handle<BackendTVShowRelationsResponse>(
    response,
    "fetch show relations",
  );
  return {
    listName: raw.listName,
    related: raw.related.map(mapRelatedShow),
    configured: raw.configured,
  };
}

export interface TVShowRecommendedResponse {
  recommended: RelatedShow[];
  configured: boolean;
}

interface BackendTVShowRecommendedResponse {
  recommended: BackendRelatedShow[];
  configured: boolean;
}

export async function fetchTVShowRecommended(
  id: string,
): Promise<TVShowRecommendedResponse> {
  const response = await fetch(`/api/tv/${id}/recommended`, {
    credentials: "include",
  });
  const raw = await handle<BackendTVShowRecommendedResponse>(
    response,
    "fetch show recommended",
  );
  return {
    recommended: raw.recommended.map(mapRelatedShow),
    configured: raw.configured,
  };
}

// Runs the airing check for just this title now (the background loop only
// comes around every 30 minutes) and returns the refreshed record.
export async function refreshTVShowAiring(id: string): Promise<TVShow> {
  const response = await fetch(`/api/tv/${id}/refresh-airing`, {
    method: "POST",
    credentials: "include",
  });
  const raw = await handle<BackendTVShow>(response, "refresh airing schedule");
  return mapBackendTVShow(raw);
}
