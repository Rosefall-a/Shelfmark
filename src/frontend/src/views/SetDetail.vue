<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { fetchSet, deleteSet, updateSet } from "../services/set";
import { fetchGames } from "../services/games";
import type { CardSetDetail } from "../types/set";
import type { Game } from "../types/game";
import { useConfirm, usePrompt } from "../state/dialog";

const confirm = useConfirm();
const prompt = usePrompt();

const route = useRoute();
const router = useRouter();
const setId = route.params.id as string;

const set = ref<CardSetDetail | null>(null);
const games = ref<Game[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const gameById = computed(() => new Map(games.value.map((g) => [g.id, g])));

async function load() {
  loading.value = true;
  try {
    const [s, g] = await Promise.all([fetchSet(setId), fetchGames()]);
    set.value = s;
    games.value = g;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load set.";
  } finally {
    loading.value = false;
  }
}

async function handleDelete() {
  if (!set.value) return;
  const ok = await confirm({
    title: "Delete set",
    message: `Delete set "${set.value.name}"? Cards in it are just unassigned, not deleted.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  await deleteSet(setId);
  router.push("/sets");
}

async function editTarget() {
  if (!set.value) return;
  const input = await prompt({
    title: "Cards in this set",
    message: "Total cards expected for this set (blank for unknown).",
    defaultValue: String(set.value.targetTotal ?? ""),
  });
  if (input === null) return;
  const target = input.trim() === "" ? null : Number(input);
  await updateSet(setId, {
    targetTotal: Number.isFinite(target) ? target : null,
  });
  await load();
}

onMounted(load);
</script>

<template>
  <main class="set-detail-page">
    <button type="button" class="back-btn" @click="router.push('/sets')">
      &larr; Sets
    </button>

    <p v-if="loading" class="empty-state">Loading…</p>
    <p v-else-if="error" class="empty-state error">{{ error }}</p>

    <template v-else-if="set">
      <div class="header-row">
        <div>
          <h1>{{ set.name }}</h1>
          <p class="progress">
            {{
              set.targetTotal
                ? `${set.cardCount} / ${set.targetTotal} cards`
                : `${set.cardCount} cards`
            }}
            <button type="button" class="link-btn" @click="editTarget">
              edit target
            </button>
          </p>
        </div>
        <button type="button" class="danger-button" @click="handleDelete">
          Delete set
        </button>
      </div>

      <div v-if="set.isComplete" class="complete-banner">
        <span class="complete-glow"></span>
        <span
          >SET COMPLETE &mdash; {{ set.cardCount }} /
          {{ set.targetTotal }}</span
        >
      </div>

      <p v-if="!set.cards.length" class="empty-state">
        No cards in this set yet. Assign one from a card's own detail page.
      </p>
      <div v-else class="cards-grid">
        <button
          v-for="c in set.cards"
          :key="c.id"
          type="button"
          class="card-tile"
          @click="router.push(`/cards/${c.id}`)"
        >
          <span class="card-tile-title">{{
            gameById.get(c.gameId)?.title ?? "Unknown game"
          }}</span>
          <span class="card-tile-num"
            >#{{ String(c.archiveNumber ?? 0).padStart(3, "0") }}</span
          >
        </button>
      </div>
    </template>
  </main>
</template>

<style scoped>
.set-detail-page {
  min-height: 100vh;
  background: #121212;
  color: #fff;
  padding: 84px 24px 24px;
  font-family: system-ui, sans-serif;
  box-sizing: border-box;
}
.back-btn {
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0;
  margin-bottom: 16px;
}
.back-btn:hover {
  color: #d68a34;
}
.empty-state {
  color: #777;
}
.empty-state.error {
  color: #fca5a5;
}
.header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
h1 {
  margin: 0 0 4px;
}
.progress {
  color: #999;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.link-btn {
  background: none;
  border: none;
  color: #d68a34;
  font-size: 0.75rem;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
}
.danger-button {
  background: #1a1a1a;
  border: 1px solid #5c2626;
  color: #fca5a5;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 0.8rem;
  cursor: pointer;
}
.complete-banner {
  position: relative;
  margin: 18px 0;
  padding: 14px 18px;
  border-radius: 10px;
  border: 1px solid #d68a34;
  background: rgba(214, 138, 52, 0.1);
  color: #d68a34;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-align: center;
  overflow: hidden;
}
.complete-glow {
  position: absolute;
  inset: 0;
  background: radial-gradient(
    ellipse at center,
    rgba(214, 138, 52, 0.25),
    transparent 70%
  );
  pointer-events: none;
}
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 16px;
  margin-top: 20px;
}
.card-tile {
  aspect-ratio: 5 / 7;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: flex-start;
  padding: 12px;
  cursor: pointer;
  color: #fff;
  text-align: left;
}
.card-tile:hover {
  border-color: #d68a34;
}
.card-tile-title {
  font-weight: 600;
  font-size: 0.85rem;
}
.card-tile-num {
  font-size: 0.7rem;
  color: #999;
  margin-top: 4px;
}
</style>
