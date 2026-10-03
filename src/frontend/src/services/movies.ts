import { failedRequest } from "./apiError";
import type { PaginatedResponse } from "../types/pagination";
import type { Movie, MovieStatus } from "../types/movie";

// The exact shape FastAPI sends, snake_case, matching the Python model
// field-for-field. Nothing outside this file should ever see raw backend
// data directly.
export interface BackendMovie {
  id: string;
  user_id: string;
  title: string;
  sort_title: string;
  description: string | null;
  release_date: string | null;
  runtime_minutes: number | null;
  director: string | null;
  writer: string | null;
  studios: string[];
  countries: string[];
  languages: string[];
  genres: string[];
  tags: string[];
  features: string[];
  age_rating: string | null;
  tmdb_score: number | string | null;
  source: string | null;
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
  // unix timestamps in seconds, not ISO strings
  created_at: number;
  updated_at: number;
}

import { createEntityCache } from "../utils/entityCache";
const movieCache = createEntityCache<Movie>();
export const peekMovie = movieCache.peek;
export const peekAllMovies = (): Movie[] | null =>
  movieCache.listLoaded() ? movieCache.all() : null;
// every entity that passes through here is remembered for instant reopening
function mapBackendMovie(raw: Parameters<typeof mapBackendMovieRaw>[0]): Movie {
  return movieCache.put(mapBackendMovieRaw(raw));
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
function normalizeStatus(raw: string): MovieStatus {
  return raw.toLowerCase().replace(/_/g, " ") as MovieStatus;
}
// inverse of normalizeStatus, 'in progress' -> 'IN_PROGRESS'
function denormalizeStatus(status: MovieStatus): string {
  return status.toUpperCase().replace(/ /g, "_");
}

export function mapBackendMovieRaw(raw: BackendMovie): Movie {
  return {
    id: raw.id,
    userId: raw.user_id,
    title: raw.title,
    sortTitle: raw.sort_title,
    description: raw.description,
    releaseDate: raw.release_date,
    runtimeMinutes: raw.runtime_minutes,
    director: raw.director,
    writer: raw.writer,
    studios: raw.studios,
    countries: raw.countries,
    languages: raw.languages,
    genres: raw.genres,
    tags: raw.tags,
    features: raw.features,
    ageRating: raw.age_rating,
    tmdbScore: toNumberOrNull(raw.tmdb_score),
    source: raw.source,
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
    createdAt: unixSecondsToIso(raw.created_at),
    updatedAt: unixSecondsToIso(raw.updated_at),
  };
}

async function handle<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    console.warn(`Failed to ${action}: ${response.status}`);
    throw await failedRequest(response);
  }
  return response.json();
}

export async function fetchMoviesPage(
  offset = 0,
  limit = 100,
  search = "",
): Promise<{
  items: Movie[];
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
  const response = await fetch(`/api/movie/list?${params}`, {
    credentials: "include",
  });
  const page = await handle<PaginatedResponse<BackendMovie>>(
    response,
    "fetch movies",
  );
  return {
    items: page.items.map(mapBackendMovie),
    total: page.total,
    offset: page.offset,
    limit: page.limit,
    statusCounts: page.status_counts,
  };
}

export async function fetchMovies(search = ""): Promise<Movie[]> {
  const all: Movie[] = [];
  let offset = 0;
  const limit = 100;
  while (true) {
    const page = await fetchMoviesPage(offset, limit, search);
    all.push(...page.items);
    if (all.length >= page.total || page.items.length === 0) break;
    offset += page.items.length;
  }
  movieCache.markListLoaded();
  return all;
}

export async function getMovie(id: string): Promise<Movie> {
  const response = await fetch(`/api/movie/get/${id}`, {
    credentials: "include",
  });
  const raw = await handle<BackendMovie>(response, `fetch movie ${id}`);
  return mapBackendMovie(raw);
}

