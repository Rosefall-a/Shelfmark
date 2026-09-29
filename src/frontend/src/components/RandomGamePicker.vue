<script setup lang="ts">
// "Can't decide what to play?" (#33): narrow the library by status,
// platform, genre, length and priority, then pick one. Filters are
// remembered between visits.
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRouter } from "vue-router";

import type { Game, GameStatus } from "../types/game";
import { GENRE_OPTIONS } from "../utils/genres";
import { normalizePlatformFamily, PLATFORM_OPTIONS } from "../utils/platforms";
import { activePriority, priorityLabel } from "../utils/priority";
import {
  DEFAULT_PICKER_FILTERS,
  matchesPickerFilters,
  pickRandomGame,
} from "../utils/randomPicker";
import type { PickerFilters } from "../utils/randomPicker";

const props = defineProps<{ games: Game[] }>();
const emit = defineEmits<{ close: [] }>();
const router = useRouter();

const STORAGE_KEY = "randomGamePickerFilters";
const STATUS_CHOICES: GameStatus[] = [
  "backlog",
  "playing",
  "on hold",
  "wishlist",
  "played",
  "beaten",
];

function defaultFilters(): PickerFilters {
  return {
    ...DEFAULT_PICKER_FILTERS,
    statuses: [...DEFAULT_PICKER_FILTERS.statuses],
  };
}

function loadFilters(): PickerFilters {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...defaultFilters(), ...JSON.parse(raw) } : defaultFilters();
  } catch {
    return defaultFilters();
  }
}

const filters = ref<PickerFilters>(loadFilters());
watch(
  filters,
  (value) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    } catch {
      // private mode / blocked storage: filters just aren't remembered
    }
  },
  { deep: true },
);

const platformOptions = computed(() => {
  const set = new Set<string>(PLATFORM_OPTIONS);
  props.games.forEach((g) =>
    g.platforms.forEach((p) => set.add(normalizePlatformFamily(p.platform))),
  );
  return Array.from(set).sort();
});
const genreOptions = computed(() => {
  const set = new Set<string>(GENRE_OPTIONS);
  props.games.forEach((g) => g.tags.forEach((t) => set.add(t)));
  return Array.from(set).sort();
});

const matchCount = computed(
  () =>
    props.games.filter((g) => matchesPickerFilters(g, filters.value)).length,
);

function toggleStatus(status: GameStatus) {
  const current = filters.value.statuses;
  filters.value.statuses = current.includes(status)
    ? current.filter((s) => s !== status)
    : [...current, status];
}

const maxHoursInput = computed({
  get: () =>
    filters.value.maxHours === null ? "" : String(filters.value.maxHours),
  set: (value: string) => {
    const hours = Number(value);
    filters.value.maxHours = value.trim() && hours > 0 ? hours : null;
  },
});
const maxPriorityInput = computed({
  get: () =>
    filters.value.maxPriority === null ? "" : String(filters.value.maxPriority),
  set: (value: string) => {
    filters.value.maxPriority = value ? Number(value) : null;
  },
});

const picked = ref<Game | null>(null);
const nothingMatched = ref(false);
const dialogEl = ref<HTMLElement | null>(null);

function pick() {
  picked.value = pickRandomGame(
    props.games,
    filters.value,
    Math.random,
    picked.value?.id,
  );
  nothingMatched.value = picked.value === null;
  // on a phone the filters fill the dialog and the pick, which sits just
  // above the buttons, lands below them: scroll down to it
  void nextTick(() => {
    if (dialogEl.value) dialogEl.value.scrollTop = dialogEl.value.scrollHeight;
  });
}

function resetFilters() {
  filters.value = defaultFilters();
}

function openPicked() {
  if (!picked.value) return;
  const id = picked.value.id;
  emit("close");
  void router.push(`/games/${id}`);
}

