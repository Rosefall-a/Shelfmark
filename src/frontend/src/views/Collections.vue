<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import CollectionCard from "../components/CollectionCard.vue";
import AccountChip from "../components/AccountChip.vue";
import { fetchGames } from "../services/games";
import type { Game } from "../types/game";
import {
  smartCollections,
  addSmartCollection,
  removeSmartCollection,
  matchesSmartCollection,
  SMART_FIELD_LABELS,
} from "../state/smartCollections";
import type { SmartField } from "../state/smartCollections";
import type { GameStatus } from "../types/game";
import { useConfirm, usePrompt } from "../state/dialog";

const confirm = useConfirm();
const prompt = usePrompt();

type SortBy = "name" | "count";

const router = useRouter();

const games = ref<Game[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const searchQuery = ref("");
const sortBy = ref<SortBy>("name");

// Empty collections (no games assigned yet) have nowhere to live on the
// backend, so they're tracked locally until a game is actually added to them.
const MANUAL_COLLECTIONS_KEY = "manualCollections";
const manualCollectionNames = ref<string[]>(loadManualCollections());

function loadManualCollections(): string[] {
  try {
    const raw = localStorage.getItem(MANUAL_COLLECTIONS_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function saveManualCollections() {
  localStorage.setItem(
    MANUAL_COLLECTIONS_KEY,
    JSON.stringify(manualCollectionNames.value),
  );
}

const createError = ref<string | null>(null);

function addCollectionName(trimmed: string): boolean {
  const alreadyExists = collectionSummaries.value.some(
    (c) => c.name.toLowerCase() === trimmed.toLowerCase(),
  );
  if (alreadyExists) {
    createError.value = `"${trimmed}" already exists.`;
    return false;
  }
  createError.value = null;
  manualCollectionNames.value.push(trimmed);
  saveManualCollections();
  return true;
}

async function createCollection() {
  createError.value = null;
  const name = await prompt({
    title: "New collection",
    message:
      'Name your new collection (use "Parent/Child" to nest it under another).',
    confirmLabel: "Create",
  });
  if (!name || !name.trim()) return;
  addCollectionName(name.trim());
}

// one-click starter suggestions, a blank "Create Collection" prompt gives
// no sense of what a collection is even for, until you've made a few
const STARTER_TEMPLATES = [
  "Currently Playing",
  "Backlog Priority",
  "Co-op Games",
];
const showTemplates = ref(false);
function useTemplate(name: string) {
  if (addCollectionName(name)) showTemplates.value = false;
}

async function loadGames() {
  loading.value = true;
  try {
    games.value = await fetchGames();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load games";
  } finally {
    loading.value = false;
  }
}

onMounted(loadGames);

interface CollectionSummary {
  name: string;
  games: Game[];
  isSmart?: boolean;
}

// which game's cover represents each collection, set from CollectionDetail.vue's
// "Cover" picker, keyed by collection name since collections have no
// backend row of their own to hang this off
function loadCoverPicks(): Record<string, string> {
  try {
    const raw = localStorage.getItem("collectionCoverPicks");
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

const collectionSummaries = computed<CollectionSummary[]>(() => {
  const map = new Map<string, Game[]>();
  for (const g of games.value) {
    for (const c of g.collections) {
      if (!map.has(c)) map.set(c, []);
      map.get(c)!.push(g);
    }
  }
  for (const name of manualCollectionNames.value) {
    if (!map.has(name)) map.set(name, []);
  }
  const coverPicks = loadCoverPicks();
  const manual = Array.from(map.entries()).map(([name, list]) => {
    const pickedId = coverPicks[name];
    const pickedIndex = pickedId
      ? list.findIndex((g) => g.id === pickedId)
      : -1;
    const orderedGames =
      pickedIndex > 0
        ? [
            list[pickedIndex],
            ...list.slice(0, pickedIndex),
            ...list.slice(pickedIndex + 1),
          ]
        : list;
    return { name, games: orderedGames };
  });
  const smart = smartCollections.value.map((rule) => ({
    name: rule.name,
    games: games.value.filter((g) => matchesSmartCollection(g, rule)),
    isSmart: true,
  }));
  return [...manual, ...smart];
});

const filteredCollections = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  let result = collectionSummaries.value;
  if (q) {
    result = result.filter((c) => c.name.toLowerCase().includes(q));
  }
  return [...result].sort((a, b) => {
    if (sortBy.value === "count") return b.games.length - a.games.length;
    return a.name.localeCompare(b.name);
  });
});

function openCollection(name: string) {
  router.push(`/collections/${encodeURIComponent(name)}`);
}

// --- smart collections -----------------------------------------------
const STATUS_OPTIONS: GameStatus[] = [
  "playing",
  "beaten",
  "mastered",
  "played",
  "on hold",
  "dropped",
  "backlog",
  "wishlist",
];
const showSmartForm = ref(false);
const smartName = ref("");
const smartField = ref<SmartField>("status");
const smartValue = ref("");
const smartError = ref<string | null>(null);

const sourceOptions = computed(() => {
  const set = new Set<string>();
  for (const g of games.value) if (g.source) set.add(g.source);
  return [...set].sort();
});
const tagOptions = computed(() => {
  const set = new Set<string>();
  for (const g of games.value) for (const t of g.tags) set.add(t);
  return [...set].sort();
});

function openSmartForm() {
  smartName.value = "";
  smartField.value = "status";
  smartValue.value = "";
  smartError.value = null;
  showSmartForm.value = true;
}

function createSmartCollection() {
  const name = smartName.value.trim();
  if (!name) {
    smartError.value = "Give it a name.";
    return;
  }
  if (
    collectionSummaries.value.some(
      (c) => c.name.toLowerCase() === name.toLowerCase(),
    )
  ) {
    smartError.value = `"${name}" already exists.`;
    return;
  }
  if (smartField.value !== "favorite" && !smartValue.value.trim()) {
    smartError.value = "Pick a value for the rule.";
    return;
  }
  addSmartCollection({
    name,
    field: smartField.value,
    value: smartValue.value.trim(),
  });
  showSmartForm.value = false;
}

async function deleteSmartCollection(id: string) {
  const ok = await confirm({
    title: "Delete smart collection",
    message:
      "Delete this smart collection? This only removes the rule, no games are affected.",
    confirmLabel: "Delete",
    danger: true,
  });
  if (ok) removeSmartCollection(id);
}
function smartIdForName(name: string): string | undefined {
  return smartCollections.value.find((c) => c.name === name)?.id;
}
</script>

<template>
  <main class="collections-page">
    <AccountChip fixed />

    <div class="content">
      <div class="header-row">
        <div>
          <h1>Collections</h1>
          <div class="sub">
            {{ collectionSummaries.length }}
            {{
              collectionSummaries.length === 1 ? "collection" : "collections"
            }}
          </div>
        </div>
        <div class="header-actions">
          <input
            v-model="searchQuery"
            type="text"
            class="search-input"
            placeholder="Search collections…"
          />
          <select v-model="sortBy" class="filter-select">
            <option value="name">Name</option>
            <option value="count">Most Games</option>
          </select>
          <div class="templates-wrap">
            <button
              type="button"
              class="secondary-button"
              @click="showTemplates = !showTemplates"
            >
              Starter templates
            </button>
            <div v-if="showTemplates" class="templates-dropdown">
              <button
                v-for="t in STARTER_TEMPLATES"
                :key="t"
                type="button"
                class="template-item"
                :disabled="
                  collectionSummaries.some(
                    (c) => c.name.toLowerCase() === t.toLowerCase(),
                  )
                "
                @click="useTemplate(t)"
              >
                {{ t }}
              </button>
            </div>
          </div>
          <button type="button" class="secondary-button" @click="openSmartForm">
            + Smart Collection
          </button>
          <button type="button" class="add-button" @click="createCollection">
            + Create Collection
          </button>
        </div>
      </div>

      <p v-if="createError" class="error create-error">{{ createError }}</p>

      <p v-if="loading">Loading…</p>
      <p v-else-if="error" class="error">{{ error }}</p>

      <template v-else>
        <div v-if="filteredCollections.length" class="grid">
          <CollectionCard
            v-for="col in filteredCollections"
            :key="col.name"
            :name="col.name"
            :games="col.games"
            :is-smart="col.isSmart"
            @open="openCollection"
            @delete="deleteSmartCollection(smartIdForName(col.name)!)"
          />
        </div>
        <p v-else class="empty-row">
          No collections yet: create one above, or use a game's collection
          button to start one.
        </p>
      </template>
    </div>

    <div
      v-if="showSmartForm"
      class="confirm-backdrop"
      @click.self="showSmartForm = false"
    >
      <div class="confirm-dialog">
        <h3>New smart collection</h3>
        <p class="dialog-hint">
          Membership updates automatically as your library changes.
        </p>
        <label class="field-label">
          Name
          <input
            v-model="smartName"
            type="text"
            class="dialog-input"
            placeholder="e.g. Mastered Games"
          />
        </label>
        <label class="field-label">
          Rule
          <select v-model="smartField" class="dialog-input">
            <option
              v-for="(label, key) in SMART_FIELD_LABELS"
              :key="key"
              :value="key"
            >
              {{ label }}
            </option>
          </select>
        </label>
        <label v-if="smartField === 'status'" class="field-label">
          Value
          <select v-model="smartValue" class="dialog-input">
            <option value="">Select…</option>
            <option v-for="s in STATUS_OPTIONS" :key="s" :value="s">
              {{ s }}
            </option>
          </select>
        </label>
        <label v-else-if="smartField === 'playtime_hours'" class="field-label">
          Hours
          <input
            v-model="smartValue"
            type="number"
            min="0"
            class="dialog-input"
            placeholder="e.g. 20"
          />
        </label>
        <label v-else-if="smartField === 'tag'" class="field-label">
          Tag
          <input
            v-model="smartValue"
            type="text"
            list="smart-tag-options"
            class="dialog-input"
            placeholder="e.g. RPG"
          />
          <datalist id="smart-tag-options">
            <option v-for="t in tagOptions" :key="t" :value="t" />
          </datalist>
        </label>
        <label v-else-if="smartField === 'source'" class="field-label">
          Source
          <input
            v-model="smartValue"
            type="text"
            list="smart-source-options"
            class="dialog-input"
            placeholder="e.g. Steam"
          />
          <datalist id="smart-source-options">
            <option v-for="s in sourceOptions" :key="s" :value="s" />
          </datalist>
        </label>
        <div v-if="smartError" class="error create-error">{{ smartError }}</div>
        <div class="confirm-actions">
          <button
            type="button"
            class="secondary-button"
            @click="showSmartForm = false"
          >
            Cancel
          </button>
          <button
            type="button"
            class="add-button"
            @click="createSmartCollection"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.collections-page {
  position: relative;
  padding: 84px 24px 24px;
  font-family: system-ui, sans-serif;
  background: #0d0d0d;
  min-height: 100vh;
  color: #fff;
}
.header-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}
.header-row h1 {
  margin: 0;
  font-size: 1.7rem;
  font-weight: 800;
}
.header-row .sub {
  margin-top: 2px;
  color: #888;
  font-size: 0.85rem;
}
.header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.search-input,
.filter-select {
  height: 38px;
  box-sizing: border-box;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 0 14px;
  font: inherit;
  font-size: 13px;
  transition: border-color 0.15s ease;
}
.search-input {
  width: 220px;
}
.search-input:focus,
.filter-select:focus {
  outline: none;
  border-color: #d68a34;
}
.filter-select:hover {
  border-color: #4a4a4a;
}
.filter-select {
  appearance: none;
  -webkit-appearance: none;
  padding-right: 34px;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' stroke='%23999' stroke-width='1.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>");
  background-repeat: no-repeat;
  background-position: right 16px center;
}
.add-button {
  height: 38px;
  box-sizing: border-box;
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 8px;
  padding: 0 18px;
  font-weight: 600;
  cursor: pointer;
}
.templates-wrap {
  position: relative;
}
.secondary-button {
  height: 38px;
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #ccc;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.secondary-button:hover {
  border-color: #4a4a4a;
  color: #fff;
}
.templates-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 200px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 6px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  z-index: 20;
}
.template-item {
  display: block;
  width: 100%;
  background: none;
  border: none;
  color: #eee;
  font-size: 13px;
  text-align: left;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
}
.template-item:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}
.template-item:disabled {
  color: #555;
  cursor: not-allowed;
}
/* fixed 10-per-row grid, column width only depends on the container, never
   on how many collections there are, so adding one more just starts filling
   the next row instead of resizing every existing card */
.grid {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 16px;
}
.grid :deep(.collection-card-wrap) {
  width: auto;
  min-width: 0;
}
.empty-row {
  color: #777;
  font-size: 14px;
}
.error {
  color: #f87171;
}
.create-error {
  font-size: 13px;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 16px;
}
.confirm-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}
.confirm-dialog {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 22px;
  width: 100%;
  max-width: 360px;
  max-height: 85vh;
  overflow-y: auto;
  box-sizing: border-box;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}
.confirm-dialog h3 {
  margin: 0 0 6px;
  color: #fff;
}
.dialog-hint {
  color: #999;
  font-size: 12.5px;
  margin: 0 0 16px;
}
.field-label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.82rem;
  color: #ccc;
  margin-bottom: 14px;
}
.dialog-input {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 9px 12px;
  font: inherit;
  font-size: 13px;
}
.dialog-input:focus {
  outline: none;
  border-color: #d68a34;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 6px;
}
</style>
