<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { fetchSets, createSet } from "../services/set";
import type { CardSet } from "../types/set";

const router = useRouter();

const sets = ref<CardSet[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const newName = ref("");
const newTarget = ref<number | null>(null);
const creating = ref(false);
const createError = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    sets.value = await fetchSets();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load sets.";
  } finally {
    loading.value = false;
  }
}

async function handleCreate() {
  const name = newName.value.trim();
  if (!name) return;
  creating.value = true;
  createError.value = null;
  try {
    await createSet({ name, targetTotal: newTarget.value });
    newName.value = "";
    newTarget.value = null;
    await load();
  } catch (e) {
    createError.value =
      e instanceof Error ? e.message : "Failed to create set.";
  } finally {
    creating.value = false;
  }
}

onMounted(load);
</script>

<template>
  <main class="sets-page">
    <h1>Sets</h1>
    <p class="section-hint">
      Group cards with a position and total. Assign a card to a set from the
      card's own detail page. When every card you expect is in, the set shows as
      complete.
    </p>

    <div class="create-row">
      <input
        v-model="newName"
        type="text"
        class="text-input"
        placeholder="New set name"
        @keyup.enter="handleCreate"
      />
      <input
        v-model.number="newTarget"
        type="number"
        min="1"
        class="text-input target-input"
        placeholder="Total (optional)"
      />
      <button
        type="button"
        class="add-button"
        :disabled="creating || !newName.trim()"
        @click="handleCreate"
      >
        + Create Set
      </button>
    </div>
    <p v-if="createError" class="error">{{ createError }}</p>

    <p v-if="loading" class="empty-state">Loading…</p>
    <p v-else-if="error" class="empty-state error">{{ error }}</p>
    <p v-else-if="!sets.length" class="empty-state">No sets yet.</p>

    <div v-else class="sets-grid">
      <button
        v-for="s in sets"
        :key="s.id"
        type="button"
        class="set-card"
        :class="{ complete: s.isComplete }"
        @click="router.push(`/sets/${s.id}`)"
      >
        <span v-if="s.isComplete" class="complete-badge">COMPLETE</span>
        <h3>{{ s.name }}</h3>
        <p class="progress">
          {{
            s.targetTotal
              ? `${s.cardCount} / ${s.targetTotal}`
              : `${s.cardCount} card${s.cardCount === 1 ? "" : "s"}`
          }}
        </p>
      </button>
    </div>
  </main>
</template>

<style scoped>
.sets-page {
  min-height: 100vh;
  background: #121212;
  color: #fff;
  padding: 84px 24px 24px;
  font-family: system-ui, sans-serif;
  box-sizing: border-box;
}
h1 {
  margin: 0;
}
.section-hint {
  color: #999;
  font-size: 0.85rem;
  max-width: 60ch;
}
.empty-state {
  color: #777;
}
.empty-state.error,
.error {
  color: #fca5a5;
}
.add-button {
  background: #d68a34;
  border: none;
  border-radius: 8px;
  padding: 9px 14px;
  font-size: 0.85rem;
  color: #121212;
  font-weight: 700;
  cursor: pointer;
}
.add-button:disabled {
  opacity: 0.5;
  cursor: default;
}
.create-row {
  display: flex;
  gap: 10px;
  margin: 18px 0;
  flex-wrap: wrap;
}
.text-input {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  color: #fff;
  padding: 9px 12px;
  font-size: 0.85rem;
}
.target-input {
  width: 160px;
}
.sets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
  margin-top: 20px;
}
.set-card {
  position: relative;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 18px;
  text-align: left;
  cursor: pointer;
  color: #fff;
}
.set-card:hover {
  border-color: #d68a34;
}
.set-card.complete {
  border-color: #d68a34;
}
.complete-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  font-size: 0.6rem;
  font-weight: 700;
  background: #d68a34;
  color: #121212;
  border-radius: 999px;
  padding: 2px 8px;
}
.set-card h3 {
  margin: 0 0 6px;
  font-size: 1rem;
}
.progress {
  color: #999;
  font-size: 0.85rem;
  margin: 0;
}
</style>
