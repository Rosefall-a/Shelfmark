<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useKeptAlive } from "../utils/useKeptAlive";
import {
  fetchAnimePage,
  updateAnime,
  deleteAnime,
  animeToInput,
  searchAnimeMetadata,
  createAnime,
  updateSeason,
} from "../services/anime";
import type { SeasonUpdateInput } from "../services/anime";
import type { Anime, AnimeStatus } from "../types/anime";
import MediaLibraryView from "../components/library/MediaLibraryView.vue";
import { displayTitle } from "../utils/displayTitle";
import { statusBucket, bucketToReal } from "../utils/mediaStatus";
import type {
  LibraryCardVM,
  SearchResultVM,
  QuickAddForm,
  EditForm,
} from "../components/library/MediaLibraryView.vue";

const shows = ref<Anime[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const showAniListImport = ref(false);
const aniListUsername = ref("");
const aniListUpdateExisting = ref(false);
const aniListImporting = ref(false);
const aniListImportError = ref<string | null>(null);
const aniListImportResult = ref<{
  fetched: number;
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
} | null>(null);

async function importFromAniList() {
  if (!aniListUsername.value.trim()) return;
  aniListImporting.value = true;
  aniListImportError.value = null;
  aniListImportResult.value = null;
  try {
    const response = await fetch("/api/anime/import/anilist", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: aniListUsername.value.trim(),
        update_existing: aniListUpdateExisting.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? "AniList import failed.");
    aniListImportResult.value = data;
    await load();
  } catch (e) {
    aniListImportError.value =
      e instanceof Error ? e.message : "AniList import failed.";
  } finally {
    aniListImporting.value = false;
  }
}

function seasonProgress(show: Anime): {
  watched: number;
  total: number | null;
} {
  const watched = show.seasons.reduce((sum, s) => sum + s.episodesWatched, 0);
  const known = show.seasons.every((s) => s.episodeCount !== null);
  const total = known
    ? show.seasons.reduce((sum, s) => sum + (s.episodeCount ?? 0), 0)
    : null;
  return { watched, total };
}
// The season currently being watched: the first one not yet fully watched.
function currentSeason(show: Anime) {
  return show.seasons.find(
    (s) => s.episodeCount === null || s.episodesWatched < s.episodeCount,
  );
}

function toVM(show: Anime): LibraryCardVM {
  const { watched, total } = seasonProgress(show);
  return {
    id: show.id,
    title: displayTitle(show),
    poster: show.posterUrl,
    status: show.status,
    favorite: show.favorite,
    score: show.ratingOverall,
    personalRank: show.personalRank,
    note: show.note,
    genres: show.genres,
    isEpisodic: true,
    watched,
    total,
    progressLabel: total !== null ? `${watched}/${total}` : `${watched}/–`,
    canAdvance: !!currentSeason(show),
    format: show.format,
    releaseYear: show.firstAirDate ? show.firstAirDate.slice(0, 4) : null,
    addedAt: Date.parse(show.createdAt) || null,
    altTitles: [
      show.title,
      show.titleEnglish,
      show.titleRomaji,
      show.titleNative,
    ].filter((t): t is string => !!t),
  };
}

const items = computed(() => shows.value.map(toVM));

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
  if (!shows.value.length) loading.value = true;
  try {
    const page = await fetchAnimePage(0, pageSize, search);
    if (request !== loadRequest) return;
    shows.value = page.items;
    total.value = page.total;
    statusCounts.value = page.statusCounts;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load anime.";
  } finally {
    loading.value = false;
  }
}
async function loadMore() {
  if (loading.value || shows.value.length >= total.value) return;
  loading.value = true;
  try {
    const page = await fetchAnimePage(
      shows.value.length,
      pageSize,
      currentSearch.value,
    );
    shows.value.push(...page.items);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load more anime.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
useKeptAlive(load);

function findShow(id: string): Anime {
  const show = shows.value.find((s) => s.id === id);
  if (!show) throw new Error(`Anime ${id} not in the loaded list`);
  return show;
}
function replaceShow(updated: Anime) {
  const idx = shows.value.findIndex((s) => s.id === updated.id);
  if (idx !== -1) shows.value[idx] = updated;
}

async function onToggleFavorite(id: string) {
  const show = findShow(id);
  const next = !show.favorite;
  show.favorite = next;
  try {
    replaceShow(
      await updateAnime(id, { ...animeToInput(show), favorite: next }),
    );
  } catch {
    show.favorite = !next;
  }
}

async function onSaveNote(id: string, note: string | null) {
  const show = findShow(id);
  replaceShow(await updateAnime(id, { ...animeToInput(show), note }));
}

// No cap on episodes watched — metadata's episode count is often wrong
// or stale, and a rewatch can genuinely outrun it too.
async function onAdvanceEpisode(id: string) {
  const show = findShow(id);
  const season = currentSeason(show);
  if (!season) return;
  const updated = await updateSeason(id, season.id, {
    episodesWatched: season.episodesWatched + 1,
  });
  replaceShow(updated);
  // pressing + on a show that is still Plan to Watch or On Hold means it has
  // been started (or picked up again), so it moves to Watching
  const bucket = statusBucket(updated.status);
  if (bucket === "plan" || bucket === "hold") {
    replaceShow(
      await updateAnime(id, {
        ...animeToInput(updated),
        status: bucketToReal("watching") as AnimeStatus,
      }),
    );
  }
}

async function onSaveEdit(id: string, form: EditForm) {
  const show = findShow(id);
  replaceShow(
    await updateAnime(id, {
      ...animeToInput(show),
      status: form.status as AnimeStatus,
      ratingOverall: form.score,
    }),
  );
  // The small edit modal's "episodes watched" and "total episodes" are
  // flat numbers; apply them to the current season the same way the
  // quick "+" button does, rather than pretending a show-level episode
  // count exists as its own field. Falls back to the last season once
  // everything is already watched (currentSeason has nothing left to
  // pick) so the fields stay editable after a show is fully caught up.
  const updatedShow = findShow(id);
  const season =
    currentSeason(updatedShow) ??
    updatedShow.seasons[updatedShow.seasons.length - 1];
  if (season) {
    const watchedDelta = form.watched - seasonProgress(updatedShow).watched;
    const totalChanged = form.totalEpisodes !== season.episodeCount;
    const seasonUpdates: SeasonUpdateInput = {};
    if (watchedDelta !== 0) {
      seasonUpdates.episodesWatched = Math.max(
        0,
        season.episodesWatched + watchedDelta,
      );
    }
    if (totalChanged) {
      seasonUpdates.episodeCount = form.totalEpisodes;
    }
    if (Object.keys(seasonUpdates).length > 0) {
      replaceShow(await updateSeason(id, season.id, seasonUpdates));
    }
  }
}

async function onBulkSetStatus(ids: string[], status: string) {
  for (const id of ids) {
    const show = findShow(id);
    replaceShow(
      await updateAnime(id, {
        ...animeToInput(show),
        status: status as AnimeStatus,
      }),
    );
  }
}
async function onBulkFavorite(ids: string[]) {
  for (const id of ids) {
    const show = findShow(id);
    replaceShow(
      await updateAnime(id, { ...animeToInput(show), favorite: true }),
    );
  }
}
async function onBulkDelete(ids: string[]) {
  for (const id of ids) {
    await deleteAnime(id);
  }
  shows.value = shows.value.filter((s) => !ids.includes(s.id));
}

async function search(
  query: string,
): Promise<{ results: SearchResultVM[]; providerErrors: string[] }> {
  const { results, providerErrors } = await searchAnimeMetadata(query);
  return {
    results: results.map((r) => ({
      title: r.title,
      poster: r.posterUrl,
      description: r.description,
      episodeTotal: r.episodeCount,
      releaseYear: r.firstAirDate ? r.firstAirDate.slice(0, 4) : null,
    })),
    providerErrors,
  };
}

async function createFromResult(
  result: SearchResultVM,
  form: QuickAddForm,
): Promise<void> {
  const { results } = await searchAnimeMetadata(result.title, 1);
  const match = results.find((r) => r.title === result.title) ?? results[0];
  // Pass the episode count through explicitly instead of leaving seasons
  // omitted (which auto-creates a default Season 1 with no count) — the
  // metadata search already knows the total, so there's no reason the
  // progress bar and "watched/total" label should come up unknown.
  const episodeCount = match?.episodeCount ?? result.episodeTotal ?? null;
  const created = await createAnime({
    title: result.title,
    description: match?.description ?? null,
    firstAirDate: match?.firstAirDate ?? null,
    episodeRuntimeMinutes: match?.episodeRuntimeMinutes ?? null,
    studios: match?.studios ?? [],
    genres: match?.genres ?? [],
    posterUrl: result.poster,
    backdropUrl: match?.backdropUrl ?? null,
    format: match?.format ?? null,
    anilistScore: match?.anilistScore ?? null,
    malScore: match?.malScore ?? null,
    externalId: match?.malId ?? null,
    // AniList is the primary provider, so provider_id is its id whenever
    // AniList matched (the common case) — kept separately from
    // externalId (MAL's) so episode sync has a fallback when Jikan is
    // unreachable or never matched this title.
    anilistId: match?.provider === "AniList" ? match.providerId : null,
    status: form.status as AnimeStatus,
    ratingOverall: form.score,
    startDate: form.startDate,
    endDate: form.endDate,
    seasons: [{ seasonNumber: 1, episodeCount }],
  });
  let finalShow = created;
  const firstSeason = created.seasons[0];
  if (firstSeason && form.watched > 0) {
    finalShow = await updateSeason(created.id, firstSeason.id, {
      episodesWatched: form.watched,
    });
  }
  shows.value.push(finalShow);
}

function detailRoute(id: string): string {
  return `/anime/${id}`;
}
</script>

<template>
  <MediaLibraryView
    kind="anime"
    add-label="+ Add Anime"
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
    @advance-episode="onAdvanceEpisode"
    @save-note="onSaveNote"
    @save-edit="onSaveEdit"
    @bulk-set-status="onBulkSetStatus"
    @bulk-favorite="onBulkFavorite"
    @bulk-delete="onBulkDelete"
  >
    <template #actions>
      <button
        type="button"
        class="anilist-import-btn"
        @click="showAniListImport = true"
      >
        Import AniList
      </button>
    </template>
  </MediaLibraryView>

  <div
    v-if="showAniListImport"
    class="import-backdrop"
    @click.self="showAniListImport = false"
  >
    <div class="import-modal">
      <h2>Import from AniList</h2>
      <p>
        Enter your public AniList username. This imports your anime list into
        this library and never changes AniList.
      </p>
      <input
        v-model="aniListUsername"
        class="import-input"
        placeholder="AniList username"
        @keyup.enter="importFromAniList"
      />
      <label class="import-check">
        <input v-model="aniListUpdateExisting" type="checkbox" />
        Update existing titles
      </label>
      <p v-if="aniListImportError" class="import-error">
        {{ aniListImportError }}
      </p>
      <p v-if="aniListImportResult" class="import-result">
        Fetched {{ aniListImportResult.fetched }} · Created
        {{ aniListImportResult.created }} · Updated
        {{ aniListImportResult.updated }} · Skipped
        {{ aniListImportResult.skipped }}
      </p>
      <ul v-if="aniListImportResult?.errors.length" class="import-errors">
        <li v-for="item in aniListImportResult.errors" :key="item">
          {{ item }}
        </li>
      </ul>
      <div class="import-actions">
        <button type="button" @click="showAniListImport = false">Close</button>
        <button
          type="button"
          :disabled="aniListImporting || !aniListUsername.trim()"
          @click="importFromAniList"
        >
          {{ aniListImporting ? "Importing…" : "Import" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.anilist-import-btn {
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.06);
  color: #ddd;
  border-radius: 8px;
  padding: 9px 13px;
  cursor: pointer;
}
.import-backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.7);
}
.import-modal {
  width: min(520px, calc(100vw - 32px));
  background: #191919;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.import-modal h2 {
  margin: 0;
}
.import-modal p {
  color: #aaa;
  margin: 0;
}
.import-input {
  width: 100%;
  box-sizing: border-box;
  padding: 10px;
  border-radius: 7px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: #111;
  color: #fff;
}
.import-check {
  display: flex;
  gap: 8px;
  align-items: center;
  color: #ddd;
}
.import-error {
  color: #e57373 !important;
}
.import-result {
  color: #8bc98f !important;
}
.import-errors {
  max-height: 120px;
  overflow: auto;
  color: #e57373;
  margin: 0;
}
.import-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.import-actions button {
  padding: 8px 14px;
  border-radius: 7px;
  cursor: pointer;
}
</style>