// Round-trips a loaded Movie back into MovieInput shape — used when a
// caller needs to change one field (e.g. toggling favorite from the
// detail page) without reopening the full edit form, since updateMovie
// always sends every field rather than a true partial patch.
export function movieToInput(movie: Movie): MovieInput {
  return {
    title: movie.title,
    description: movie.description,
    releaseDate: movie.releaseDate,
    runtimeMinutes: movie.runtimeMinutes,
    director: movie.director,
    writer: movie.writer,
    studios: movie.studios,
    countries: movie.countries,
    languages: movie.languages,
    genres: movie.genres,
    tags: movie.tags,
    features: movie.features,
    ageRating: movie.ageRating,
    tmdbScore: movie.tmdbScore,
    source: movie.source,
    posterUrl: movie.posterUrl,
    backdropUrl: movie.backdropUrl,
    status: movie.status,
    priority: movie.priority,
    favorite: movie.favorite,
    rewatches: movie.rewatches,
    note: movie.note,
    startDate: movie.startDate,
    endDate: movie.endDate,
    ratingStory: movie.ratingStory,
    ratingPerformance: movie.ratingPerformance,
    ratingSoundtrack: movie.ratingSoundtrack,
    ratingOverall: movie.ratingOverall,
    personalRank: movie.personalRank,
  };
}

export interface MovieInput {
  title: string;
  description?: string | null;
  releaseDate?: string | null;
  runtimeMinutes?: number | null;
  director?: string | null;
  writer?: string | null;
  studios?: string[];
  countries?: string[];
  languages?: string[];
  genres?: string[];
  tags?: string[];
  features?: string[];
  ageRating?: string | null;
  tmdbScore?: number | null;
  source?: string | null;
  posterUrl?: string | null;
  backdropUrl?: string | null;
  status?: MovieStatus;
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
}

function inputToBody(input: MovieInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    title: input.title,
    description: input.description ?? null,
    release_date: input.releaseDate ?? null,
    runtime_minutes: input.runtimeMinutes ?? null,
    director: input.director ?? null,
    writer: input.writer ?? null,
    studios: input.studios ?? [],
    countries: input.countries ?? [],
    languages: input.languages ?? [],
    genres: input.genres ?? [],
    tags: input.tags ?? [],
    features: input.features ?? [],
    age_rating: input.ageRating ?? null,
    tmdb_score: input.tmdbScore ?? null,
    source: input.source ?? null,
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
  if (input.status) body.status = denormalizeStatus(input.status);
  return body;
}

export async function createMovie(input: MovieInput): Promise<Movie> {
  const response = await fetch("/api/movie/create", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputToBody(input)),
  });
  const raw = await handle<BackendMovie>(response, "create movie");
  return mapBackendMovie(raw);
}

export async function updateMovie(
  id: string,
  input: MovieInput,
): Promise<Movie> {
  const response = await fetch(`/api/movie/update/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputToBody(input)),
  });
  const raw = await handle<BackendMovie>(response, `update movie ${id}`);
  return mapBackendMovie(raw);
}

export async function deleteMovie(id: string): Promise<void> {
  movieCache.remove(id);
  const response = await fetch(`/api/movie/delete/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to delete movie ${id}: ${response.status}`);
  }
}

export interface TrashedMovie {
  id: string;
  title: string;
  deleted_at: number;
}

export async function fetchMovieTrash(): Promise<TrashedMovie[]> {
  const response = await fetch("/api/movie/trash", { credentials: "include" });
  if (!response.ok) {
    throw new Error(`Failed to fetch deleted movies: ${response.status}`);
  }
  return await response.json();
}

export async function restoreMovie(id: string): Promise<Movie> {
  const response = await fetch(`/api/movie/${id}/restore`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Failed to restore movie ${id}: ${response.status}`);
  }
  return mapBackendMovie(await response.json());
}

