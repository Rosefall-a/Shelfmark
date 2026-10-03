<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import {
  attachGameAssetFromUrl,
  createGame,
  fetchGames,
  searchGameMetadata,
  updateGame,
  uploadGameAsset,
} from "../services/games";
import type { MetadataSearchResult } from "../services/games";
import type {
  Game,
  GameStatus,
  AchievementsProvider,
  GameRelationshipType,
} from "../types/game";
import type { GameLink, GameOwnership } from "../types/game";
import { currentUser } from "../state/auth";

const props = defineProps<{
  game?: Game | null;
}>();

// for the "parent game" picker, fetched here rather than threaded as a
// prop through every place this modal is opened from (GameLibrary,
// GameDetail, CollectionDetail, HomeHub), so it works consistently
// regardless of caller
const availableParentGames = ref<Game[]>([]);
onMounted(async () => {
  try {
    availableParentGames.value = (await fetchGames()).filter(
      (g) => g.id !== props.game?.id,
    );
  } catch {
    // parent picker just stays empty, not worth failing the whole form
  }
});

const emit = defineEmits<{
  close: [];
  saved: [gameId: string];
  delete: [gameId: string];
}>();

const isEditing = computed(() => !!props.game);

const statuses: GameStatus[] = [
  "playing",
  "beaten",
  "mastered",
  "played",
  "on hold",
  "dropped",
  "backlog",
  "wishlist",
];

const tabs = [
  "General",
  "Ratings & Tags",
  "Media",
  "Links",
  "Ownership",
] as const;
const activeTab = ref<(typeof tabs)[number]>("General");

const title = ref(props.game?.title ?? "");
const sortTitle = ref("");
const folderLocation = ref(props.game?.folderLocation ?? "");
const status = ref<GameStatus>(props.game?.status ?? "backlog");
const developer = ref(props.game?.developer ?? "");
const publisher = ref(props.game?.publisher ?? "");
const series = ref(props.game?.series ?? "");
const parentGameId = ref(props.game?.parentGameId ?? "");
const relationshipType = ref<GameRelationshipType | "">(
  props.game?.relationshipType ?? "",
);
const RELATIONSHIP_TYPE_OPTIONS: {
  value: GameRelationshipType;
  label: string;
}[] = [
  { value: "mod", label: "Mod" },
  { value: "modpack", label: "Modpack" },
  { value: "expansion", label: "Expansion" },
  { value: "dlc", label: "DLC" },
  { value: "standalone_expansion", label: "Standalone expansion" },
  { value: "total_conversion", label: "Total conversion" },
];
const source = ref(props.game?.source ?? "");
const ageRating = ref(props.game?.ageRating ?? "");
const timeToBeatHours = ref(
  props.game?.timeToBeatHours != null ? String(props.game.timeToBeatHours) : "",
);
const region = ref(props.game?.region ?? "");
const language = ref(props.game?.language ?? "");
const achievementsProvider = ref<AchievementsProvider>(
  props.game?.achievementsProvider ?? null,
);
const releaseDate = ref(props.game?.releaseDate ?? "");
const dateAdded = ref(
  props.game?.dateAdded ?? new Date().toISOString().slice(0, 10),
);
const description = ref(props.game?.description ?? "");
const profilesEnabled = ref(props.game?.profilesEnabled ?? false);
const osrsStatsEnabled = ref(props.game?.osrsStatsEnabled ?? false);
watch(profilesEnabled, (enabled) => {
  if (!enabled) osrsStatsEnabled.value = false;
});

const ratingOverall = ref<number | null>(props.game?.ratingOverall ?? null);
const ratingStory = ref<number | null>(props.game?.ratingStory ?? null);
const ratingGameplay = ref<number | null>(props.game?.ratingGameplay ?? null);
const ratingSound = ref<number | null>(props.game?.ratingSound ?? null);
const tagsInput = ref(props.game?.tags.join(", ") ?? "");
const featuresInput = ref(props.game?.features.join(", ") ?? "");

