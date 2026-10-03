<script setup lang="ts">
import MyNote from "../components/MyNote.vue";
import { ref, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  getMovie,
  peekMovie,
  updateMovie,
  movieToInput,
  fetchMovieRelations,
  fetchMovieRecommended,
  fetchMovies,
  createMovie,
  searchMovieMetadata,
} from "../services/movies";
import type { RelatedMovie } from "../services/movies";
import type { Movie, MovieStatus } from "../types/movie";
import MovieFormModal from "../components/MovieFormModal.vue";
import RelationsGraph from "../components/RelationsGraph.vue";
import type { ChainNode, BranchNode } from "../components/RelationsGraph.vue";
import MediaPreviewModal from "../components/MediaPreviewModal.vue";
import MediaExtrasPanel from "../components/MediaExtrasPanel.vue";
import MediaProviderPanel from "../components/MediaProviderPanel.vue";
import MediaTopBar from "../components/MediaTopBar.vue";
import BackButton from "../components/BackButton.vue";
import RatingPicker from "../components/RatingPicker.vue";
import PluginExtensionSlot from "../components/plugins/PluginExtensionSlot.vue";
import PluginContextualActions from "../components/plugins/PluginContextualActions.vue";
import {
  STATUS_BUCKETS,
  statusBucket,
  bucketToReal,
} from "../utils/mediaStatus";

const route = useRoute();
const router = useRouter();
const movieId = computed(() => route.params.id as string);

const movie = ref<Movie | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const showEditModal = ref(false);
const activeTab = ref<"overview" | "related" | "recommended">("overview");
const descriptionExpanded = ref(false);
const statusBucketModel = computed({
  get: () => statusBucket(movie.value?.status ?? "wishlist"),
  set: (bucket: string) => {
    if (!movie.value) return;
    movie.value.status = bucketToReal(bucket) as MovieStatus;
  },
});

function goBack() {
  if (window.history.length > 1) {
    router.back();
  } else {
    router.push("/movies");
  }
}

async function load() {
  const cached = peekMovie(movieId.value);
  if (cached) {
    movie.value = cached;
    loading.value = false;
  } else {
    loading.value = true;
  }
  try {
    movie.value = await getMovie(movieId.value);
  } catch (e) {
    if (!cached)
      error.value = e instanceof Error ? e.message : "Failed to load movie.";
  } finally {
    loading.value = false;
  }
}

async function toggleFavorite() {
  if (!movie.value) return;
  const next = !movie.value.favorite;
  movie.value.favorite = next;
  try {
    await updateMovie(movie.value.id, {
      ...movieToInput(movie.value),
      favorite: next,
    });
  } catch {
    movie.value.favorite = !next;
  }
}

async function saveNote(note: string | null) {
  if (!movie.value) return;
  const previous = movie.value.note;
  movie.value.note = note;
  try {
    movie.value = await updateMovie(movie.value.id, {
      ...movieToInput(movie.value),
      note,
    });
  } catch {
    movie.value.note = previous;
  }
}

async function onStatusChange() {
  if (!movie.value) return;
  const previous = movie.value.status;
  try {
    movie.value = await updateMovie(movie.value.id, {
      ...movieToInput(movie.value),
      status: movie.value.status,
    });
  } catch {
    movie.value.status = previous;
  }
}

function onSaved(saved: Movie) {
  movie.value = saved;
  showEditModal.value = false;
}

function onDeleted() {
  router.push("/movies");
}

const releaseYear = computed(() =>
  movie.value?.releaseDate ? movie.value.releaseDate.slice(0, 4) : null,
);
const runtimeLabel = computed(() => {
  const minutes = movie.value?.runtimeMinutes;
  if (!minutes) return null;
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;
});
const nativeTitleLine = computed(() => {
  if (!movie.value) return "";
  const credit = movie.value.director || movie.value.studios[0];
  return credit ? `Movie · ${credit}` : "Movie";
});
const heroBackdropUrl = computed(
  () => movie.value?.backdropUrl ?? movie.value?.posterUrl ?? null,
);
const descriptionOverflows = computed(
  () => (movie.value?.description?.length ?? 0) > 320,
);

// ---- related (real TMDB collection data) ----
const relatedLoading = ref(false);
const relatedLoaded = ref(false);
const relatedError = ref<string | null>(null);
const relatedList = ref<RelatedMovie[]>([]);
const relatedCollectionName = ref<string | null>(null);
const relatedConfigured = ref(true);