export async function purgeMovie(id: string): Promise<void> {
  const response = await fetch(`/api/movie/${id}/purge`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to purge movie ${id}: ${response.status}`);
  }
}

// A raw metadata search result, straight from whichever provider (TMDB or
// OMDb) found it — already snake_case-to-camelCase mapped here since these
// never round-trip back to the backend the way BackendMovie does.
export interface MovieMetadataResult {
  provider: string;
  providerId: string;
  title: string;
  description: string | null;
  releaseDate: string | null;
  runtimeMinutes: number | null;
  director: string | null;
  writer: string | null;
  studios: string[];
  countries: string[];
  languages: string[];
  genres: string[];
  posterUrl: string | null;
  backdropUrl: string | null;
  tmdbScore: number | null;
  url: string | null;
}

export interface MovieMetadataSearchResponse {
  query: string;
  providers: string[];
  providerErrors: string[];
  results: MovieMetadataResult[];
}

interface BackendMovieMetadataResult {
  provider: string;
  provider_id: string;
  title: string;
  description: string | null;
  release_date: string | null;
  runtime_minutes: number | null;
  director: string | null;
  writer: string | null;
  studios: string[];
  countries: string[];
  languages: string[];
  genres: string[];
  poster_url: string | null;
  backdrop_url: string | null;
  tmdb_score: number | string | null;
  url: string | null;
}

interface BackendMovieMetadataSearchResponse {
  query: string;
  providers: string[];
  provider_errors: string[];
  results: BackendMovieMetadataResult[];
}

export async function searchMovieMetadata(
  query: string,
  limit = 8,
): Promise<MovieMetadataSearchResponse> {
  const params = new URLSearchParams({ query, limit: String(limit) });
  const response = await fetch(`/api/movie/metadata/search?${params}`, {
    credentials: "include",
  });
  const raw = await handle<BackendMovieMetadataSearchResponse>(
    response,
    "search movie metadata",
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
      releaseDate: r.release_date,
      runtimeMinutes: r.runtime_minutes,
      director: r.director,
      writer: r.writer,
      studios: r.studios,
      countries: r.countries,
      languages: r.languages,
      genres: r.genres,
      posterUrl: r.poster_url,
      backdropUrl: r.backdrop_url,
      tmdbScore: toNumberOrNull(r.tmdb_score),
      url: r.url,
    })),
  };
}

// Related/Recommended titles — a plain item, not a full Movie: these
// exist only to render a graph node or a poster tile and link back to
// TMDB, never round-tripped into this app's own data.
export interface RelatedMovie {
  id: number;
  title: string;
  year: string | null;
  posterUrl: string | null;
}

export interface MovieRelationsResponse {
  collectionName: string | null;
  related: RelatedMovie[];
  configured: boolean;
}

interface BackendRelatedMovie {
  id: number;
  title: string;
  year: string | null;
  poster_url: string | null;
}

interface BackendMovieRelationsResponse {
  collection_name: string | null;
  related: BackendRelatedMovie[];
  configured: boolean;
}

function mapRelatedMovie(r: BackendRelatedMovie): RelatedMovie {
  return { id: r.id, title: r.title, year: r.year, posterUrl: r.poster_url };
}

export async function fetchMovieRelations(
  id: string,
): Promise<MovieRelationsResponse> {
  const response = await fetch(`/api/movie/${id}/relations`, {
    credentials: "include",
  });
  const raw = await handle<BackendMovieRelationsResponse>(
    response,
    "fetch movie relations",
  );
  return {
    collectionName: raw.collection_name,
    related: raw.related.map(mapRelatedMovie),
    configured: raw.configured,
  };
}

export interface MovieRecommendedResponse {
  recommended: RelatedMovie[];
  configured: boolean;
}

interface BackendMovieRecommendedResponse {
  recommended: BackendRelatedMovie[];
  configured: boolean;
}

export async function fetchMovieRecommended(
  id: string,
): Promise<MovieRecommendedResponse> {
  const response = await fetch(`/api/movie/${id}/recommended`, {
    credentials: "include",
  });
  const raw = await handle<BackendMovieRecommendedResponse>(
    response,
    "fetch movie recommended",
  );
  return {
    recommended: raw.recommended.map(mapRelatedMovie),
    configured: raw.configured,
  };
}
