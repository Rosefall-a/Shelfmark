<script setup lang="ts">
import { ref, computed, watch } from "vue";
import {
  createAnime,
  updateAnime,
  deleteAnime,
  searchAnimeMetadata,
  animeToInput,
} from "../services/anime";
import type { AnimeMetadataResult } from "../services/anime";
import type { Anime, AnimeStatus } from "../types/anime";
import {
  STATUS_BUCKETS,
  statusBucket,
  bucketToReal,
} from "../utils/mediaStatus";
import { lockedFieldLabels } from "../utils/lockedFields";

const props = defineProps<{
  show?: Anime | null;
}>();

const emit = defineEmits<{
  saved: [show: Anime];
  deleted: [showId: string];
  closed: [];
}>();

function blankFields() {
  return {
    title: "",
    description: "",
    firstAirDate: "",
    episodeRuntimeMinutes: null as number | null,
    studiosInput: "",
    genresInput: "",
    tagsInput: "",
    status: "wishlist" as AnimeStatus,
    favorite: false,
    ratingOverall: null as number | null,
    personalRank: null as number | null,
    posterUrl: null as string | null,
    backdropUrl: null as string | null,
    anilistScore: null as number | null,
    malScore: null as number | null,
    externalId: null as string | null,
    anilistId: null as string | null,
  };
}

const fields = ref(blankFields());
const statusBucketModel = computed({
  get: () => statusBucket(fields.value.status),
  set: (bucket: string) => {
    fields.value.status = bucketToReal(bucket) as AnimeStatus;
  },
});
const saving = ref(false);
const deleting = ref(false);
const error = ref<string | null>(null);

const metadataQuery = ref("");
const metadataResults = ref<AnimeMetadataResult[]>([]);
const searchingMetadata = ref(false);
const metadataMessage = ref<string | null>(null);
const providerWarnings = ref<string[]>([]);

function loadFromShow(show: Anime | null | undefined) {
  if (!show) {
    fields.value = blankFields();
    return;
  }
  fields.value = {
    title: show.title,
    description: show.description ?? "",
    firstAirDate: show.firstAirDate ?? "",
    episodeRuntimeMinutes: show.episodeRuntimeMinutes,
    studiosInput: show.studios.join(", "),
    genresInput: show.genres.join(", "),
    tagsInput: show.tags.join(", "),
    status: show.status,
    favorite: show.favorite,
    ratingOverall: show.ratingOverall,
    personalRank: show.personalRank,
    posterUrl: show.posterUrl,
    backdropUrl: show.backdropUrl,
    anilistScore: show.anilistScore,
    malScore: show.malScore,
    externalId: show.externalId,
    anilistId: show.anilistId,
  };
}

watch(() => props.show, loadFromShow, { immediate: true });

