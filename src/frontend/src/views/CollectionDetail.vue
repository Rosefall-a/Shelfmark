<script setup lang="ts">
import { computed, ref, onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import GameCard from "../components/GameCard.vue";
import GameFormModal from "../components/GameFormModal.vue";
import CollectionPickerModal from "../components/CollectionPickerModal.vue";
import BackButton from "../components/BackButton.vue";
import AccountChip from "../components/AccountChip.vue";
import {
  fetchGames,
  deleteGame,
  removeGameFromCollection,
} from "../services/games";
import type { Game } from "../types/game";
import {
  findSmartCollectionByName,
  matchesSmartCollection,
  describeSmartCollection,
  removeSmartCollection,
} from "../state/smartCollections";
import { useConfirm } from "../state/dialog";

const confirm = useConfirm();

const route = useRoute();
const router = useRouter();

const games = ref<Game[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const showFormModal = ref(false);
const editingGame = ref<Game | null>(null);

const deletingGame = ref<Game | null>(null);
const deleting = ref(false);
const deleteError = ref<string | null>(null);

const collectionName = computed(() =>
  decodeURIComponent(route.params.name as string),
);
// same "Parent/Child" naming convention as CollectionCard.vue
const nestedParent = computed(() => {
  const idx = collectionName.value.indexOf("/");
  return idx === -1 ? null : collectionName.value.slice(0, idx);
});
const collectionDisplayName = computed(() => {
  const idx = collectionName.value.indexOf("/");
  return idx === -1
    ? collectionName.value
    : collectionName.value.slice(idx + 1);
});

// custom display order, collections have no order of their own on the
// backend (games.collections is just a flat tag), so this lives alongside
// the cover pick below, keyed the same way
const ORDER_KEY = "collectionGameOrder";
function loadOrders(): Record<string, string[]> {
  try {
    const raw = localStorage.getItem(ORDER_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}
function saveOrder(order: string[]) {
  const orders = loadOrders();
  orders[collectionName.value] = order;
  try {
    localStorage.setItem(ORDER_KEY, JSON.stringify(orders));
  } catch {
    // best-effort, falls back to natural order next time
  }
}

const gameOrder = ref<string[] | null>(
  loadOrders()[collectionName.value] ?? null,
);
watch(collectionName, (name) => {
  gameOrder.value = loadOrders()[name] ?? null;
});

const smartRule = computed(() =>
  findSmartCollectionByName(collectionName.value),
);

const collectionGames = computed(() => {
  const members = smartRule.value
    ? games.value.filter((g) => matchesSmartCollection(g, smartRule.value!))
    : games.value.filter((g) => g.collections.includes(collectionName.value));
  if (smartRule.value || !gameOrder.value) return members;
  const byId = new Map(members.map((g) => [g.id, g]));
  const ordered: Game[] = [];
  for (const id of gameOrder.value) {
    const g = byId.get(id);
    if (g) {
      ordered.push(g);
      byId.delete(id);
    }
  }
  // any member not in the saved order (newly added since) goes at the end
  return [...ordered, ...byId.values()];
});

const reorderMode = ref(false);
function moveGame(index: number, direction: -1 | 1) {
  const target = index + direction;
  if (target < 0 || target >= collectionGames.value.length) return;
  const next = collectionGames.value.map((g) => g.id);
  [next[index], next[target]] = [next[target], next[index]];
  gameOrder.value = next;
  saveOrder(next);
}

// which game's cover represents this collection on the Collections grid,
// keyed by collection name, alongside manualCollections' own localStorage
// entry, since collections have no backend row of their own to hang this off
const COLLECTION_COVER_KEY = "collectionCoverPicks";
function loadCoverPicks(): Record<string, string> {
  try {
    const raw = localStorage.getItem(COLLECTION_COVER_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}
const coverPickedGameId = ref<string | null>(
  loadCoverPicks()[collectionName.value] ?? null,
);
function setCoverPick(gameId: string) {
  const picks = loadCoverPicks();
  if (gameId) picks[collectionName.value] = gameId;
  else delete picks[collectionName.value];
  try {
    localStorage.setItem(COLLECTION_COVER_KEY, JSON.stringify(picks));
  } catch {
    // best-effort, the collection just falls back to its default cover collage
  }
  coverPickedGameId.value = gameId || null;
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

function openEditModal(game: Game) {
  editingGame.value = game;
  showFormModal.value = true;
}

async function onGameSaved() {
  showFormModal.value = false;
  editingGame.value = null;
  await loadGames();
}

function onDeleteFromModal(gameId: string) {
  const game = games.value.find((g) => g.id === gameId);
  showFormModal.value = false;
  editingGame.value = null;
  if (game) requestDelete(game);
}

function requestDelete(game: Game) {
  deletingGame.value = game;
  deleteError.value = null;
}

async function confirmDelete() {
  if (!deletingGame.value) return;
  deleting.value = true;
  deleteError.value = null;
  try {
    await deleteGame(deletingGame.value.id);
    deletingGame.value = null;
    await loadGames();
  } catch (err) {
    deleteError.value =
      err instanceof Error ? err.message : "Failed to delete game";
  } finally {
    deleting.value = false;
  }
}

const collectionPickerGame = ref<Game | null>(null);

function handleAddToCollection(game: Game) {
  collectionPickerGame.value = game;
}

async function onCollectionAdded() {
  await loadGames();
}

function goBack() {
  if (window.history.length > 1) {
    router.back();
  } else {
    router.push("/collections");
  }
}

async function deleteSmartRule() {
  if (!smartRule.value) return;
  const ok = await confirm({
    title: "Delete smart collection",
    message: `Delete the smart collection "${collectionName.value}"? This only removes the rule, no games are affected.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  removeSmartCollection(smartRule.value.id);
  router.push("/collections");
}

const deletingCollection = ref(false);
const deleteCollectionError = ref<string | null>(null);

async function deleteCollection() {
  const ok = await confirm({
    title: "Delete collection",
    message: `Delete "${collectionName.value}"? This removes it from every game.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  deletingCollection.value = true;
  deleteCollectionError.value = null;
  try {
    for (const game of collectionGames.value) {
      await removeGameFromCollection(game.id, collectionName.value);
    }
    try {
      const raw = localStorage.getItem("manualCollections");
      const names: string[] = raw ? JSON.parse(raw) : [];
      localStorage.setItem(
        "manualCollections",
        JSON.stringify(names.filter((n) => n !== collectionName.value)),
      );
    } catch {
      // non-critical, manual-collections cleanup is best-effort
    }
    router.push("/collections");
  } catch (err) {
    deleteCollectionError.value =
      err instanceof Error ? err.message : "Failed to delete collection";
    // some games may have already been removed from the collection before
    // the failure, refresh so the list reflects what actually happened
    // server-side instead of showing the stale pre-delete membership
    await loadGames();
  } finally {
    deletingCollection.value = false;
  }
}
</script>

<template>
  <main class="collection-detail">
    <BackButton fixed @click="goBack" />

    <AccountChip fixed />

    <div class="content">
      <div class="header-row">
        <h1>
          <router-link
            v-if="nestedParent"
            :to="`/collections/${encodeURIComponent(nestedParent)}`"
            class="parent-crumb"
            >{{ nestedParent }} ›</router-link
          >
          {{ collectionDisplayName }}
        </h1>
        <span class="count-badge"
          >{{ collectionGames.length }} game{{
            collectionGames.length === 1 ? "" : "s"
          }}</span
        >
        <span
          v-if="smartRule"
          class="smart-rule-badge"
          :title="describeSmartCollection(smartRule)"
          >⚡ {{ describeSmartCollection(smartRule) }}</span
        >
        <div class="header-spacer"></div>
        <template v-if="!smartRule">
          <label v-if="collectionGames.length" class="cover-pick-field">
            <span>Cover</span>
            <select
              class="filter-select"
              :value="coverPickedGameId ?? ''"
              @change="setCoverPick(($event.target as HTMLSelectElement).value)"
            >
              <option value="">First game (default)</option>
              <option v-for="g in collectionGames" :key="g.id" :value="g.id">
                {{ g.title }}
              </option>
            </select>
          </label>
          <button
            v-if="collectionGames.length > 1"
            type="button"
            class="secondary-button"
            :class="{ active: reorderMode }"
            @click="reorderMode = !reorderMode"
          >
            {{ reorderMode ? "Done reordering" : "Reorder" }}
          </button>
          <button
            type="button"
            class="danger-button"
            :disabled="deletingCollection"
            @click="deleteCollection"
          >
            {{ deletingCollection ? "Deleting…" : "Delete Collection" }}
          </button>
        </template>
        <button
          v-else
          type="button"
          class="danger-button"
          @click="deleteSmartRule"
        >
          Delete Rule
        </button>
      </div>
      <p v-if="smartRule" class="smart-hint">
        This collection updates automatically, games are added or removed here
        as your library changes, not managed by hand.
      </p>
      <p v-if="deleteCollectionError" class="error">
        {{ deleteCollectionError }}
      </p>

      <p v-if="loading">Loading…</p>
      <p v-else-if="error" class="error">{{ error }}</p>

      <template v-else>
        <ol v-if="reorderMode && collectionGames.length" class="reorder-list">
          <li
            v-for="(game, index) in collectionGames"
            :key="game.id"
            class="reorder-item"
          >
            <img :src="game.coverImageUrl" alt="" class="reorder-thumb" />
            <span class="reorder-title">{{ game.title }}</span>
            <div class="reorder-arrows">
              <button
                type="button"
                :disabled="index === 0"
                @click="moveGame(index, -1)"
              >
                ↑
              </button>
              <button
                type="button"
                :disabled="index === collectionGames.length - 1"
                @click="moveGame(index, 1)"
              >
                ↓
              </button>
            </div>
          </li>
        </ol>
        <div v-else-if="collectionGames.length" class="grid">
          <GameCard
            v-for="game in collectionGames"
            :key="game.id"
            :game="game"
            @edit="openEditModal"
            @add-to-collection="handleAddToCollection"
          />
        </div>
        <p v-else class="empty-row">No games in this collection.</p>
      </template>

      <CollectionPickerModal
        v-if="collectionPickerGame"
        :game="collectionPickerGame"
        @close="collectionPickerGame = null"
        @added="onCollectionAdded"
      />

      <GameFormModal
        v-if="showFormModal"
        :game="editingGame"
        @close="showFormModal = false"
        @saved="onGameSaved"
        @delete="onDeleteFromModal"
      />

      <div
        v-if="deletingGame"
        class="confirm-backdrop"
        @click.self="deletingGame = null"
      >
        <div class="confirm-dialog">
          <h3>Delete {{ deletingGame.title }}?</h3>
          <p>This can't be undone.</p>
          <div v-if="deleteError" class="confirm-error">{{ deleteError }}</div>
          <div class="confirm-actions">
            <button
              type="button"
              class="secondary-button"
              @click="deletingGame = null"
            >
              Cancel
            </button>
            <button
              type="button"
              class="danger-button"
              :disabled="deleting"
              @click="confirmDelete"
            >
              {{ deleting ? "Deleting…" : "Delete" }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.collection-detail {
  position: relative;
  padding: 84px 24px 24px;
  font-family: system-ui, sans-serif;
  background: #0d0d0d;
  min-height: 100vh;
  color: #fff;
}
.header-row {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-bottom: 24px;
}
.header-spacer {
  flex: 1;
}
.header-row h1 {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
}
.parent-crumb {
  color: #777;
  font-size: 1.1rem;
  font-weight: 600;
  text-decoration: none;
  margin-right: 4px;
}
.parent-crumb:hover {
  color: #d68a34;
}
.count-badge {
  color: #999;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.06);
  padding: 4px 12px;
  border-radius: 999px;
}
.smart-rule-badge {
  color: #d68a34;
  font-size: 12px;
  font-weight: 600;
  background: rgba(214, 138, 52, 0.12);
  border: 1px solid rgba(214, 138, 52, 0.3);
  padding: 4px 12px;
  border-radius: 999px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}
.smart-hint {
  color: #999;
  font-size: 12.5px;
  margin: -10px 0 16px;
}
.cover-pick-field {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #999;
  font-size: 12.5px;
}
.filter-select {
  height: 34px;
  box-sizing: border-box;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 0 12px;
  font: inherit;
  font-size: 13px;
  max-width: 200px;
}
.filter-select:focus {
  outline: none;
  border-color: #d68a34;
}
/* fixed 10-per-row grid, column width only depends on the container, never
   on how many games there are, so adding one more game just starts filling
   the next row instead of resizing every existing card */
.grid {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 16px;
}
.grid :deep(.game-card-wrap) {
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
.confirm-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}
.confirm-dialog {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 22px;
  width: 100%;
  max-width: 360px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}
.confirm-dialog h3 {
  margin: 0 0 8px;
}
.confirm-dialog p {
  margin: 0 0 16px;
  color: #aaa;
  font-size: 14px;
}
.confirm-error {
  color: #fca5a5;
  font-size: 13px;
  margin-bottom: 12px;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.secondary-button,
.danger-button {
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-weight: 600;
  cursor: pointer;
}
.secondary-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.secondary-button.active {
  background: #d68a34;
  color: #111;
}
.reorder-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: 480px;
}
.reorder-item {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  padding: 8px 12px;
}
.reorder-thumb {
  width: 32px;
  height: 44px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
}
.reorder-title {
  flex: 1;
  color: #fff;
  font-size: 13.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.reorder-arrows {
  display: flex;
  gap: 4px;
}
.reorder-arrows button {
  background: rgba(255, 255, 255, 0.08);
  border: none;
  border-radius: 6px;
  color: #fff;
  width: 26px;
  height: 26px;
  cursor: pointer;
}
.reorder-arrows button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.danger-button {
  background: #dc2626;
  color: #fff;
}
.danger-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