async function loadRelated() {
  if (!movie.value || relatedLoaded.value) return;
  relatedLoading.value = true;
  relatedError.value = null;
  try {
    const res = await fetchMovieRelations(movie.value.id);
    relatedList.value = res.related;
    relatedCollectionName.value = res.collectionName;
    relatedConfigured.value = res.configured;
    relatedLoaded.value = true;
  } catch (e) {
    relatedError.value =
      e instanceof Error ? e.message : "Failed to load related movies.";
  } finally {
    relatedLoading.value = false;
  }
}

const relatedChainNodes = computed<ChainNode[]>(() =>
  movie.value
    ? [
        {
          id: "current",
          title: movie.value.title,
          type: "This movie",
          sub: "",
          current: true,
        },
      ]
    : [],
);
const relatedBranchNodes = computed<BranchNode[]>(() =>
  relatedList.value.map((r) => ({
    id: String(r.id),
    title: r.title,
    type: "Movie",
    sub: r.year ?? "",
    label: relatedCollectionName.value ?? "Related",
    anchorIndex: 0,
  })),
);
function onRelatedBranchClick() {
  // Related titles are TMDB entries, not necessarily in this library —
  // nothing to navigate to yet.
}

// ---- recommended (TMDB) ----
const recommendedLoading = ref(false);
const recommendedLoaded = ref(false);
const recommendedError = ref<string | null>(null);
const recommendedList = ref<RelatedMovie[]>([]);
const recommendedConfigured = ref(true);

async function loadRecommended() {
  if (!movie.value || recommendedLoaded.value) return;
  recommendedLoading.value = true;
  recommendedError.value = null;
  try {
    const res = await fetchMovieRecommended(movie.value.id);
    recommendedList.value = res.recommended;
    recommendedConfigured.value = res.configured;
    recommendedLoaded.value = true;
  } catch (e) {
    recommendedError.value =
      e instanceof Error ? e.message : "Failed to load recommendations.";
  } finally {
    recommendedLoading.value = false;
  }
}

// ---- click-through on a Related/Recommended title: go straight to it
// if it's already in the library, otherwise preview it with an Add
// button (reusing the same search-then-create flow the library page's
// quick-add uses) ----
const myMovies = ref<Movie[] | null>(null);
async function ensureMyMovies(): Promise<Movie[]> {
  if (!myMovies.value) myMovies.value = await fetchMovies();
  return myMovies.value;
}

const previewOpen = ref(false);
const previewLoading = ref(false);
const previewAdding = ref(false);
const previewError = ref<string | null>(null);
const previewTitle = ref("");
const previewPosterUrl = ref<string | null>(null);
const previewDescription = ref<string | null>(null);
const previewMeta = ref<string[]>([]);

function closePreview() {
  previewOpen.value = false;
}

async function onRelatedTitleClick(r: {
  title: string;
  posterUrl: string | null;
}) {
  const mine = await ensureMyMovies();
  const existing = mine.find(
    (m) => m.title.trim().toLowerCase() === r.title.trim().toLowerCase(),
  );
  if (existing) {
    router.push(`/movies/${existing.id}`);
    return;
  }
  previewOpen.value = true;
  previewLoading.value = true;
  previewError.value = null;
  previewTitle.value = r.title;
  previewPosterUrl.value = r.posterUrl;
  previewDescription.value = null;
  previewMeta.value = [];
  try {
    const { results } = await searchMovieMetadata(r.title, 1);
    const match = results.find((m) => m.title === r.title) ?? results[0];
    previewDescription.value = match?.description ?? null;
    previewMeta.value = [
      match?.releaseDate?.slice(0, 4),
      match?.director,
    ].filter((v): v is string => !!v);
  } catch (e) {
    previewError.value =
      e instanceof Error ? e.message : "Failed to load a preview.";
  } finally {
    previewLoading.value = false;
  }
}