const coverFile = ref<File | null>(null);
const bannerFile = ref<File | null>(null);

const links = ref<GameLink[]>(props.game?.links ? [...props.game.links] : []);
function addLink() {
  links.value.push({ label: "", url: "" });
}
function removeLink(index: number) {
  links.value.splice(index, 1);
}

const ownershipFormat = ref<GameOwnership["format"]>(
  props.game?.ownership.format ?? null,
);
const purchaseDate = ref(props.game?.ownership.purchaseDate ?? "");
const completionDate = ref(props.game?.completionDate ?? "");
const price = ref<number | null>(props.game?.ownership.price ?? null);
const priceCurrency = ref(props.game?.ownership.priceCurrency ?? "USD");
const condition = ref(props.game?.ownership.condition ?? "");

const saving = ref(false);
const error = ref<string | null>(null);
const metadataQuery = ref("");
const metadataResults = ref<MetadataSearchResult[]>([]);
const searchingMetadata = ref(false);
const metadataMessage = ref<string | null>(null);
const steamgriddbConfigured = ref(false);
const providerWarnings = ref<string[]>([]);

// picked from the selected metadata result, attached to the game as real
// assets once it's actually saved (see submit())
const pickedKeyArtUrl = ref<string | null>(null);
const pickedBannerUrl = ref<string | null>(null);
const keyArtCandidates = ref<string[]>([]);
const bannerCandidates = ref<string[]>([]);

const hasSteamgriddbKey = computed(
  () => !!currentUser.value?.steamgriddb_api_key,
);

async function searchMetadata() {
  if (metadataQuery.value.trim().length < 2) {
    metadataMessage.value = "Enter at least two characters to search.";
    return;
  }
  searchingMetadata.value = true;
  metadataMessage.value = null;
  providerWarnings.value = [];
  try {
    const response = await searchGameMetadata(metadataQuery.value.trim());
    metadataResults.value = response.results;
    steamgriddbConfigured.value = response.steamgriddb_configured;
    providerWarnings.value = response.provider_errors ?? [];
    if (!metadataResults.value.length)
      metadataMessage.value = "No games found.";
  } catch (err) {
    metadataMessage.value =
      err instanceof Error ? err.message : "Metadata search failed.";
  } finally {
    searchingMetadata.value = false;
  }
}

function applyMetadata(result: MetadataSearchResult) {
  title.value = result.title;
  sortTitle.value = "";
  folderLocation.value = result.title
    .trim()
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  folderTouched.value = false;
  description.value = result.description ?? "";
  developer.value = result.developer ?? "";
  publisher.value = result.publisher ?? "";
  ageRating.value = result.age_rating ?? "";
  timeToBeatHours.value =
    result.time_to_beat_hours != null
      ? String(result.time_to_beat_hours)
      : timeToBeatHours.value;
  releaseDate.value = result.release_date ?? "";
  source.value = result.provider;
  tagsInput.value = result.tags.join(", ");
  featuresInput.value = result.features.join(", ");
  links.value = result.links.map((link) => ({ ...link }));
  pickedKeyArtUrl.value = result.key_art_url;
  pickedBannerUrl.value = result.banner_url;
  keyArtCandidates.value = result.key_art_urls;
  bannerCandidates.value = result.banner_urls;
  metadataResults.value = [];
  metadataQuery.value = result.title;
  metadataMessage.value = `Prefilled from ${result.provider}. Review the fields before saving.`;
}

// when editing, the folder name is already real data, don't let the
// title-blur auto-suggest silently overwrite it
const folderTouched = ref(isEditing.value);
function suggestFolderFromTitle() {
  if (folderTouched.value) return;
  folderLocation.value = title.value
    .trim()
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function resetFileInputOnClick(e: Event) {
  // Clear before the picker opens so selecting the same file again still
  // fires change, while keeping the selected filename visible afterwards.
  (e.currentTarget as HTMLInputElement).value = "";
}

function onCoverFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  coverFile.value = input.files?.[0] ?? null;
}
function onBannerFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  bannerFile.value = input.files?.[0] ?? null;
}