function splitList(input: string): string[] {
  return input
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

async function searchMetadata() {
  if (metadataQuery.value.trim().length < 2) {
    metadataMessage.value = "Enter at least two characters to search.";
    return;
  }
  searchingMetadata.value = true;
  metadataMessage.value = null;
  providerWarnings.value = [];
  try {
    const response = await searchAnimeMetadata(metadataQuery.value.trim());
    metadataResults.value = response.results;
    providerWarnings.value = response.providerErrors;
    if (!metadataResults.value.length) {
      metadataMessage.value = "No anime found.";
    }
  } catch (e) {
    metadataMessage.value =
      e instanceof Error ? e.message : "Metadata search failed.";
  } finally {
    searchingMetadata.value = false;
  }
}

function applyMetadata(result: AnimeMetadataResult) {
  const locked = new Set(props.show?.lockedFields ?? []);
  if (!locked.has("title")) fields.value.title = result.title;
  if (!locked.has("description"))
    fields.value.description = result.description ?? "";
  if (!locked.has("first_air_date"))
    fields.value.firstAirDate = result.firstAirDate ?? "";
  if (
    !locked.has("episode_runtime_minutes") &&
    result.episodeRuntimeMinutes !== null
  )
    fields.value.episodeRuntimeMinutes = result.episodeRuntimeMinutes;
  if (!locked.has("studios") && result.studios.length)
    fields.value.studiosInput = result.studios.join(", ");
  if (!locked.has("genres") && result.genres.length)
    fields.value.genresInput = result.genres.join(", ");
  if (!locked.has("poster_url")) fields.value.posterUrl = result.posterUrl;
  if (!locked.has("backdrop_url"))
    fields.value.backdropUrl = result.backdropUrl;
  if (!locked.has("anilist_score") && result.anilistScore !== null)
    fields.value.anilistScore = result.anilistScore;
  if (!locked.has("mal_score") && result.malScore !== null)
    fields.value.malScore = result.malScore;
  // Not gated by locked_fields — these aren't a user-editable display
  // field, just the link episode sync/airing checks need. Picking a
  // search result is exactly how a show with a missing/wrong link (e.g.
  // added by hand, or from before this app tracked these ids) gets
  // fixed, so always take the freshly-picked match's ids.
  fields.value.externalId = result.malId;
  fields.value.anilistId =
    result.provider === "AniList" ? result.providerId : null;
  metadataResults.value = [];
  metadataQuery.value = result.title;
  metadataMessage.value = locked.size
    ? `Prefilled from ${result.provider}. Skipped ${locked.size} field(s) you've already edited: ${lockedFieldLabels([...locked]).join(", ")}. Review the fields before saving.`
    : `Prefilled from ${result.provider}. Review the fields before saving.`;
}

async function submit() {
  if (!fields.value.title.trim()) {
    error.value = "Title is required.";
    return;
  }
  saving.value = true;
  error.value = null;
  try {
    const input = {
      title: fields.value.title.trim(),
      description: fields.value.description.trim() || null,
      firstAirDate: fields.value.firstAirDate || null,
      episodeRuntimeMinutes: fields.value.episodeRuntimeMinutes,
      studios: splitList(fields.value.studiosInput),
      genres: splitList(fields.value.genresInput),
      tags: splitList(fields.value.tagsInput),
      status: fields.value.status,
      favorite: fields.value.favorite,
      ratingOverall: fields.value.ratingOverall,
      personalRank: fields.value.personalRank,
      posterUrl: fields.value.posterUrl,
      backdropUrl: fields.value.backdropUrl,
      anilistScore: fields.value.anilistScore,
      malScore: fields.value.malScore,
      externalId: fields.value.externalId,
      anilistId: fields.value.anilistId,
    };
    const saved = props.show
      ? await updateAnime(props.show.id, {
          // keep the fields this form doesn't show
          ...animeToInput(props.show),
          ...input,
        })
      : await createAnime(input);
    emit("saved", saved);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to save anime.";
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!props.show) return;
  deleting.value = true;
  error.value = null;
  try {
    await deleteAnime(props.show.id);
    emit("deleted", props.show.id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to delete anime.";
  } finally {
    deleting.value = false;
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('closed')">
    <div class="modal" role="dialog" aria-label="Anime">
      <div class="modal-head">
        <h2>{{ show ? "Edit Anime" : "Add Anime" }}</h2>
        <button type="button" class="close-btn" @click="emit('closed')">
          &times;
        </button>
      </div>

      <div class="modal-body">
        <p v-if="error" class="error-text">{{ error }}</p>

        <div class="field">
          <span>Search AniList / MyAnimeList</span>
          <div class="search-row">
            <input
              v-model="metadataQuery"
              type="search"
              class="text-input"
              placeholder="Search by anime title"
              aria-label="Search by anime title"
              @keyup.enter="searchMetadata"
            />
            <button
              type="button"
              class="secondary-button"
              :disabled="searchingMetadata"
              @click="searchMetadata"
            >
              {{ searchingMetadata ? "Searching…" : "Search" }}
            </button>
          </div>
          <div v-if="metadataResults.length" class="metadata-results">
            <button
              v-for="result in metadataResults"
              :key="`${result.provider}-${result.providerId}`"
              type="button"
              class="metadata-result"
              @click="applyMetadata(result)"
            >
              <span>{{ result.title }}</span>
              <small
                >{{ result.provider
                }}<span v-if="result.firstAirDate">
                  · {{ result.firstAirDate.slice(0, 4) }}</span
                ><span v-if="result.episodeCount">
                  · {{ result.episodeCount }} ep</span
                ></small
              >
            </button>
          </div>
          <p v-if="metadataMessage" class="hint">{{ metadataMessage }}</p>
          <ul v-if="providerWarnings.length" class="provider-warnings">
            <li v-for="warning in providerWarnings" :key="warning">
              {{ warning }}
            </li>
          </ul>
        </div>

        <img
          v-if="fields.posterUrl"
          :src="fields.posterUrl"
          alt=""
          class="poster-preview"
        />

        <label class="field">
          <span>Title</span>
          <input
            v-model="fields.title"
            type="text"
            class="text-input"
            placeholder="Fullmetal Alchemist: Brotherhood"
          />
        </label>

        <label class="field">
          <span>Description</span>
          <textarea
            v-model="fields.description"
            class="text-input textarea-input"
            rows="3"
          ></textarea>
        </label>

        <div class="field-row">
          <label class="field">
            <span>First air date</span>
            <input
              v-model="fields.firstAirDate"
              type="date"
              class="text-input"
            />
          </label>
          <label class="field">
            <span>Episode runtime (minutes)</span>
            <input
              v-model.number="fields.episodeRuntimeMinutes"
              type="number"
              min="0"
              class="text-input"
            />
          </label>
        </div>

        <label class="field">
          <span>Studios (comma-separated)</span>
          <input v-model="fields.studiosInput" type="text" class="text-input" />
        </label>

        <label class="field">
          <span>Genres (comma-separated)</span>
          <input v-model="fields.genresInput" type="text" class="text-input" />
        </label>

        <label class="field">
          <span>Tags (comma-separated)</span>
          <input v-model="fields.tagsInput" type="text" class="text-input" />
        </label>

        <div class="field-row">
          <label class="field">
            <span>Status</span>
            <select v-model="statusBucketModel" class="text-input">
              <option v-for="s in STATUS_BUCKETS" :key="s.key" :value="s.key">
                {{ s.label }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>Overall rating (0-10)</span>
            <input
              v-model.number="fields.ratingOverall"
              type="number"
              min="0"
              max="10"
              step="0.1"
              class="text-input"
            />
          </label>
        </div>

        <div class="field-row">
          <label class="field checkbox-field">
            <input v-model="fields.favorite" type="checkbox" />
            <span>Favorite</span>
          </label>
          <label class="field">
            <span>Personal rank</span>
            <input
              v-model.number="fields.personalRank"
              type="number"
              min="1"
              class="text-input"
            />
          </label>
        </div>

        <div class="field-row">
          <label class="field">
            <span>AniList score (0-10)</span>
            <input
              v-model.number="fields.anilistScore"
              type="number"
              min="0"
              max="10"
              step="0.1"
              class="text-input"
            />
          </label>
          <label class="field">
            <span>MAL score (0-10)</span>
            <input
              v-model.number="fields.malScore"
              type="number"
              min="0"
              max="10"
              step="0.1"
              class="text-input"
            />
          </label>
        </div>
      </div>

      <div class="modal-foot">
        <button
          v-if="show"
          type="button"
          class="delete-btn"
          :disabled="deleting || saving"
          @click="remove"
        >
          {{ deleting ? "Deleting…" : "Delete" }}
        </button>
        <div class="modal-foot-spacer"></div>
        <button type="button" class="secondary-button" @click="emit('closed')">
          Cancel
        </button>
        <button
          type="button"
          class="primary-btn"
          :disabled="saving || deleting"
          @click="submit"
        >
          {{ saving ? "Saving…" : show ? "Save Changes" : "Add Anime" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--ui-z-modal);
  background: rgba(8, 6, 4, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.modal {
  width: 100%;
  max-width: 480px;
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 30px 70px -20px rgba(0, 0, 0, 0.8);
  color: #fff;
  font-family: system-ui, sans-serif;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  border-bottom: 1px solid #2a2a2a;
}
.modal-head h2 {
  margin: 0;
  font-size: 1.05rem;
}
.close-btn {
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  width: 32px;
  height: 32px;
  margin: -3px -7px -3px 0;
  border-radius: 50%;
  font-size: 1.2rem;
  line-height: 1;
}
.close-btn:hover {
  color: #d68a34;
}
.modal-body {
  padding: 18px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.error-text {
  color: #fca5a5;
  font-size: 0.85rem;
  margin: 0;
}
.search-row {
  display: flex;
  gap: 8px;
}
.search-row input {
  flex: 1;
  min-width: 0;
}
.metadata-results {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}
.metadata-result {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 9px 10px;
  text-align: left;
  color: #fff;
  background: #202020;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
}
.metadata-result:hover {
  border-color: #d68a34;
  background: #282828;
}
.metadata-result small {
  color: #999;
  font-size: 0.78rem;
}
.provider-warnings {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.provider-warnings li {
  color: #fca27a;
  font-size: 0.75rem;
}
.poster-preview {
  width: 100%;
  max-height: 220px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid #2a2a2a;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  flex: 1;
  min-width: 0;
}
.field span {
  font-size: 0.78rem;
  color: #999;
}
.field-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.field-row > .field {
  flex: 1 1 120px;
}
.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.checkbox-field span {
  font-size: 0.85rem;
  color: #fff;
}
.text-input {
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  color: #fff;
  padding: 8px 10px;
  font-size: 0.85rem;
  font-family: inherit;
  width: 100%;
  box-sizing: border-box;
}
.text-input:focus {
  outline: 2px solid #d68a34;
  outline-offset: 1px;
}
.textarea-input {
  resize: vertical;
  min-height: 60px;
}
.hint {
  font-size: 0.78rem;
  color: #999;
  margin: 0;
}
.modal-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  border-top: 1px solid #2a2a2a;
}
.modal-foot-spacer {
  flex: 1;
}
.primary-btn {
  background: #d68a34;
  color: #121212;
  border: none;
  border-radius: 8px;
  padding: 9px 18px;
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
}
.primary-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
.secondary-button {
  background: #111;
  border: 1px solid #2a2a2a;
  color: #ccc;
  border-radius: 8px;
  padding: 9px 14px;
  font-size: 0.85rem;
  cursor: pointer;
}
.delete-btn {
  background: none;
  border: 1px solid #5c2a2a;
  color: #fca5a5;
  border-radius: 8px;
  padding: 9px 14px;
  font-size: 0.85rem;
  cursor: pointer;
}
.delete-btn:hover {
  background: #2a1414;
}
.delete-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
