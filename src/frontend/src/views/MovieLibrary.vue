<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useKeptAlive } from "../utils/useKeptAlive";
import {
  fetchMoviesPage,
  updateMovie,
  deleteMovie,
  movieToInput,
  searchMovieMetadata,
  createMovie,
} from "../services/movies";
import type { Movie, MovieStatus } from "../types/movie";
import MediaLibraryView from "../components/library/MediaLibraryView.vue";
import type {
  LibraryCardVM,
  SearchResultVM,
  QuickAddForm,
  EditForm,
} from "../components/library/MediaLibraryView.vue";

const movies = ref<Movie[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const COMPLETED_STATUSES: MovieStatus[] = ["watched", "favorite", "rewatch"];

function formatRuntime(minutes: number | null): string {
  if (!minutes) return "–";
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;
}

function toVM(m: Movie): LibraryCardVM {
  const seen = COMPLETED_STATUSES.includes(m.status);
  return {
    id: m.id,
    title: m.title,
    poster: m.posterUrl,
    status: m.status,
    favorite: m.favorite,
    score: m.ratingOverall,
    personalRank: m.personalRank,
    note: m.note,
    genres: m.genres,
    isEpisodic: false,
    watched: seen ? 1 : 0,
    total: 1,
    progressLabel: formatRuntime(m.runtimeMinutes),
    canAdvance: false,
    releaseYear: m.releaseDate ? m.releaseDate.slice(0, 4) : null,
    addedAt: Date.parse(m.createdAt) || null,
  };
}

const items = computed(() => movies.value.map(toVM));

// Only the very first load shows the loading state; a refresh when the
// page comes back swaps data in quietly, so titles never blink away.
let loadRequest = 0;
const total = ref(0);
const statusCounts = ref<Record<string, number>>({});
const pageSize = 100;
const currentSearch = ref("");
async function load(search = "") {
  currentSearch.value = search;
  const request = ++loadRequest;
  if (!movies.value.length) loading.value = true;
  try {
    const page = await fetchMoviesPage(0, pageSize, search);
    if (request !== loadRequest) return;
    movies.value = page.items;
    total.value = page.total;
    statusCounts.value = page.statusCounts;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load movies.";
  } finally {
    loading.value = false;
  }
}
async function loadMore() {
  if (loading.value || movies.value.length >= total.value) return;
  loading.value = true;
  try {
    const page = await fetchMoviesPage(
      movies.value.length,
      pageSize,
      currentSearch.value,
    );
    movies.value.push(...page.items);
  } catch (e) {
    error.value =
      e instanceof Error ? e.message : "Failed to load more movies.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
useKeptAlive(load);

function findMovie(id: string): Movie {
  const movie = movies.value.find((m) => m.id === id);
  if (!movie) throw new Error(`Movie ${id} not in the loaded list`);
  return movie;
}
function replaceMovie(updated: Movie) {
  const idx = movies.value.findIndex((m) => m.id === updated.id);
  if (idx !== -1) movies.value[idx] = updated;
}

async function onToggleFavorite(id: string) {
  const movie = findMovie(id);
  const next = !movie.favorite;
  movie.favorite = next;
  try {
    replaceMovie(
      await updateMovie(id, { ...movieToInput(movie), favorite: next }),
    );
  } catch {
    movie.favorite = !next;
  }
}

async function onSaveNote(id: string, note: string | null) {
  const movie = findMovie(id);
  replaceMovie(await updateMovie(id, { ...movieToInput(movie), note }));
}

async function onSaveEdit(id: string, form: EditForm) {
  const movie = findMovie(id);
  replaceMovie(
    await updateMovie(id, {
      ...movieToInput(movie),
      status: form.status as MovieStatus,
      ratingOverall: form.score,
    }),
  );
}

async function onBulkSetStatus(ids: string[], status: string) {
  for (const id of ids) {
    const movie = findMovie(id);
    replaceMovie(
      await updateMovie(id, {
        ...movieToInput(movie),
        status: status as MovieStatus,
      }),
    );
  }
}
async function onBulkFavorite(ids: string[]) {
  for (const id of ids) {
    const movie = findMovie(id);
    replaceMovie(
      await updateMovie(id, { ...movieToInput(movie), favorite: true }),
    );
  }
}
async function onBulkDelete(ids: string[]) {
  for (const id of ids) {
    await deleteMovie(id);
  }
  movies.value = movies.value.filter((m) => !ids.includes(m.id));
}

async function search(
  query: string,
): Promise<{ results: SearchResultVM[]; providerErrors: string[] }> {
  const { results, providerErrors } = await searchMovieMetadata(query);
  return {
    results: results.map((r) => ({
      title: r.title,
      poster: r.posterUrl,
      description: r.description,
      episodeTotal: null,
      releaseYear: r.releaseDate ? r.releaseDate.slice(0, 4) : null,
    })),
    providerErrors,
  };
}

async function createFromResult(
  result: SearchResultVM,
  form: QuickAddForm,
): Promise<void> {
  // Re-run the search to recover the full metadata result behind this
  // title (the normalized SearchResultVM only carries what the shared
  // library view needs to render — the rest of the real fields still
  // come straight from the same provider search).
  const { results } = await searchMovieMetadata(result.title, 1);
  const match = results.find((r) => r.title === result.title) ?? results[0];
  const created = await createMovie({
    title: result.title,
    description: match?.description ?? null,
    releaseDate: match?.releaseDate ?? null,
    director: match?.director ?? null,
    writer: match?.writer ?? null,
    studios: match?.studios ?? [],
    countries: match?.countries ?? [],
    genres: match?.genres ?? [],
    posterUrl: result.poster,
    backdropUrl: match?.backdropUrl ?? null,
    tmdbScore: match?.tmdbScore ?? null,
    status: form.status as MovieStatus,
    ratingOverall: form.score,
    startDate: form.startDate,
    endDate: form.endDate,
  });
  movies.value.push(created);
}

function detailRoute(id: string): string {
  return `/movies/${id}`;
}
</script>

<template>
  <MediaLibraryView
    kind="movie"
    add-label="+ Add Movie"
    :items="items"
    :total="total"
    :status-counts="statusCounts"
    :loading="loading"
    :error="error"
    :detail-route="detailRoute"
    :search="search"
    :create-from-result="createFromResult"
    @search="load"
    @load-more="loadMore"
    @toggle-favorite="onToggleFavorite"
    @save-note="onSaveNote"
    @save-edit="onSaveEdit"
    @bulk-set-status="onBulkSetStatus"
    @bulk-favorite="onBulkFavorite"
    @bulk-delete="onBulkDelete"
  />
</template>
