<script setup lang="ts">
import { computed } from "vue";
import type { Game } from "../types/game";

const props = defineProps<{
  name: string;
  games: Game[];
  isSmart?: boolean;
}>();

const emit = defineEmits<{
  open: [name: string];
  delete: [];
}>();

const covers = computed(() =>
  props.games.slice(0, 4).map((g) => g.coverImageUrl),
);
const emptySlots = computed(() => Math.max(0, 4 - covers.value.length));

// nesting is a pure naming convention, "Parent/Child", not a separate
// data model, since collections have no backend row to hang real
// parent/child structure off in the first place
const slashIndex = computed(() => props.name.indexOf("/"));
const parentLabel = computed(() =>
  slashIndex.value === -1 ? null : props.name.slice(0, slashIndex.value),
);
const displayName = computed(() =>
  slashIndex.value === -1 ? props.name : props.name.slice(slashIndex.value + 1),
);
</script>

<template>
  <div
    class="collection-card-wrap"
    role="button"
    tabindex="0"
    @click="emit('open', name)"
    @keydown.enter.self="emit('open', name)"
    @keydown.space.self.prevent="emit('open', name)"
  >
    <div class="collection-card">
      <div class="cover">
        <div class="cover-grid">
          <div
            v-for="(cover, i) in covers"
            :key="i"
            class="cover-cell"
            :style="{ backgroundImage: `url(${cover})` }"
          ></div>
          <div
            v-for="i in emptySlots"
            :key="`empty-${i}`"
            class="cover-cell empty"
          ></div>
        </div>
        <span
          v-if="isSmart"
          class="smart-badge"
          title="Auto-updates based on a rule"
          >⚡ Auto</span
        >
        <button
          v-if="isSmart"
          type="button"
          class="smart-delete"
          title="Delete this smart collection"
          @click.stop="emit('delete')"
        >
          ✕
        </button>
      </div>
    </div>

    <div class="card-info">
      <span v-if="parentLabel" class="parent-eyebrow">{{ parentLabel }} ›</span>
      <h3 class="title">{{ displayName }}</h3>
      <div class="meta-row">
        <span class="status"
          >{{ games.length }} game{{ games.length === 1 ? "" : "s" }}</span
        >
      </div>
    </div>
  </div>
</template>

<style scoped>
.collection-card-wrap {
  width: 200px;
  cursor: pointer;
}
.collection-card {
  position: relative;
  width: 100%;
  border-radius: 10px;
  transition:
    transform 0.32s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.32s cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform;
}
.collection-card-wrap:hover .collection-card {
  transform: scale(1.07) translateY(-4px);
  box-shadow: 0 24px 56px rgba(0, 0, 0, 0.5);
}
.smart-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  background: rgba(20, 20, 20, 0.75);
  backdrop-filter: blur(4px);
  border: 1px solid rgba(214, 138, 52, 0.5);
  color: #d68a34;
  font-size: 10px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 999px;
}
.smart-delete {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: none;
  background: rgba(20, 20, 20, 0.75);
  backdrop-filter: blur(4px);
  color: #ccc;
  font-size: 11px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.collection-card-wrap:hover .smart-delete {
  opacity: 1;
}
.smart-delete:hover {
  color: #fca5a5;
}
.cover {
  position: relative;
  width: 100%;
  /* matches GameCard's 2:3 (Steam-vertical) ratio so collection cards stay
     uniform with regular game cards */
  aspect-ratio: 2 / 3;
  border-radius: 10px;
  overflow: hidden;
  background: #1a1a1a;
}
.cover-grid {
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 2px;
}
.cover-cell {
  background-size: cover;
  background-position: center;
  background-color: #1c1c1c;
}
.cover-cell.empty {
  background-color: #161616;
}
.card-info {
  padding: 10px 2px 0;
}
.parent-eyebrow {
  display: block;
  color: #777;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 2px;
}
.title {
  margin: 0 0 2px;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.meta-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #999;
}
</style>
