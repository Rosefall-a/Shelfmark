<script setup lang="ts">
import { ref } from "vue";
import type { MediaItem } from "../services/media";
import type { Achievement } from "../types/game";
import type { GameProfile } from "../services/gameProfiles";

const props = defineProps<{
  item: MediaItem;
  achievements: Achievement[];
  showGameTitle?: boolean;
  // only passed when the game has "Track multiple accounts" enabled, lets
  // an already-uploaded screenshot be moved to a different account after
  // the fact instead of only being assignable at upload time
  profiles?: GameProfile[];
}>();

const emit = defineEmits<{
  delete: [item: MediaItem];
  save: [
    item: MediaItem,
    tags: string[],
    note: string | null,
    linkedAchievementId: string | null,
    profileId: string | null,
  ];
  preview: [item: MediaItem];
  rename: [item: MediaItem];
}>();

const expanded = ref(false);
const tagsInput = ref(props.item.tags.join(", "));
const noteInput = ref(props.item.note ?? "");
const linkedAchievement = ref(props.item.linked_achievement_id ?? "");
const profileSelection = ref(props.item.profile_id ?? "");
const saving = ref(false);

function toggleExpanded() {
  expanded.value = !expanded.value;
}

async function save() {
  saving.value = true;
  try {
    const tags = tagsInput.value
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    emit(
      "save",
      props.item,
      tags,
      noteInput.value.trim() || null,
      linkedAchievement.value || null,
      profileSelection.value || null,
    );
  } finally {
    saving.value = false;
  }
}

function linkedAchievementName(): string | null {
  if (!props.item.linked_achievement_id) return null;
  return (
    props.achievements.find((a) => a.id === props.item.linked_achievement_id)
      ?.name ?? null
  );
}
</script>

<template>
  <div class="media-tile" :class="{ expanded }">
    <div
      class="media-preview"
      @click="item.kind === 'screenshot' ? emit('preview', item) : undefined"
    >
      <img v-if="item.kind === 'screenshot'" :src="item.url" alt="" />
      <video
        v-else-if="item.kind === 'clip'"
        :src="item.url"
        controls
        preload="metadata"
      ></video>
      <div v-else class="soundtrack-preview">
        <svg
          viewBox="0 0 24 24"
          width="22"
          height="22"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M9 18V5l12-2v13" />
          <circle cx="6" cy="18" r="3" />
          <circle cx="18" cy="16" r="3" />
        </svg>
        <audio :src="item.url" controls preload="metadata"></audio>
      </div>
      <button
        type="button"
        class="tile-remove"
        title="Delete"
        @click.stop="emit('delete', item)"
      >
        ✕
      </button>
    </div>

    <div v-if="showGameTitle && item.game_title" class="media-game-title">
      {{ item.game_title }}
    </div>

    <div class="media-filename">{{ item.filename.split("_").slice(1).join("_") || item.filename }}</div>
    <div class="media-meta-row">
      <div class="media-tags">
        <span
          v-if="item.profile_id && profiles"
          class="tag-chip account-tag-chip"
        >
          {{
            profiles.find((p) => p.id === item.profile_id)?.name ??
            "Unknown account"
          }}
        </span>
        <span v-for="tag in item.tags" :key="tag" class="tag-chip">{{
          tag
        }}</span>
        <span v-if="linkedAchievementName()" class="tag-chip achievement-chip">
          <svg
            viewBox="0 0 24 24"
            width="11"
            height="11"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M8 4h8v5a4 4 0 0 1-8 0z" />
            <path d="M8 4H5a2 2 0 0 0 0 4h1.5M16 4h3a2 2 0 0 1 0 4h-1.5" />
            <path d="M12 13v3" />
            <path d="M9 20h6" />
            <path d="M10 16.5h4l.8 3.5H9.2z" />
          </svg>
          {{ linkedAchievementName() }}
        </span>
      </div>
      <div class="media-actions">
        <button type="button" class="edit-toggle" @click="toggleExpanded">{{ expanded ? "Close" : "Edit" }}</button>
        <button type="button" class="edit-toggle" @click="emit('rename', item)">Rename</button>
      </div>
    </div>

    <div v-if="expanded" class="media-edit-panel">
      <label class="field">
        <span>Tags (comma-separated)</span>
        <input
          v-model="tagsInput"
          type="text"
          placeholder="boss fight, funny, glitch"
        />
      </label>
      <label class="field">
        <span>Note</span>
        <textarea
          v-model="noteInput"
          rows="2"
          placeholder="What's happening here?"
        ></textarea>
      </label>
      <label v-if="achievements.length" class="field">
        <span>Link to achievement</span>
        <select v-model="linkedAchievement">
          <option value="">None</option>
          <option v-for="a in achievements" :key="a.id" :value="a.id">
            {{ a.name }}
          </option>
        </select>
      </label>
      <label v-if="profiles && profiles.length" class="field">
        <span>Account</span>
        <select v-model="profileSelection">
          <option value="">None</option>
          <option v-for="p in profiles" :key="p.id" :value="p.id">
            {{ p.name }}
          </option>
        </select>
      </label>
      <button
        type="button"
        class="primary-button"
        :disabled="saving"
        @click="save"
      >
        {{ saving ? "Saving…" : "Save" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.media-tile {
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.media-preview {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #000;
  cursor: pointer;
}
.media-preview img,
.media-preview video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.soundtrack-preview {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #d68a34;
  padding: 10px;
}
.soundtrack-preview audio {
  width: 100%;
  max-width: 100%;
}
.tile-remove {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  cursor: pointer;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.media-tile:hover .tile-remove {
  opacity: 1;
}
.media-game-title {
  padding: 6px 8px 0;
  color: #999;
  font-size: 0.72rem;
  font-weight: 600;
}
.media-filename { padding: 8px 8px 0; color: #fff; font-size: .78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.media-meta-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
  padding: 8px;
}
.media-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
  min-width: 0;
}
.tag-chip {
  background: rgba(255, 255, 255, 0.08);
  color: #ccc;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.68rem;
}
.achievement-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: rgba(214, 138, 52, 0.16);
  color: #d68a34;
}
.achievement-chip svg {
  flex-shrink: 0;
  opacity: 0.85;
}
.account-tag-chip {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  font-weight: 700;
}
.media-actions { display: flex; gap: 8px; flex-shrink: 0; }
.edit-toggle {
  background: none;
  border: none;
  color: #999;
  font-size: 0.72rem;
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
}
.edit-toggle:hover {
  color: #fff;
}
.media-edit-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 8px 10px;
  border-top: 1px solid #232323;
  margin-top: 2px;
  padding-top: 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 0.72rem;
  color: #ccc;
}
.field input,
.field textarea,
.field select {
  background: #1a1a1a;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  color: #fff;
  padding: 6px 8px;
  font: inherit;
  font-size: 0.76rem;
  resize: vertical;
}
.primary-button {
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  align-self: flex-start;
}
.primary-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