async function addPreviewToLibrary() {
  previewAdding.value = true;
  previewError.value = null;
  try {
    const { results } = await searchMovieMetadata(previewTitle.value, 1);
    const match =
      results.find((m) => m.title === previewTitle.value) ?? results[0];
    const created = await createMovie({
      title: previewTitle.value,
      description: match?.description ?? null,
      releaseDate: match?.releaseDate ?? null,
      runtimeMinutes: match?.runtimeMinutes ?? null,
      director: match?.director ?? null,
      writer: match?.writer ?? null,
      studios: match?.studios ?? [],
      countries: match?.countries ?? [],
      genres: match?.genres ?? [],
      posterUrl: previewPosterUrl.value,
      backdropUrl: match?.backdropUrl ?? null,
      tmdbScore: match?.tmdbScore ?? null,
      status: "wishlist",
    });
    if (myMovies.value) myMovies.value.push(created);
    router.push(`/movies/${created.id}`);
  } catch (e) {
    previewError.value =
      e instanceof Error ? e.message : "Failed to add to library.";
  } finally {
    previewAdding.value = false;
  }
}

function setTab(tab: "overview" | "related" | "recommended") {
  activeTab.value = tab;
  if (tab === "related") loadRelated();
  if (tab === "recommended") loadRecommended();
}

// Vue Router reuses this component instance across /movies/:id → /movies/:id2
// navigations (same matched route), so onMounted alone would never refire —
// watch the param instead, resetting every tab's lazy-loaded state so a
// click-through from Related/Recommended actually shows the new title.
watch(
  movieId,
  () => {
    activeTab.value = "overview";
    relatedLoaded.value = false;
    recommendedLoaded.value = false;
    previewOpen.value = false;
    load();
  },
  { immediate: true },
);
async function onRatingChange(value: number | null) {
  if (!movie.value) return;
  const previous = movie.value.ratingOverall;
  movie.value.ratingOverall = value;
  try {
    movie.value = await updateMovie(movie.value.id, {
      ...movieToInput(movie.value),
      ratingOverall: value,
    });
  } catch {
    if (movie.value) movie.value.ratingOverall = previous;
  }
}
</script>

