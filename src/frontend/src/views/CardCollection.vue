<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { listCards, createCard } from "../services/cards";
import { fetchGames } from "../services/games";
import { fetchBounties } from "../services/bounties";
import type { Bounty } from "../services/bounties";
import type { Card, CardRarity } from "../types/card";
import type { Game } from "../types/game";

const router = useRouter();

const cards = ref<Card[]>([]);
const games = ref<Game[]>([]);
const bounties = ref<Bounty[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const showPicker = ref(false);
const pickerQuery = ref("");
const creating = ref(false);

const RARITY_LETTER: Record<CardRarity, string> = {
  common: "C",
  uncommon: "U",
  rare: "R",
  legendary: "L",
  mythic: "M",
};

const gameById = computed(() => new Map(games.value.map((g) => [g.id, g])));
const bountyById = computed(
  () => new Map(bounties.value.map((b) => [b.id, b])),
);
function isCardPrestiged(c: Card): boolean {
  return (
    !!c.bountyId && bountyById.value.get(c.bountyId)?.status === "completed"
  );
}

const eligibleGames = computed(() => {
  const cardedGameIds = new Set(cards.value.map((c) => c.gameId));
  return games.value.filter(
    (g) =>
      (g.status === "beaten" || g.status === "mastered") &&
      !cardedGameIds.has(g.id) &&
      g.title.toLowerCase().includes(pickerQuery.value.toLowerCase()),
  );
});

async function load() {
  loading.value = true;
  try {
    const [c, g, b] = await Promise.all([
      listCards(),
      fetchGames(),
      fetchBounties(),
    ]);
    cards.value = c;
    games.value = g;
    bounties.value = b;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load cards.";
  } finally {
    loading.value = false;
  }
}

async function handleCreate(gameId: string) {
  creating.value = true;
  try {
    const card = await createCard({ gameId });
    router.push(`/cards/${card.id}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to create card.";
  } finally {
    creating.value = false;
  }
}

onMounted(load);
</script>

<template>
  <main class="cards-page">
    <div class="header-row">
      <h1>Cards</h1>
      <button type="button" class="add-button" @click="showPicker = true">
        + New Card
      </button>
    </div>
    <p class="section-hint">
      Every Collector Card you've generated, front-face up.
    </p>

    <div v-if="showPicker" class="picker-panel">
      <div class="picker-head">
        <h2>New card for which game?</h2>
        <button type="button" class="close-btn" @click="showPicker = false">
          &times;
        </button>
      </div>
      <input
        v-model="pickerQuery"
        type="text"
        class="text-input"
        placeholder="Search Beaten/Mastered games…"
      />
      <p v-if="!eligibleGames.length" class="empty-state">
        No eligible games. A card can only be made for a game marked Beaten or
        Mastered that doesn't already have one.
      </p>
      <ul v-else class="picker-list">
        <li v-for="g in eligibleGames" :key="g.id" class="picker-item">
          <span>{{ g.title }}</span>
          <button
            type="button"
            class="secondary-button"
            :disabled="creating"
            @click="handleCreate(g.id)"
          >
            Create
          </button>
        </li>
      </ul>
    </div>

    <p v-if="loading" class="empty-state">Loading…</p>
    <p v-else-if="error" class="empty-state error">{{ error }}</p>
    <p v-else-if="!cards.length" class="empty-state">No cards yet.</p>

    <div v-else class="cards-grid">
      <button
        v-for="c in cards"
        :key="c.id"
        type="button"
        class="card-tile"
        @click="router.push(`/cards/${c.id}`)"
      >
        <span v-if="c.rarity" class="rarity-chip">{{
          RARITY_LETTER[c.rarity]
        }}</span>
        <span v-if="isCardPrestiged(c)" class="prestige-chip">P</span>
        <span class="card-tile-title">{{
          gameById.get(c.gameId)?.title ?? "Unknown game"
        }}</span>
        <span class="card-tile-num"
          >#{{ String(c.archiveNumber ?? 0).padStart(3, "0") }}</span
        >
      </button>
    </div>
  </main>
</template>

<style scoped>
.cards-page {
  min-height: 100vh;
  background: #121212;
  color: #fff;
  padding: 84px 24px 24px;
  font-family: system-ui, sans-serif;
  box-sizing: border-box;
}
.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
h1 {
  margin: 0;
}
.section-hint {
  color: #999;
  font-size: 0.85rem;
}
.empty-state {
  color: #777;
}
.empty-state.error {
  color: #fca5a5;
}
.add-button {
  background: #d68a34;
  border: none;
  color: #121212;
  font-weight: 700;
  border-radius: 8px;
  padding: 9px 14px;
  font-size: 0.85rem;
  cursor: pointer;
}
.secondary-button {
  background: #111;
  border: 1px solid #2a2a2a;
  color: #ccc;
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 0.8rem;
  cursor: pointer;
}
.secondary-button:disabled {
  opacity: 0.5;
  cursor: default;
}
.picker-panel {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 16px;
  margin: 16px 0;
}
.picker-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.picker-head h2 {
  margin: 0;
  font-size: 1rem;
}
.close-btn {
  background: none;
  border: none;
  color: #999;
  font-size: 1.2rem;
  cursor: pointer;
}
.text-input {
  width: 100%;
  box-sizing: border-box;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  color: #fff;
  padding: 9px 12px;
  font-size: 0.85rem;
  margin: 10px 0;
}
.picker-list {
  list-style: none;
  padding: 0;
  margin: 0;
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.picker-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
}
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 16px;
  margin-top: 20px;
}
.card-tile {
  position: relative;
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
.rarity-chip {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #d68a34;
  color: #121212;
  font-weight: 700;
  font-size: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
}
.prestige-chip {
  position: absolute;
  top: 10px;
  left: 10px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid #d68a34;
  color: #d68a34;
  font-weight: 700;
  font-size: 0.7rem;
  display: flex;
  align-items: center;
  justify-content: center;
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