const pickedPriority = computed(() =>
  picked.value ? activePriority(picked.value) : null,
);

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") emit("close");
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <div class="ui-backdrop" @click.self="emit('close')">
    <div
      ref="dialogEl"
      class="ui-modal picker"
      role="dialog"
      aria-modal="true"
      aria-labelledby="random-picker-title"
    >
      <h3 id="random-picker-title">Pick something to play</h3>
      <p class="picker-sub">
        Narrow it down, then let the dice decide.
        <span class="match-count"
          >{{ matchCount }}
          {{ matchCount === 1 ? "game matches" : "games match" }}.</span
        >
      </p>

      <fieldset class="picker-group">
        <legend>Status</legend>
        <div class="chips">
          <button
            v-for="status in STATUS_CHOICES"
            :key="status"
            type="button"
            class="ui-chip"
            :class="{ on: filters.statuses.includes(status) }"
            :aria-pressed="filters.statuses.includes(status)"
            @click="toggleStatus(status)"
          >
            {{ status }}
          </button>
        </div>
        <small v-if="!filters.statuses.length" class="picker-hint"
          >None selected: any game that isn't finished.</small
        >
      </fieldset>

      <div class="picker-row">
        <label class="picker-field">
          <span>Platform</span>
          <select v-model="filters.platform" class="ui-field">
            <option value="all">Any platform</option>
            <option v-for="p in platformOptions" :key="p" :value="p">
              {{ p }}
            </option>
          </select>
        </label>
        <label class="picker-field">
          <span>Genre</span>
          <select v-model="filters.genre" class="ui-field">
            <option value="all">Any genre</option>
            <option v-for="g in genreOptions" :key="g" :value="g">
              {{ g }}
            </option>
          </select>
        </label>
      </div>

      <div class="picker-row">
        <label class="picker-field">
          <span>At most (hours to beat)</span>
          <input
            v-model="maxHoursInput"
            class="ui-field"
            type="number"
            min="1"
            step="1"
            placeholder="No limit"
          />
        </label>
        <label class="picker-field">
          <span>Priority</span>
          <select v-model="maxPriorityInput" class="ui-field">
            <option value="">Any, including none</option>
            <option value="1">Only 1 · Highest</option>
            <option value="2">2 or higher</option>
            <option value="3">3 or higher</option>
            <option value="4">4 or higher</option>
            <option value="5">Any set priority</option>
          </select>
        </label>
      </div>

      <label v-if="filters.maxHours !== null" class="picker-check">
        <input v-model="filters.includeUnknownLength" type="checkbox" />
        Include games with no known length
      </label>
      <label class="picker-check">
        <input v-model="filters.weightByPriority" type="checkbox" />
        Favour higher-priority games
      </label>

      <!-- the live region stays in the page so each new pick is announced -->
      <div aria-live="polite">
        <div v-if="picked" class="picked">
          <img :src="picked.coverImageUrl" alt="" class="picked-cover" />
          <div class="picked-info">
            <strong class="picked-title">{{ picked.title }}</strong>
            <span class="picked-meta">
              {{ picked.status }}
              <template v-if="picked.platforms[0]">
                · {{ picked.platforms[0].platform }}</template
              >
              <template v-if="picked.timeToBeatHours !== null">
                · ~{{ picked.timeToBeatHours }}h</template
              >
              <template v-if="pickedPriority !== null">
                · priority {{ priorityLabel(pickedPriority) }}</template
              >
            </span>
            <button
              type="button"
              class="ui-btn ui-btn-primary ui-btn-sm"
              @click="openPicked"
            >
              Open game
            </button>
          </div>
        </div>
        <p v-else-if="nothingMatched" class="ui-state error">
          No games match these filters. Loosen one and try again.
        </p>
      </div>

      <div class="ui-modal-actions picker-actions">
        <button type="button" class="ui-btn ui-btn-ghost" @click="resetFilters">
          Reset
        </button>
        <button
          type="button"
          class="ui-btn ui-btn-ghost"
          @click="emit('close')"
        >
          Close
        </button>
        <button
          type="button"
          class="ui-btn ui-btn-primary"
          :disabled="matchCount === 0"
          @click="pick"
        >
          {{ picked ? "Pick again" : "Pick a game" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.picker {
  max-width: 520px;
}
.picker-sub {
  margin: 0 0 14px;
  color: var(--ui-dim);
  font-size: 0.85rem;
}
.match-count {
  color: var(--ui-faint);
}
.picker-group {
  border: none;
  margin: 0 0 12px;
  padding: 0;
}
.picker-group legend,
.picker-field span {
  display: block;
  margin-bottom: 6px;
  color: var(--ui-dim);
  font-size: 0.78rem;
  font-weight: 700;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chips .ui-chip {
  text-transform: capitalize;
}
.picker-hint {
  display: block;
  margin-top: 6px;
  color: var(--ui-faint);
  font-size: 0.75rem;
}
.picker-row {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
.picker-field {
  flex: 1;
  min-width: 0;
}
.picker-field .ui-field {
  width: 100%;
}
.picker-check {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--ui-dim);
  font-size: 0.82rem;
}
.picked {
  display: flex;
  gap: 14px;
  align-items: center;
  margin: 14px 0 6px;
  padding: 12px;
  background: var(--ui-surface);
  border: 1px solid var(--ui-accent-line);
  border-radius: var(--ui-radius-card);
}
.picked-cover {
  width: 64px;
  height: 96px;
  object-fit: cover;
  border-radius: 6px;
  background: var(--ui-surface-2);
  flex-shrink: 0;
}
.picked-info {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  min-width: 0;
}
.picked-title {
  font-size: 1rem;
  overflow-wrap: anywhere;
}
.picked-meta {
  color: var(--ui-dim);
  font-size: 0.8rem;
  text-transform: capitalize;
}
/* the buttons stay in view while the filters scroll on a short screen */
.picker-actions {
  position: sticky;
  bottom: -22px;
  margin: 6px -22px -22px;
  padding: 12px 22px 22px;
  background: var(--ui-popover);
}
@media (max-width: 520px) {
  .picker-row {
    flex-direction: column;
  }
}
</style>