async function submit() {
  if (!title.value.trim()) {
    error.value = "Title is required.";
    activeTab.value = "General";
    return;
  }
  if (!isEditing.value && !folderLocation.value.trim()) {
    error.value = "Folder name is required.";
    activeTab.value = "General";
    return;
  }

  saving.value = true;
  error.value = null;

  const input = {
    title: title.value.trim(),
    sortTitle: sortTitle.value.trim() || null,
    folderLocation: folderLocation.value.trim(),
    status: status.value,
    description: description.value.trim() || null,
    developer: developer.value.trim() || null,
    publisher: publisher.value.trim() || null,
    series: series.value.trim() || null,
    parentGameId: parentGameId.value || null,
    relationshipType: parentGameId.value
      ? relationshipType.value || null
      : null,
    releaseDate: releaseDate.value || null,
    dateAdded: dateAdded.value || null,
    completionDate: completionDate.value || null,
    source: source.value.trim() || null,
    ageRating: ageRating.value.trim() || null,
    timeToBeatHours: timeToBeatHours.value.trim()
      ? Number(timeToBeatHours.value)
      : null,
    region: region.value.trim() || null,
    language: language.value.trim() || null,
    achievementsProvider: achievementsProvider.value,
    ratingOverall: ratingOverall.value,
    ratingStory: ratingStory.value,
    ratingGameplay: ratingGameplay.value,
    ratingSound: ratingSound.value,
    tags: tagsInput.value
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean),
    features: featuresInput.value
      .split(",")
      .map((f) => f.trim())
      .filter(Boolean),
    links: links.value.filter((l) => l.label.trim() && l.url.trim()),
    ownership: {
      format: ownershipFormat.value,
      purchaseDate: purchaseDate.value || null,
      price: price.value,
      priceCurrency:
        price.value !== null
          ? priceCurrency.value.trim().toUpperCase() || "USD"
          : null,
      condition: condition.value.trim() || null,
    },
    favorite: props.game?.favorite ?? false,
    collections: props.game?.collections ?? [],
    profilesEnabled: profilesEnabled.value,
    osrsStatsEnabled: osrsStatsEnabled.value,
  };

  try {
    const savedGame = isEditing.value
      ? await updateGame(props.game!.id, input)
      : await createGame(input);

    if (import.meta.env.VITE_USE_MOCK_DATA !== "true") {
      // an explicitly-chosen file always wins over the metadata-suggested art
      if (coverFile.value) {
        await uploadGameAsset(savedGame.id, "key_art", coverFile.value);
      } else if (pickedKeyArtUrl.value) {
        await attachGameAssetFromUrl(
          savedGame.id,
          "key_art",
          pickedKeyArtUrl.value,
        );
      }
      if (bannerFile.value) {
        await uploadGameAsset(savedGame.id, "banner", bannerFile.value);
      } else if (pickedBannerUrl.value) {
        await attachGameAssetFromUrl(
          savedGame.id,
          "banner",
          pickedBannerUrl.value,
        );
      }
    }

    emit("saved", savedGame.id);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to save game";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-header">
        <h2>{{ isEditing ? "Edit Game" : "Add Game" }}</h2>
        <button type="button" class="close-button" @click="emit('close')">
          ✕
        </button>
      </div>

      <nav class="modal-tabs">
        <button
          v-for="tab in tabs"
          :key="tab"
          type="button"
          class="modal-tab"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          {{ tab }}
        </button>
      </nav>

      <form class="modal-form" @submit.prevent="submit">
        <div class="modal-body">
          <div v-if="activeTab === 'General'" class="tab-panel">
            <div class="metadata-search">
              <div class="search-heading">
                <strong>Find game metadata</strong>
                <span
                  >Search external providers and choose a match to prefill this
                  form.</span
                >
              </div>
              <p v-if="!hasSteamgriddbKey" class="steamgriddb-hint">
                Add your own SteamGridDB API key in
                <router-link to="/settings" @click="emit('close')"
                  >Settings</router-link
                >
                to also pull real cover and hero art automatically: without it,
                only Steam's own (often lower-quality) images are used.
              </p>
              <div class="search-row">
                <input
                  v-model="metadataQuery"
                  type="search"
                  placeholder="Search by game title"
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
                  :key="`${result.provider}-${result.provider_id}`"
                  type="button"
                  class="metadata-result"
                  @click="applyMetadata(result)"
                >
                  <span>{{ result.title }}</span>
                  <small
                    >{{ result.provider
                    }}<span v-if="result.release_date">
                      · {{ result.release_date.slice(0, 4) }}</span
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

            <div class="field-row">
              <label class="field">
                <span>Title</span>
                <input
                  v-model="title"
                  type="text"
                  required
                  @blur="suggestFolderFromTitle"
                />
              </label>
              <label class="field">
                <span>Sorting Name</span>
                <input
                  v-model="sortTitle"
                  type="text"
                  placeholder="defaults to Title"
                />
              </label>
            </div>

            <div class="field-row">
              <label class="field">
                <span>Folder name</span>
                <input
                  v-model="folderLocation"
                  type="text"
                  :required="!isEditing"
                  pattern="[A-Za-z0-9_-]+"
                  :placeholder="isEditing ? 'leave blank to keep current' : ''"
                  @input="folderTouched = true"
                />
              </label>
              <label class="field">
                <span>Status</span>
                <select v-model="status">
                  <option v-for="s in statuses" :key="s" :value="s">
                    {{ s }}
                  </option>
                </select>
              </label>
            </div>

            <div class="field-row">
              <label class="field">
                <span>Developer</span>
                <input v-model="developer" type="text" />
              </label>
              <label class="field">
                <span>Publisher</span>
                <input v-model="publisher" type="text" />
              </label>
            </div>

            <div class="field-row">
              <label class="field">
                <span>Series</span>
                <input v-model="series" type="text" />
              </label>
              <label class="field">
                <span>Source</span>
                <input
                  v-model="source"
                  type="text"
                  placeholder="Steam, GOG, physical..."
                />
              </label>
            </div>

            <div class="field-row">
              <label class="field">
                <span>Parent game</span>
                <select v-model="parentGameId">
                  <option value="">None: this is its own game</option>
                  <option
                    v-for="g in availableParentGames"
                    :key="g.id"
                    :value="g.id"
                  >
                    {{ g.title }}
                  </option>
                </select>
              </label>
              <label class="field">
                <span>Relationship</span>
                <select v-model="relationshipType" :disabled="!parentGameId">
                  <option value="">N/A</option>
                  <option
                    v-for="opt in RELATIONSHIP_TYPE_OPTIONS"
                    :key="opt.value"
                    :value="opt.value"
                  >
                    {{ opt.label }}
                  </option>
                </select>
              </label>
            </div>

            <div class="field-row">
              <label class="checkbox-field">
                <input v-model="profilesEnabled" type="checkbox" />
                <span>
                  Track multiple accounts on this game
                  <small
                    >Adds an account switcher with its own checklist and media
                    for each account, useful for any game with multiple
                    characters/accounts, not just OSRS.</small
                  >
                </span>
              </label>
            </div>

            <div v-if="profilesEnabled" class="field-row">
              <label class="checkbox-field">
                <input v-model="osrsStatsEnabled" type="checkbox" />
                <span>
                  Use OSRS stats (WiseOldMan)
                  <small
                    >Adds skill/boss syncing from wiseoldman.net, real skill
                    icons, and dated stat history to each account. Only makes
                    sense for Old School RuneScape.</small
                  >
                </span>
              </label>
            </div>

            <div class="field-row">
              <label class="field">
                <span>Age Rating</span>
                <input
                  v-model="ageRating"
                  type="text"
                  placeholder="ESRB M, PEGI 18..."
                />
              </label>
              <label class="field">
                <span>Release Date</span>
                <input v-model="releaseDate" type="date" />
              </label>
            </div>

            <div class="field-row">
              <label class="field">
                <span>Time to Beat (hours)</span>
                <input
                  v-model="timeToBeatHours"
                  type="number"
                  min="0"
                  step="0.5"
                  placeholder="e.g. 12.5"
                />
              </label>
            </div>

            <div class="field-row">
              <label class="field">
                <span>Region</span>
                <input
                  v-model="region"
                  type="text"
                  placeholder="NA, PAL, JP..."
                />
              </label>
              <label class="field">
                <span>Language</span>
                <input
                  v-model="language"
                  type="text"
                  placeholder="English, Japanese..."
                />
              </label>
            </div>

            <label class="field">
              <span>Date added to library</span>
              <input v-model="dateAdded" type="date" />
            </label>

            <label class="field">
              <span>Description</span>
              <textarea v-model="description" rows="3"></textarea>
            </label>
          </div>

          <div v-else-if="activeTab === 'Ratings & Tags'" class="tab-panel">
            <div class="field-row ratings-row">
              <label class="field">
                <span>Atmosphere</span>
                <input
                  v-model.number="ratingOverall"
                  type="number"
                  min="0"
                  max="10"
                  step="0.1"
                />
              </label>
              <label class="field">
                <span>Story</span>
                <input
                  v-model.number="ratingStory"
                  type="number"
                  min="0"
                  max="10"
                  step="0.1"
                />
              </label>
              <label class="field">
                <span>Gameplay</span>
                <input
                  v-model.number="ratingGameplay"
                  type="number"
                  min="0"
                  max="10"
                  step="0.1"
                />
              </label>
              <label class="field">
                <span>Sound</span>
                <input
                  v-model.number="ratingSound"
                  type="number"
                  min="0"
                  max="10"
                  step="0.1"
                />
              </label>
            </div>

            <label class="field">
              <span>Tags (comma separated)</span>
              <input
                v-model="tagsInput"
                type="text"
                placeholder="Action RPG, Souls-Like"
              />
            </label>

            <label class="field">
              <span>Features (comma separated)</span>
              <input
                v-model="featuresInput"
                type="text"
                placeholder="Achievements, Cloud Saves"
              />
            </label>

            <label class="field">
              <span>Achievement Tracking</span>
              <select v-model="achievementsProvider">
                <option :value="null">None</option>
                <option value="native">Native</option>
                <option value="retroachievements">RetroAchievements</option>
              </select>
            </label>
          </div>

          <div v-else-if="activeTab === 'Media'" class="tab-panel">
            <label class="field">
              <span>Cover image (portrait)</span>
              <input
                type="file"
                accept="image/*"
                @click="resetFileInputOnClick"
                @change="onCoverFileChange"
              />
            </label>

            <div v-if="keyArtCandidates.length > 1" class="media-candidates">
              <span class="candidates-label">Or pick from metadata search</span>
              <div class="candidates-grid">
                <button
                  v-for="url in keyArtCandidates"
                  :key="url"
                  type="button"
                  class="candidate-thumb"
                  :class="{ active: pickedKeyArtUrl === url }"
                  @click="
                    pickedKeyArtUrl = url;
                    coverFile = null;
                  "
                >
                  <img :src="url" alt="" />
                </button>
              </div>
            </div>

            <label class="field">
              <span>Banner image (landscape)</span>
              <input
                type="file"
                accept="image/*"
                @click="resetFileInputOnClick"
                @change="onBannerFileChange"
              />
            </label>

            <div v-if="bannerCandidates.length > 1" class="media-candidates">
              <span class="candidates-label">Or pick from metadata search</span>
              <div class="candidates-grid banner-grid">
                <button
                  v-for="url in bannerCandidates"
                  :key="url"
                  type="button"
                  class="candidate-thumb banner-thumb"
                  :class="{ active: pickedBannerUrl === url }"
                  @click="
                    pickedBannerUrl = url;
                    bannerFile = null;
                  "
                >
                  <img :src="url" alt="" />
                </button>
              </div>
            </div>

            <p class="hint">
              Choose a file here to stage it for upload. The image is uploaded
              when you click Add Game or Save Changes; it is not sent
              immediately when selected.
            </p>
          </div>

          <div v-else-if="activeTab === 'Links'" class="tab-panel">
            <div
              v-for="(link, index) in links"
              :key="index"
              class="field-row link-row"
            >
              <label class="field">
                <span>Label</span>
                <input
                  v-model="link.label"
                  type="text"
                  placeholder="Steam Store Page"
                />
              </label>
              <label class="field">
                <span>URL</span>
                <input
                  v-model="link.url"
                  type="url"
                  placeholder="https://..."
                />
              </label>
              <button
                type="button"
                class="remove-button"
                @click="removeLink(index)"
              >
                ✕
              </button>
            </div>
            <button type="button" class="secondary-button" @click="addLink">
              + Add Link
            </button>
          </div>

          <div v-else-if="activeTab === 'Ownership'" class="tab-panel">
            <label class="field">
              <span>Format</span>
              <select v-model="ownershipFormat">
                <option :value="null">Unspecified</option>
                <option value="digital">Digital</option>
                <option value="physical">Physical</option>
              </select>
            </label>

            <div class="field-row">
              <label class="field">
                <span>Purchase date</span>
                <input v-model="purchaseDate" type="date" />
              </label>
              <label class="field">
                <span>100% completion date</span>
                <input v-model="completionDate" type="date" />
              </label>
              <label class="field">
                <span>Price</span>
                <input
                  v-model.number="price"
                  type="number"
                  min="0"
                  step="0.01"
                />
              </label>
              <label class="field">
                <span>Currency</span>
                <input
                  v-model="priceCurrency"
                  type="text"
                  placeholder="USD"
                  maxlength="3"
                />
              </label>
            </div>

            <label v-if="ownershipFormat === 'physical'" class="field">
              <span>Condition / notes</span>
              <input
                v-model="condition"
                type="text"
                placeholder="CIB, disc only, box wear..."
              />
            </label>
          </div>

          <div v-if="error" class="form-error">{{ error }}</div>
        </div>

        <div class="modal-actions">
          <button
            v-if="isEditing"
            type="button"
            class="danger-button"
            @click="emit('delete', props.game!.id)"
          >
            Delete Game
          </button>
          <div class="modal-actions-spacer"></div>
          <button type="button" class="secondary-button" @click="emit('close')">
            Cancel
          </button>
          <button type="submit" class="primary-button" :disabled="saving">
            {{ saving ? "Saving…" : isEditing ? "Save Changes" : "Add Game" }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 14px;
  width: 100%;
  max-width: 760px;
  height: 640px;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  color: #fff;
  font-family: system-ui, sans-serif;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 22px;
  border-bottom: 1px solid #2a2a2a;
  flex-shrink: 0;
}
.modal-header h2 {
  margin: 0;
  font-size: 1.2rem;
}
.close-button {
  background: none;
  border: none;
  color: #999;
  font-size: 15px;
  cursor: pointer;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.close-button:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}
.modal-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 20px 0;
  border-bottom: 1px solid #2a2a2a;
  flex-shrink: 0;
  overflow-x: auto;
}
.modal-tab {
  background: none;
  border: none;
  color: #999;
  padding: 9px 16px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 8px 8px 0 0;
  white-space: nowrap;
  border-bottom: 2px solid transparent;
  transition:
    color 0.15s ease,
    background 0.15s ease;
}
.modal-tab:hover {
  color: #ddd;
  background: rgba(255, 255, 255, 0.05);
}
.modal-tab.active {
  color: #fff;
  background: rgba(214, 138, 52, 0.1);
  border-bottom-color: #d68a34;
}
.modal-form {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.modal-body {
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}
.tab-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 380px;
}
.metadata-search {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.search-heading {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.search-heading strong {
  font-size: 0.85rem;
  color: #ccc;
}
.search-heading span,
.metadata-result small {
  color: #888;
  font-size: 0.78rem;
}
.steamgriddb-hint {
  margin: 0;
  padding: 0;
  background: none;
  border: none;
  color: #888;
  font-size: 0.78rem;
  line-height: 1.5;
}
.steamgriddb-hint a {
  color: #d68a34;
  font-weight: 600;
  text-decoration: none;
}
.steamgriddb-hint a:hover {
  text-decoration: underline;
}
.search-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
}
.search-row input {
  flex: 1;
  min-width: 0;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 9px 11px;
  font: inherit;
  transition: border-color 0.15s ease;
}
.search-row input:focus {
  outline: none;
  border-color: #d68a34;
}
.search-row .secondary-button {
  flex-shrink: 0;
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
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  cursor: pointer;
}
.metadata-result:hover {
  border-color: #d68a34;
  background: #282828;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.85rem;
  color: #ccc;
  flex: 1;
}
.checkbox-field {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 0.85rem;
  color: #ccc;
  flex: 1;
  cursor: pointer;
}
.checkbox-field input[type="checkbox"] {
  margin-top: 3px;
  width: 16px;
  height: 16px;
  accent-color: #d68a34;
  flex-shrink: 0;
}
.checkbox-field span {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.checkbox-field small {
  color: #888;
  font-size: 0.75rem;
  font-weight: 400;
}
.field input,
.field select,
.field textarea {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 9px 11px;
  font: inherit;
  transition: border-color 0.15s ease;
}
.field input:focus,
.field select:focus,
.field textarea:focus {
  outline: none;
  border-color: #d68a34;
}
.field-row {
  display: flex;
  gap: 12px;
}
.ratings-row .field {
  min-width: 0;
}
.link-row {
  align-items: flex-end;
}
.remove-button {
  background: rgba(220, 38, 38, 0.15);
  color: #fca5a5;
  border: none;
  border-radius: 8px;
  width: 38px;
  height: 38px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.remove-button:hover {
  background: rgba(220, 38, 38, 0.3);
}
.hint {
  color: #888;
  font-size: 0.8rem;
  margin: 0;
}
.provider-warnings {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.provider-warnings li {
  color: #f0b458;
  font-size: 0.78rem;
}
.media-candidates {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: -6px;
}
.candidates-label {
  color: #999;
  font-size: 0.78rem;
}
.candidates-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.candidate-thumb {
  width: 60px;
  height: 90px;
  padding: 0;
  border: 2px solid transparent;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  background: #111;
  flex-shrink: 0;
}
.candidate-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.candidate-thumb.active {
  border-color: #d68a34;
}
.banner-thumb {
  width: 120px;
  height: 45px;
}
.form-error {
  color: #fca5a5;
  font-size: 0.85rem;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 8px;
  padding: 10px 12px;
}
.modal-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 22px;
  border-top: 1px solid #2a2a2a;
  flex-shrink: 0;
}
.modal-actions-spacer {
  flex: 1;
}
.danger-button {
  background: rgba(220, 38, 38, 0.15);
  color: #fca5a5;
  border: none;
  border-radius: 8px;
  padding: 10px 20px;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.15s ease;
}
.danger-button:hover {
  background: rgba(220, 38, 38, 0.3);
}
.primary-button,
.secondary-button {
  border: none;
  border-radius: 8px;
  padding: 10px 20px;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  transition:
    background 0.15s ease,
    transform 0.05s ease;
}
.primary-button {
  background: #d68a34;
  color: #111;
}
.primary-button:hover:not(:disabled) {
  background: #ffd83d;
}
.primary-button:active:not(:disabled) {
  transform: scale(0.98);
}
.primary-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.secondary-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.secondary-button:hover {
  background: rgba(255, 255, 255, 0.15);
}
</style>