<template>
  <main v-if="loading" class="detail loading-state">
    <MediaTopBar active="movie" />
    <p class="loading-text">Loading…</p>
  </main>

  <main v-else-if="error" class="detail error-state">
    <MediaTopBar active="movie" />
    <p class="loading-text">{{ error }}</p>
  </main>

  <main v-else-if="movie" class="detail">
    <MediaTopBar active="movie" />
    <PluginExtensionSlot
      slot-id="media.detail.after-header"
      :context="{
        host_page: 'media.detail',
        media_id: movie.id,
        media_type: 'movie',
      }"
    />
    <PluginContextualActions
      :context="{
        kind: 'media',
        resource_id: String(movie.id),
        resource_type: 'movie',
      }"
    />

    <BackButton class="back-spot" @click="goBack" />

    <MovieFormModal
      v-if="showEditModal"
      :movie="movie"
      @saved="onSaved"
      @deleted="onDeleted"
      @closed="showEditModal = false"
    />

    <section class="hero" :class="{ 'no-poster': !heroBackdropUrl }">
      <div
        v-if="heroBackdropUrl"
        class="hero-backdrop"
        :class="{ 'is-poster': !movie.backdropUrl }"
        :style="{ backgroundImage: `url(${heroBackdropUrl})` }"
      ></div>
      <div class="hero-overlay"></div>
      <div class="hero-content">
        <div
          class="poster-card"
          :style="
            movie.posterUrl
              ? { backgroundImage: `url(${movie.posterUrl})` }
              : {}
          "
        >
          <span v-if="!movie.posterUrl">{{ movie.title }}</span>
        </div>
        <div class="hero-text">
          <div class="native-title">{{ nativeTitleLine }}</div>
          <h1 class="title">{{ movie.title }}</h1>
          <div class="badge-row">
            <select
              v-model="statusBucketModel"
              class="badge status status-select"
              title="Change status"
              @change="onStatusChange"
            >
              <option
                v-for="opt in STATUS_BUCKETS"
                :key="opt.key"
                :value="opt.key"
              >
                {{ opt.label }}
              </option>
            </select>
            <RatingPicker
              :model-value="movie.ratingOverall"
              @change="onRatingChange"
            />
            <span v-if="releaseYear" class="badge">{{ releaseYear }}</span>
            <span v-if="runtimeLabel" class="badge">{{ runtimeLabel }}</span>
          </div>
          <div class="action-row">
            <button
              class="edit-btn"
              type="button"
              @click="showEditModal = true"
            >
              ✎ Edit
            </button>
            <button
              class="icon-btn"
              :class="{ active: movie.favorite }"
              type="button"
              :title="
                movie.favorite ? 'Remove from favorites' : 'Add to favorites'
              "
              @click="toggleFavorite"
            >
              <svg
                viewBox="0 0 24 24"
                width="16"
                height="16"
                :fill="movie.favorite ? 'currentColor' : 'none'"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path
                  d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.6z"
                />
              </svg>
            </button>
            <MediaExtrasPanel media-type="movie" :media-id="movie.id" />
          </div>
        </div>
      </div>
    </section>

    <div class="tabbar-wrap">
      <div class="tabbar">
        <button
          type="button"
          class="tab-btn"
          :class="{ active: activeTab === 'overview' }"
          @click="setTab('overview')"
        >
          Overview
        </button>
        <button
          type="button"
          class="tab-btn"
          :class="{ active: activeTab === 'related' }"
          @click="setTab('related')"
        >
          Related
        </button>
        <button
          type="button"
          class="tab-btn"
          :class="{ active: activeTab === 'recommended' }"
          @click="setTab('recommended')"
        >
          Recommended
        </button>
      </div>
    </div>

    <div class="body">
      <div v-if="activeTab === 'overview'" class="tab-panel">
        <div class="meta-grid">
          <div v-if="movie.director" class="meta-item">
            <span class="meta-label">Director</span>
            <span class="meta-value">{{ movie.director }}</span>
          </div>
          <div v-if="movie.writer" class="meta-item">
            <span class="meta-label">Writer</span>
            <span class="meta-value">{{ movie.writer }}</span>
          </div>
          <div v-if="movie.studios.length" class="meta-item">
            <span class="meta-label">Studios</span>
            <span class="meta-value">{{ movie.studios.join(", ") }}</span>
          </div>
          <div v-if="movie.tmdbScore !== null" class="meta-item">
            <span class="meta-label">TMDB score</span>
            <span class="meta-value accent">{{
              movie.tmdbScore.toFixed(1)
            }}</span>
          </div>
          <div v-if="movie.ratingOverall !== null" class="meta-item">
            <span class="meta-label">Your score</span>
            <span class="meta-value accent">{{
              movie.ratingOverall.toFixed(1)
            }}</span>
          </div>
          <div v-if="movie.personalRank !== null" class="meta-item">
            <span class="meta-label">Personal rank</span>
            <span class="meta-value">#{{ movie.personalRank }}</span>
          </div>
          <div v-if="movie.rewatches > 0" class="meta-item">
            <span class="meta-label">Rewatches</span>
            <span class="meta-value">{{ movie.rewatches }}</span>
          </div>
        </div>

        <div v-if="movie.genres.length" class="chip-row">
          <span v-for="g in movie.genres" :key="g" class="chip primary">{{
            g
          }}</span>
        </div>
        <div v-if="movie.tags.length" class="chip-row">
          <span v-for="t in movie.tags" :key="t" class="chip">{{ t }}</span>
        </div>
        <div v-if="movie.description" class="description-block">
          <p
            class="description"
            :class="{ clamped: descriptionOverflows && !descriptionExpanded }"
          >
            {{ movie.description }}
          </p>
          <button
            v-if="descriptionOverflows"
            type="button"
            class="read-more-btn"
            @click="descriptionExpanded = !descriptionExpanded"
          >
            {{ descriptionExpanded ? "Show less" : "Read more" }}
          </button>
        </div>
        <MyNote :note="movie.note" @save="saveNote" />
        <MediaProviderPanel media-type="movie" :media-id="movie.id" />
      </div>

      <div v-else-if="activeTab === 'related'" class="tab-panel">
        <div class="section-heading">
          <h2>Related</h2>
        </div>
        <p v-if="relatedLoading" class="empty-state">Loading…</p>
        <p v-else-if="relatedError" class="empty-state error-text">
          {{ relatedError }}
        </p>
        <p v-else-if="!relatedConfigured" class="empty-state">
          TMDB isn't configured yet. A server admin can add an API key under
          Settings &gt; Metadata Sources to enable this.
        </p>
        <p v-else-if="!relatedList.length" class="empty-state">
          Not part of any known collection on TMDB.
        </p>
        <template v-else>
          <RelationsGraph
            :chain-nodes="relatedChainNodes"
            :branch-nodes="relatedBranchNodes"
            @branch-click="onRelatedBranchClick"
          />
          <div class="poster-grid">
            <div
              v-for="r in relatedList"
              :key="r.id"
              class="poster-card-sm"
              @click="onRelatedTitleClick(r)"
            >
              <div
                class="poster-card-sm-art"
                :style="
                  r.posterUrl ? { backgroundImage: `url(${r.posterUrl})` } : {}
                "
              ></div>
              <div class="poster-card-sm-title">{{ r.title }}</div>
              <div v-if="r.year" class="poster-card-sm-meta">{{ r.year }}</div>
            </div>
          </div>
        </template>
      </div>

      <div v-else class="tab-panel">
        <div class="section-heading">
          <h2>Recommended</h2>
        </div>
        <p v-if="recommendedLoading" class="empty-state">Loading…</p>
        <p v-else-if="recommendedError" class="empty-state error-text">
          {{ recommendedError }}
        </p>
        <p v-else-if="!recommendedConfigured" class="empty-state">
          TMDB isn't configured yet. A server admin can add an API key under
          Settings &gt; Metadata Sources to enable this.
        </p>
        <p v-else-if="!recommendedList.length" class="empty-state">
          No recommendations found.
        </p>
        <div v-else class="poster-grid">
          <div
            v-for="r in recommendedList"
            :key="r.id"
            class="poster-card-sm"
            @click="onRelatedTitleClick(r)"
          >
            <div
              class="poster-card-sm-art"
              :style="
                r.posterUrl ? { backgroundImage: `url(${r.posterUrl})` } : {}
              "
            ></div>
            <div class="poster-card-sm-title">{{ r.title }}</div>
            <div v-if="r.year" class="poster-card-sm-meta">{{ r.year }}</div>
          </div>
        </div>
      </div>
    </div>

    <MediaPreviewModal
      v-if="previewOpen"
      :title="previewTitle"
      :poster-url="previewPosterUrl"
      :description="previewDescription"
      :meta="previewMeta"
      :loading="previewLoading"
      :adding="previewAdding"
      :error="previewError"
      @add="addPreviewToLibrary"
      @close="closePreview"
    />
  </main>
