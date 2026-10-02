<script setup lang="ts">
// The Lists equivalent of CollectionCard.vue — same 2x2 poster-collage
// tile, same card shape/hover, so a list reads as "the same kind of
// thing" as a game collection instead of a different feature bolted on.
import { computed } from "vue";
import type { MediaListSummary } from "../services/mediaExtras";
import { blurOnLeave } from "../utils/blurOnLeave";

const props = defineProps<{
  list: MediaListSummary;
  // the page is in "My order" with nothing filtered: show the move controls
  reorderable?: boolean;
  canMoveEarlier?: boolean;
  canMoveLater?: boolean;
  dragOver?: boolean;
}>();

const emit = defineEmits<{
  open: [id: string];
  delete: [id: string];
  edit: [id: string];
  pin: [id: string];
  move: [id: string, direction: -1 | 1];
  dragstart: [id: string];
  dragover: [id: string];
  drop: [id: string];
  dragend: [];
}>();

const covers = computed(() => props.list.previewPosters.slice(0, 4));
const emptySlots = computed(() => Math.max(0, 4 - covers.value.length));
</script>

<template>
  <div
    class="collection-card-wrap"
    :class="{ 'drop-target': dragOver }"
    :draggable="reorderable"
    @click="emit('open', list.id)"
    @dragstart="emit('dragstart', list.id)"
    @dragover.prevent="emit('dragover', list.id)"
    @drop.prevent="emit('drop', list.id)"
    @dragend="emit('dragend')"
    @mouseleave="blurOnLeave"
  >
    <div class="collection-card">
      <div class="cover">
        <div class="cover-grid">
          <div
            v-for="(cover, i) in covers"
            :key="i"
            class="cover-cell"
            :style="cover ? { backgroundImage: `url(${cover})` } : {}"
          ></div>
          <div
            v-for="i in emptySlots"
            :key="`empty-${i}`"
            class="cover-cell empty"
          ></div>
        </div>
        <span
          v-if="list.isSmart"
          class="smart-badge"
          title="Fills itself from a filter"
          >{{ list.isSystem ? "Auto" : "Smart" }}</span
        >
        <span v-if="list.pinned" class="pin-badge" title="Pinned">
          <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
            <path
              d="M9 3h6l-1 6 3 3v2h-4v6l-1 1-1-1v-6H7v-2l3-3z"
              fill="currentColor"
            />
          </svg>
        </span>
        <div class="card-actions">
          <button
            type="button"
            :title="list.pinned ? 'Unpin this list' : 'Pin this list'"
            :class="{ on: list.pinned }"
            @click.stop="emit('pin', list.id)"
          >
            <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
              <path
                d="M9 3h6l-1 6 3 3v2h-4v6l-1 1-1-1v-6H7v-2l3-3z"
                fill="currentColor"
              />
            </svg>
          </button>
          <template v-if="reorderable">
            <button
              v-if="canMoveEarlier"
              type="button"
              title="Move earlier"
              @click.stop="emit('move', list.id, -1)"
            >
              &#9664;
            </button>
            <button
              v-if="canMoveLater"
              type="button"
              title="Move later"
              @click.stop="emit('move', list.id, 1)"
            >
              &#9654;
            </button>
          </template>
          <template v-if="!list.isSystem">
            <button
              type="button"
              title="Edit this list"
              @click.stop="emit('edit', list.id)"
            >
              ✎
            </button>
            <button
              type="button"
              title="Delete this list"
              @click.stop="emit('delete', list.id)"
            >
              ✕
            </button>
          </template>
        </div>
      </div>
    </div>

    <div class="card-info">
      <h3 class="title">{{ list.name }}</h3>
      <div class="meta-row">
        <span class="status"
          >{{ list.itemCount }} title{{ list.itemCount === 1 ? "" : "s" }}</span
        >
        <span v-if="list.description" class="desc" :title="list.description">{{
          list.description
        }}</span>
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
.card-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 6px;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.collection-card-wrap:hover .card-actions,
.collection-card-wrap:focus-within .card-actions {
  opacity: 1;
}
/* no hover on touch screens: keep the actions reachable */
@media (hover: none) {
  .card-actions {
    opacity: 1;
  }
}
.card-actions button {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: none;
  background: rgba(20, 20, 20, 0.78);
  backdrop-filter: blur(4px);
  color: #ccc;
  font-size: 11px;
  cursor: pointer;
}
.card-actions button:hover,
.card-actions button.on {
  color: #d68a34;
}
.pin-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(20, 20, 20, 0.8);
  backdrop-filter: blur(4px);
  color: #d68a34;
}
.collection-card-wrap[draggable="true"] {
  cursor: grab;
}
.collection-card-wrap.drop-target .collection-card {
  outline: 2px dashed #d68a34;
  outline-offset: 3px;
}
.card-actions button[title^="Delete"]:hover {
  color: #e57373;
}
.desc {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #666;
}
.cover {
  position: relative;
  width: 100%;
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
.smart-badge {
  position: absolute;
  left: 8px;
  bottom: 8px;
  z-index: 2;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(20, 20, 20, 0.8);
  backdrop-filter: blur(4px);
  color: #d68a34;
}
.card-info {
  padding: 10px 2px 0;
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
  color: #9c9c9c;
}
</style>