</template>

<style scoped>
.detail {
  min-height: 100vh;
  background: #0d0d0d;
  color: #f2f2f2;
  font-family: system-ui, sans-serif;
  position: relative;
}
.loading-state,
.error-state {
  display: flex;
  flex-direction: column;
  color: #9c9c9c;
}
.loading-text {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
}
.hero {
  position: relative;
  background-size: cover;
  background-position: center 25%;
  background-color: #1a1a1a;
  min-height: 440px;
  display: flex;
  align-items: flex-end;
  overflow: hidden;
}
.hero.no-poster {
  background: linear-gradient(160deg, #241a10, #0d0d0d 70%);
}
.hero-backdrop {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center 20%;
  filter: brightness(0.55) saturate(1.15);
  z-index: 0;
}
.hero-backdrop.is-poster {
  inset: -30px;
  filter: blur(18px) brightness(0.55) saturate(1.15);
  transform: translateZ(0);
}
.hero-overlay {
  position: absolute;
  inset: 0;
  z-index: 1;
  background:
    linear-gradient(
      180deg,
      rgba(13, 13, 13, 0.25) 0%,
      rgba(13, 13, 13, 0.55) 45%,
      #0d0d0d 96%
    ),
    linear-gradient(
      90deg,
      rgba(13, 13, 13, 0.75) 0%,
      rgba(13, 13, 13, 0.15) 40%
    );
}
.hero-content {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 24px 28px;
  display: flex;
  align-items: flex-end;
  gap: 26px;
}
.poster-card {
  width: 190px;
  aspect-ratio: 2 / 3;
  flex-shrink: 0;
  border-radius: 8px;
  background-size: cover;
  background-position: center;
  background-color: #222222;
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 24px 48px -14px rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.78rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.3);
  text-align: center;
  padding: 10px;
}
.hero-text {
  min-width: 0;
  padding-bottom: 4px;
}
.native-title {
  font-size: 0.82rem;
  color: #666;
  margin-bottom: 4px;
  font-weight: 500;
}
.title {
  font-weight: 800;
  font-size: 2.5rem;
  line-height: 1.05;
  margin: 0 0 14px;
  letter-spacing: -0.01em;
  text-shadow: 0 4px 24px rgba(0, 0, 0, 0.5);
}
.badge-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.badge {
  line-height: 1.25;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 7px;
  padding: 4px 11px;
  font-size: 0.78rem;
  font-weight: 600;
  color: #9c9c9c;
  text-transform: capitalize;
}
.status-select {
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  border-color: rgba(214, 138, 52, 0.4);
  color: #d68a34;
  font-family: inherit;
  cursor: pointer;
  padding-right: 26px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23d68a34' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  background-size: 10px;
}
.action-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.edit-btn {
  background: #d68a34;
  border: none;
  color: #14100a;
  border-radius: 8px;
  padding: 0 20px;
  height: 38px;
  font-family: inherit;
  font-size: 0.86rem;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.icon-btn {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #f2f2f2;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}
.icon-btn:hover {
  border-color: rgba(214, 138, 52, 0.4);
}
.icon-btn.active {
  color: #d68a34;
  border-color: rgba(214, 138, 52, 0.4);
  background: rgba(214, 138, 52, 0.16);
}
.tabbar-wrap {
  max-width: 1180px;
  margin: 22px auto 0;
  padding: 0 24px;
}
.tabbar {
  display: flex;
  gap: 4px;
  background: #1a1a1a;
  border-radius: 10px;
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
  padding: 5px;
}
.tab-btn {
  flex-shrink: 0;
  white-space: nowrap;
  background: transparent;
  border: none;
  color: #9c9c9c;
  font-family: inherit;
  font-size: 0.84rem;
  font-weight: 600;
  padding: 8px 18px;
  border-radius: 7px;
  cursor: pointer;
}
.tab-btn.active {
  background: #d68a34;
  color: #14100a;
}
.body {
  position: relative;
  max-width: 1180px;
  margin: 0 auto;
  padding: 22px 24px 60px;
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 18px 24px;
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid #202020;
}
.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.meta-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #666;
  font-weight: 700;
}
.meta-value {
  font-size: 0.9rem;
  color: #f2f2f2;
  font-variant-numeric: tabular-nums;
}
.meta-value.accent {
  color: #d68a34;
  font-weight: 700;
}
.description-block {
  margin-top: 22px;
}
.description {
  font-size: 0.96rem;
  line-height: 1.7;
  color: #9c9c9c;
  margin: 0;
}
.description.clamped {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.read-more-btn {
  background: none;
  border: none;
  color: #d68a34;
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
  padding: 6px 0 0;
}
.read-more-btn:hover {
  text-decoration: underline;
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.chip {
  background: #222222;
  color: #9c9c9c;
  border: 1px solid #2b2b2b;
  border-radius: 999px;
  padding: 5px 13px;
  font-size: 0.78rem;
  font-weight: 600;
}
.chip.primary {
  background: rgba(214, 138, 52, 0.16);
  color: #d68a34;
  border-color: rgba(214, 138, 52, 0.4);
}
.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.section-heading h2 {
  font-weight: 800;
  font-size: 1.05rem;
  margin: 0;
}
.empty-state {
  color: #666;
  font-size: 0.85rem;
}
.error-text {
  color: #e57373;
}
.poster-grid {
  margin-top: 20px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 16px;
}
.poster-card-sm {
  cursor: pointer;
}
.poster-card-sm-art {
  aspect-ratio: 2 / 3;
  border-radius: 8px;
  background-size: cover;
  background-position: center;
  background-color: #222222;
  border: 1px solid #2b2b2b;
  transition: border-color 0.15s ease;
}
.poster-card-sm:hover .poster-card-sm-art {
  border-color: rgba(214, 138, 52, 0.5);
}
.poster-card-sm-title {
  margin-top: 6px;
  font-size: 0.8rem;
  font-weight: 700;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.poster-card-sm-meta {
  margin-top: 2px;
  font-size: 0.7rem;
  color: #666;
}
@media (max-width: 640px) {
  .hero-content {
    flex-direction: column;
    align-items: flex-start;
  }
}
/* Sits under the top bar and stays there while the page scrolls. It is sticky
   rather than absolute so it never slides over the bar, and the negative
   bottom margin gives back the room it takes so the hero does not move. */
.detail > .back-spot {
  display: flex;
  width: 38px;
  position: sticky;
  top: 76px;
  z-index: 79;
  margin: 16px 0 -54px var(--ui-edge-left);
}
</style>
