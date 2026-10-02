<script setup lang="ts">
import {
  ref,
  computed,
  reactive,
  watch,
  onMounted,
  onBeforeUnmount,
} from "vue";
import { useRouter } from "vue-router";
import CheckIcon from "../CheckIcon.vue";
import MediaTopBar from "../MediaTopBar.vue";
import SegmentedTabs from "../SegmentedTabs.vue";
import type { SegmentOption } from "../SegmentedTabs.vue";
import { preferences } from "../../state/preferences";
import { matchesFilters } from "../../utils/libraryFilters";
import type { LibraryFilters } from "../../utils/libraryFilters";
import { blurOnLeave } from "../../utils/blurOnLeave";
import {
  STATUS_BUCKETS,
  statusBucket,
  statusBucketLabel,
  bucketToReal,
} from "../../utils/mediaStatus";

// A normalized view-model so this one component can drive Movies, TV
// Shows, and Anime without knowing about seasons, episode tables, or any
// other per-entity detail — each Library.vue page adapts its real
// entities into this shape and reacts to the events below.
export interface LibraryCardVM {
  id: string;
  title: string;
  poster: string | null;
  status: string;
  favorite: boolean;
  score: number | null;
  personalRank: number | null;
  note: string | null;
  genres: string[];
  isEpisodic: boolean;
  watched: number;
  total: number | null;
  progressLabel: string;
  canAdvance: boolean;
  // No real "currently airing" data source is wired up for any of the
  // three entities yet (would need extending the TVmaze/AniList/TMDB
  // clients) — the field and its always-rendered-but-invisible tag stay
  // here so the capability and layout are ready the moment that data
  // exists, matching the mockup exactly rather than dropping the feature.
  airing?: boolean;
  // The real sub-format (e.g. "TV", "Movie", "OVA") when the entity
  // carries one — currently only Anime does (from AniList/Jikan). Falls
  // back to the generic per-kind typeLabel below when absent.
  format?: string | null;
  // Release/first-air year, shown right under the format label — null
  // when the underlying date is unknown.
  releaseYear: string | null;
  // when it was added to the library (ms), for sorting by recently added
  addedAt?: number | null;
  // other spellings of the title, so search finds any of them
  altTitles?: string[];
}

export interface SearchResultVM {
  title: string;
  poster: string | null;
  description: string | null;
  episodeTotal: number | null;
  releaseYear: string | null;
}

export interface QuickAddForm {
  status: string;
  watched: number;
  seen: boolean;
  score: number | null;
  startDate: string | null;
  endDate: string | null;
}

export interface EditForm {
  status: string;
  score: number | null;
  watched: number;
  totalEpisodes: number | null;
  seen: boolean;
}

// The pill/tab labels shown everywhere in this view come from the shared
// 5-value bucket set in utils/mediaStatus.ts — the pill's CSS modifier
// class is just the bucket key itself (see .pill.watching etc below).
const STATUSES = STATUS_BUCKETS;

const props = defineProps<{
  kind: "movie" | "tv" | "anime";
  addLabel: string;
  items: LibraryCardVM[];
  total: number;
  statusCounts: Record<string, number>;
  loading: boolean;
  error: string | null;
  detailRoute: (id: string) => string;
  search: (
    query: string,
  ) => Promise<{ results: SearchResultVM[]; providerErrors: string[] }>;
  createFromResult: (
    result: SearchResultVM,
    form: QuickAddForm,
  ) => Promise<void>;
}>();

const emit = defineEmits<{
  (e: "toggle-favorite", id: string): void;
  (e: "advance-episode", id: string): void;
  (e: "save-note", id: string, note: string | null): void;
  (e: "save-edit", id: string, form: EditForm): void;
  (e: "bulk-set-status", ids: string[], status: string): void;
  (e: "bulk-favorite", ids: string[]): void;
  (e: "bulk-delete", ids: string[]): void;
  (e: "search", query: string): void;
  (e: "load-more"): void;
}>();

const router = useRouter();

function maybeLoadMore() {
  if (
    layout.value === "board" ||
    props.loading ||
    props.items.length >= props.total
  )
    return;
  if (
    window.innerHeight + window.scrollY >=
    document.documentElement.scrollHeight - 1000
  ) {
    emit("load-more");
  }
}
onMounted(() =>
  window.addEventListener("scroll", maybeLoadMore, { passive: true }),
);
onBeforeUnmount(() => window.removeEventListener("scroll", maybeLoadMore));
watch(
  () => props.items.length,
  () => requestAnimationFrame(maybeLoadMore),
);

// The mockup's per-item "type" field (TV/Movie/OVA/Series/Anthology) has
// no real per-item equivalent — none of the three entities carry a
// sub-format string — so this renders a static per-page label instead,
// keeping the same element in the same place rather than dropping it.
const typeLabel = computed(() => {
  if (props.kind === "movie") return "Movie";
  if (props.kind === "tv") return "TV Series";
  return "Anime";
});

const LAYOUT_OPTIONS: SegmentOption[] = [
  {
    value: "list",
    label: "List",
    icon: '<line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />',
  },
  {
    value: "shelf",
    label: "Shelf",
    icon: '<rect x="3" y="3" width="7" height="18" rx="1" /><rect x="14" y="3" width="7" height="10" rx="1" />',
  },
  {
    value: "board",
    label: "Board",
    icon: '<rect x="3" y="4" width="6" height="16" rx="1" /><rect x="11" y="4" width="6" height="10" rx="1" /><rect x="19" y="4" width="2" height="7" rx="1" />',
  },
];

// ---- layout + filters ----
// List/Shelf/Board is a persisted, remembered choice — same idea as the
// Shelf card-size toggle below, so switching kinds or reloading doesn't
// reset it back to List every time. Stats is deliberately kept out of
// this persisted value: it's a separate lens on the data, not another
// layout choice, so opening it never overwrites what List/Shelf/Board
// was last set to, and leaving it returns to that remembered layout.
const layout = ref<"list" | "shelf" | "board">(
  (localStorage.getItem("libraryLayout") as "list" | "shelf" | "board") ||
    preferences.value.library_default_layout,
);
// the server default arrives a moment after the first render
watch(
  () => preferences.value.library_default_layout,
  (v) => {
    if (!localStorage.getItem("libraryLayout")) layout.value = v;
  },
);
watch(layout, (v) => localStorage.setItem("libraryLayout", v));
// Card size for the Shelf grid, same idea as Games' S/M/L density toggle
// — persisted so it doesn't reset every visit.
const shelfCardSize = ref<"compact" | "cozy" | "large">(
  (localStorage.getItem("libraryShelfCardSize") as
    "compact" | "cozy" | "large") || "cozy",
);
watch(shelfCardSize, (v) => localStorage.setItem("libraryShelfCardSize", v));
const shelfCardMinWidth = computed(() => {
  if (shelfCardSize.value === "compact") return "150px";
  if (shelfCardSize.value === "large") return "260px";
  return "200px";
});
// Board's cards are fixed-width flex items (each status is its own
// horizontally-scrolling row) rather than a minmax grid, so the same S/M/L
// preference maps to an explicit width instead.
const boardCardWidth = computed(() => {
  if (shelfCardSize.value === "compact") return "150px";
  if (shelfCardSize.value === "large") return "260px";
  return "196px";
});
const activeStatus = ref<string>("all");
const searchQuery = ref("");
let searchTimer: ReturnType<typeof setTimeout> | null = null;
watch(searchQuery, (query) => {
  if (searchTimer !== null) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => emit("search", query.trim()), 250);
});
type SortKey =
  | "rank"
  | "score"
  | "title"
  | "title_desc"
  | "added"
  | "year_new"
  | "year_old"
  | "progress";
const SORT_KEYS: SortKey[] = [
  "rank",
  "score",
  "title",
  "title_desc",
  "added",
  "year_new",
  "year_old",
  "progress",
];
function savedSort(): SortKey {
  try {
    const v = localStorage.getItem(`librarySort:${props.kind}`) as SortKey;
    return SORT_KEYS.includes(v) ? v : "rank";
  } catch {
    return "rank";
  }
}
const sortKey = ref<SortKey>(savedSort());
watch(sortKey, (v) => {
  try {
    localStorage.setItem(`librarySort:${props.kind}`, v);
  } catch {
    /* remembering the sort is optional */
  }
});
const selectedGenres = ref<Set<string>>(new Set());
const genreMatchAll = ref(false);
const selectedFormats = ref<Set<string>>(new Set());
const onlyFavorites = ref(false);
const onlyUnrated = ref(false);
const onlyWithNote = ref(false);
const minScore = ref<number | null>(null);
// kept as text: v-model on a number input would hand back a Number
const yearFrom = ref("");
const yearTo = ref("");
const filtersOpen = ref(false);
const SCORE_OPTIONS = [6, 7, 8, 9];

const allGenres = computed(() => {
  const set = new Set<string>();
  props.items.forEach((it) => it.genres.forEach((g) => set.add(g)));
  return [...set].sort();
});

const allFormats = computed(() => {
  const set = new Set<string>();
  props.items.forEach((it) => it.format && set.add(it.format));
  return [...set].sort();
});

// the number of separate filters in use, shown on the Filters button
const activeFilterCount = computed(
  () =>
    [
      selectedGenres.value.size > 0,
      selectedFormats.value.size > 0,
      onlyFavorites.value,
      onlyUnrated.value,
      onlyWithNote.value,
      minScore.value !== null,
      yearFrom.value.trim() !== "" || yearTo.value.trim() !== "",
    ].filter(Boolean).length,
);
function clearFilters() {
  selectedGenres.value = new Set();
  selectedFormats.value = new Set();
  genreMatchAll.value = false;
  onlyFavorites.value = false;
  onlyUnrated.value = false;
  onlyWithNote.value = false;
  minScore.value = null;
  yearFrom.value = "";
  yearTo.value = "";
}

// Every filter except the status tab (the Board shows the tabs as rows).
const filters = computed<LibraryFilters>(() => ({
  search: searchQuery.value,
  genres: [...selectedGenres.value],
  genreMatchAll: genreMatchAll.value,
  formats: [...selectedFormats.value],
  onlyFavorites: onlyFavorites.value,
  onlyUnrated: onlyUnrated.value,
  onlyWithNote: onlyWithNote.value,
  minScore: minScore.value,
  yearFrom: yearFrom.value,
  yearTo: yearTo.value,
}));
function matchesFilterState(it: LibraryCardVM): boolean {
  return matchesFilters(it, filters.value);
}

// Rank is generated, not manually assigned — a leaderboard position among
// everything that's been rated, highest score first. Nothing without a
// score participates, so there's no ranking to show for it yet.
const rankByItemId = computed(() => {
  const ranked = props.items
    .filter((it) => it.score !== null)
    .slice()
    .sort((a, b) => (b.score as number) - (a.score as number));
  const map = new Map<string, number>();
  ranked.forEach((it, idx) => map.set(it.id, idx + 1));
  return map;
});
function computedRank(it: LibraryCardVM): number | null {
  return rankByItemId.value.get(it.id) ?? null;
}

const statusCounts = computed<Record<string, number>>(() => ({
  all: props.total,
  ...props.statusCounts,
}));

function progressPct(it: LibraryCardVM): number {
  if (!it.isEpisodic) return it.watched > 0 ? 100 : 0;
  return it.total ? (it.watched / it.total) * 100 : 0;
}

const filteredItems = computed(() => {
  let list = props.items;
  if (activeStatus.value !== "all") {
    list = list.filter((it) => statusBucket(it.status) === activeStatus.value);
  }
  list = list.filter(matchesFilterState);
  const sorted = [...list];
  const year = (it: LibraryCardVM) =>
    it.releaseYear ? parseInt(it.releaseYear, 10) : null;
  // titles missing the sorted value always go last, whichever direction
  const byNullable = (
    value: (it: LibraryCardVM) => number | null,
    direction: 1 | -1,
  ) =>
    sorted.sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      if (va === null && vb === null) return a.title.localeCompare(b.title);
      if (va === null) return 1;
      if (vb === null) return -1;
      return (va - vb) * direction || a.title.localeCompare(b.title);
    });
  if (sortKey.value === "title") {
    sorted.sort((a, b) => a.title.localeCompare(b.title));
  } else if (sortKey.value === "title_desc") {
    sorted.sort((a, b) => b.title.localeCompare(a.title));
  } else if (sortKey.value === "progress") {
    sorted.sort((a, b) => progressPct(b) - progressPct(a));
  } else if (sortKey.value === "score") {
    byNullable((it) => it.score, -1);
  } else if (sortKey.value === "added") {
    byNullable((it) => it.addedAt ?? null, -1);
  } else if (sortKey.value === "year_new") {
    byNullable(year, -1);
  } else if (sortKey.value === "year_old") {
    byNullable(year, 1);
  } else {
    sorted.sort((a, b) => {
      const ra = computedRank(a) ?? 999999;
      const rb = computedRank(b) ?? 999999;
      return ra - rb || a.title.localeCompare(b.title);
    });
  }
  return sorted;
});

const boardPageStarts = reactive<Record<string, number>>({});
const boardViewportWidth = ref(0);
const boardContainer = ref<HTMLElement | null>(null);
const boardVisibleCount = computed(() => {
  const cardWidth =
    shelfCardSize.value === "compact"
      ? 150
      : shelfCardSize.value === "large"
        ? 260
        : 196;
  return Math.max(
    1,
    Math.floor((boardViewportWidth.value + 14) / (cardWidth + 14)) || 1,
  );
});
function resetBoardPages() {
  Object.keys(boardPageStarts).forEach((key) => delete boardPageStarts[key]);
}
function moveBoard(status: string, direction: -1 | 1, available: number) {
  const current = boardPageStarts[status] ?? 0;
  if (direction < 0) {
    boardPageStarts[status] = Math.max(0, current - available);
    return;
  }
  if (
    current + available >= props.items.length &&
    props.items.length < props.total
  ) {
    emit("load-more");
  }
  boardPageStarts[status] = current + available;
}
watch([activeStatus, filters], resetBoardPages);
watch(boardViewportWidth, resetBoardPages);
function updateBoardViewport() {
  boardViewportWidth.value = boardContainer.value?.clientWidth ?? 0;
}
onMounted(updateBoardViewport);
watch(shelfCardSize, () => requestAnimationFrame(updateBoardViewport));
window.addEventListener("resize", updateBoardViewport);
onBeforeUnmount(() =>
  window.removeEventListener("resize", updateBoardViewport),
);

const boardGroups = computed(() => {
  const statuses =
    activeStatus.value === "all"
      ? STATUSES
      : STATUSES.filter((s) => s.key === activeStatus.value);
  return statuses
    .map((s) => {
      let rowItems = props.items.filter(
        (it) => statusBucket(it.status) === s.key,
      );
      rowItems = rowItems.filter(matchesFilterState);
      const start = boardPageStarts[s.key] ?? 0;
      return {
        status: s,
        rowItems,
        visibleItems: rowItems.slice(start, start + boardVisibleCount.value),
        start,
      };
    })
    .filter((g) => g.rowItems.length > 0);
});

function toggleFormat(f: string) {
  const next = new Set(selectedFormats.value);
  if (next.has(f)) next.delete(f);
  else next.add(f);
  selectedFormats.value = next;
}

function toggleGenre(g: string) {
  const next = new Set(selectedGenres.value);
  if (next.has(g)) next.delete(g);
  else next.add(g);
  selectedGenres.value = next;
}

// ---- select / bulk edit ----
const selectMode = ref(false);
const selectedIds = ref<Set<string>>(new Set());
const bulkStatusValue = ref("");

function toggleSelectMode() {
  selectMode.value = !selectMode.value;
  if (!selectMode.value) selectedIds.value = new Set();
}
function toggleSelectItem(id: string) {
  const next = new Set(selectedIds.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selectedIds.value = next;
}
function clearSelection() {
  selectedIds.value = new Set();
}
function bulkApplyStatus() {
  if (!bulkStatusValue.value) return;
  emit(
    "bulk-set-status",
    [...selectedIds.value],
    bucketToReal(bulkStatusValue.value),
  );
  bulkStatusValue.value = "";
}
function bulkFavorite() {
  emit("bulk-favorite", [...selectedIds.value]);
}
function bulkDelete() {
  emit("bulk-delete", [...selectedIds.value]);
  selectedIds.value = new Set();
}

function handleCardClick(it: LibraryCardVM) {
  if (selectMode.value) {
    toggleSelectItem(it.id);
    return;
  }
  router.push(props.detailRoute(it.id));
}

// ---- notes modal ----
const noteOpen = ref(false);
const noteTargetId = ref<string | null>(null);
const noteText = ref("");
function openNote(it: LibraryCardVM) {
  noteTargetId.value = it.id;
  noteText.value = it.note ?? "";
  noteOpen.value = true;
}
function closeNote() {
  noteOpen.value = false;
  noteTargetId.value = null;
}
function saveNote() {
  if (!noteTargetId.value) return;
  emit("save-note", noteTargetId.value, noteText.value.trim() || null);
  closeNote();
}

// ---- episode advance ----
// No cap on how far watched can go past the known total — metadata's
// episode count is often wrong or stale, and a rewatch can outrun it too.
function advanceEpisode(it: LibraryCardVM) {
  if (!it.canAdvance) return;
  emit("advance-episode", it.id);
  const nowWatched = it.watched + 1;
  const justFinished = it.total !== null && nowWatched >= it.total;
  if (justFinished && it.score === null) {
    openFinishRating(it, statusBucket(it.status), nowWatched, it.total);
  }
}

// ---- "you finished it" rating prompt ----
// Only appears once something is actually complete (episodes caught up to
// the known total, or the status is edited to Completed) rather than on
// every single episode tick — a rating is worth asking for once, not
// nagging for every checkbox click.
const finishOpen = ref(false);
const finishTargetId = ref<string | null>(null);
const finishTitle = ref("");
const finishPoster = ref<string | null>(null);
const finishScore = ref<number | null>(null);
const finishBucket = ref("completed");
const finishWatched = ref(0);
const finishTotalEpisodes = ref<number | null>(null);
function openFinishRating(
  it: LibraryCardVM,
  bucket: string,
  watched: number,
  totalEpisodes: number | null,
) {
  finishTargetId.value = it.id;
  finishTitle.value = it.title;
  finishPoster.value = it.poster;
  finishScore.value = null;
  finishBucket.value = bucket;
  finishWatched.value = watched;
  finishTotalEpisodes.value = totalEpisodes;
  finishOpen.value = true;
}
function closeFinish() {
  finishOpen.value = false;
  finishTargetId.value = null;
}
function stepFinishScore(delta: number) {
  const base = finishScore.value ?? 0;
  finishScore.value = Math.max(
    0,
    Math.min(10, Math.round((base + delta) * 10) / 10),
  );
}
function finishSave() {
  if (!finishTargetId.value) return;
  emit("save-edit", finishTargetId.value, {
    status: bucketToReal(finishBucket.value),
    score: finishScore.value,
    watched: finishWatched.value,
    totalEpisodes: finishTotalEpisodes.value,
    seen: finishWatched.value > 0,
  });
  closeFinish();
}

// ---- small edit modal ----
const editOpen = ref(false);
const editTargetId = ref<string | null>(null);
const editForm = reactive<EditForm>({
  status: "plan",
  score: null,
  watched: 0,
  totalEpisodes: null,
  seen: false,
});
function openEdit(it: LibraryCardVM) {
  editTargetId.value = it.id;
  editForm.status = statusBucket(it.status);
  editForm.score = it.score;
  editForm.watched = it.watched;
  editForm.totalEpisodes = it.total;
  editForm.seen = it.watched > 0;
  editOpen.value = true;
}
function closeEdit() {
  editOpen.value = false;
  editTargetId.value = null;
}
function saveEdit() {
  if (!editTargetId.value) return;
  const target = props.items.find((i) => i.id === editTargetId.value);
  const wasCompleted = target
    ? statusBucket(target.status) === "completed"
    : false;
  const justCompleted = editForm.status === "completed" && !wasCompleted;
  const id = editTargetId.value;
  const totalEpisodes = editForm.totalEpisodes;
  // Setting status to Completed catches episodes watched up to the known
  // total automatically — no reason to make someone type in the number
  // themselves when the app already knows it.
  const watched =
    editForm.status === "completed" && totalEpisodes !== null
      ? totalEpisodes
      : editForm.watched;
  const scoreAlreadySet = editForm.score !== null;
  emit("save-edit", id, {
    ...editForm,
    watched,
    status: bucketToReal(editForm.status),
  });
  closeEdit();
  if (target && justCompleted && !scoreAlreadySet) {
    openFinishRating(target, "completed", watched, totalEpisodes);
  }
}

// ---- quick add (two-step: search -> fill-out form) ----
const quickAddOpen = ref(false);
const quickAddStep = ref<"search" | "form">("search");
const quickAddQuery = ref("");
const quickAddResults = ref<SearchResultVM[]>([]);
const quickAddProviderErrors = ref<string[]>([]);
const quickAddSearching = ref(false);
const quickAddPick = ref<SearchResultVM | null>(null);
const quickAddForm = reactive<QuickAddForm>({
  status: "plan",
  watched: 0,
  seen: false,
  score: null,
  startDate: null,
  endDate: null,
});
const quickAddSaving = ref(false);

function openQuickAdd() {
  quickAddStep.value = "search";
  quickAddQuery.value = "";
  quickAddResults.value = [];
  quickAddProviderErrors.value = [];
  quickAddOpen.value = true;
}
function onEscape(e: KeyboardEvent) {
  if (e.key === "Escape" && quickAddOpen.value) closeQuickAdd();
}
onMounted(() => window.addEventListener("keydown", onEscape));
onBeforeUnmount(() => window.removeEventListener("keydown", onEscape));
function closeQuickAdd() {
  quickAddOpen.value = false;
  quickAddPick.value = null;
}
async function runQuickAddSearch() {
  if (!quickAddQuery.value.trim()) {
    quickAddResults.value = [];
    return;
  }
  quickAddSearching.value = true;
  try {
    const { results, providerErrors } = await props.search(quickAddQuery.value);
    quickAddResults.value = results;
    quickAddProviderErrors.value = providerErrors;
  } finally {
    quickAddSearching.value = false;
  }
}
function pickQuickAddResult(result: SearchResultVM) {
  quickAddPick.value = result;
  quickAddForm.status = "plan";
  quickAddForm.watched = 0;
  quickAddForm.seen = false;
  quickAddForm.score = null;
  quickAddForm.startDate = null;
  quickAddForm.endDate = null;
  quickAddStep.value = "form";
}
function quickAddBackToSearch() {
  quickAddStep.value = "search";
}
// The max attribute alone doesn't stop someone from typing past it — a
// fresh add has no legitimate reason to start above the known total
// (unlike the ongoing rewatch case, where advancing past it is allowed).
function clampQuickAddWatched() {
  const max = quickAddPick.value?.episodeTotal;
  if (max !== null && max !== undefined && quickAddForm.watched > max) {
    quickAddForm.watched = max;
  }
}
async function saveQuickAdd() {
  if (!quickAddPick.value) return;
  quickAddSaving.value = true;
  // Same as the edit modal: picking Completed catches episodes watched up
  // to the known total automatically instead of leaving it at 0.
  const watched =
    quickAddForm.status === "completed" &&
    quickAddPick.value.episodeTotal !== null
      ? quickAddPick.value.episodeTotal
      : quickAddForm.watched;
  try {
    await props.createFromResult(quickAddPick.value, {
      ...quickAddForm,
      watched,
      status: bucketToReal(quickAddForm.status),
    });
    closeQuickAdd();
  } finally {
    quickAddSaving.value = false;
  }
}

defineExpose({ openQuickAdd });
</script>

<template>
  <div class="lib-root">
    <MediaTopBar :active="kind">
      <template #actions>
        <SegmentedTabs
          :options="LAYOUT_OPTIONS"
          :model-value="layout"
          aria-label="Layout"
          @update:model-value="layout = $event as 'list' | 'shelf' | 'board'"
        />
      </template>
    </MediaTopBar>

    <div class="lib-inner">
      <div class="page-head">
        <div>
          <h1>
            {{
              kind === "movie" ? "Movies" : kind === "tv" ? "TV Shows" : "Anime"
            }}
          </h1>
          <div class="sub">
            {{ total }} {{ total === 1 ? "title" : "titles" }}
          </div>
        </div>
        <div style="display: flex; gap: 8px">
          <button
            type="button"
            class="select-btn"
            :class="{ on: selectMode }"
            @click="toggleSelectMode"
          >
            {{ selectMode ? "Done" : "Select" }}
          </button>
          <button
            type="button"
            class="add-btn"
            :disabled="selectMode"
            @click="openQuickAdd"
          >
            {{ addLabel }}
          </button>
          <slot name="actions"></slot>
        </div>
      </div>

      <div v-if="selectedIds.size" class="bulk-bar">
        <span class="count">{{ selectedIds.size }} selected</span>
        <select v-model="bulkStatusValue" @change="bulkApplyStatus">
          <option value="">Set status to...</option>
          <option v-for="s in STATUSES" :key="s.key" :value="s.key">
            {{ s.label }}
          </option>
        </select>
        <button type="button" class="btn-outline" @click="bulkFavorite">
          Toggle Favorite
        </button>
        <div class="spacer"></div>
        <button type="button" class="btn-outline" @click="bulkDelete">
          Remove from library
        </button>
        <button type="button" class="btn-outline" @click="clearSelection">
          Clear
        </button>
      </div>

      <div class="toolbar">
        <div class="search-wrap">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
          >
            <circle cx="11" cy="11" r="7" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input v-model="searchQuery" placeholder="Search your library..." />
        </div>
        <select v-model="sortKey" class="sort-select">
          <option value="rank">Sort: Rank</option>
          <option value="score">Sort: Score, highest first</option>
          <option value="title">Sort: Title A–Z</option>
          <option value="title_desc">Sort: Title Z–A</option>
          <option value="added">Sort: Recently added</option>
          <option value="year_new">Sort: Release year, newest</option>
          <option value="year_old">Sort: Release year, oldest</option>
          <option value="progress">Sort: Progress</option>
        </select>
        <button
          type="button"
          class="filter-btn"
          :class="{ 'active-filter': activeFilterCount }"
          @click="filtersOpen = !filtersOpen"
        >
          Filters
          <span v-if="activeFilterCount" class="count">{{
            activeFilterCount
          }}</span>
        </button>
        <div
          v-if="layout === 'shelf' || layout === 'board'"
          class="card-size-toggle"
          title="Card size"
        >
          <button
            v-for="s in ['compact', 'cozy', 'large']"
            :key="s"
            type="button"
            class="card-size-button"
            :class="{ active: shelfCardSize === s }"
            :title="s"
            @click="shelfCardSize = s as typeof shelfCardSize"
          >
            {{ s === "compact" ? "S" : s === "cozy" ? "M" : "L" }}
          </button>
        </div>
      </div>
      <div v-if="filtersOpen" class="filter-panel">
        <div class="filter-group">
          <span class="filter-label">Show</span>
          <button
            type="button"
            class="genre-chip"
            :class="{ selected: onlyFavorites }"
            @click="onlyFavorites = !onlyFavorites"
          >
            Favorites
          </button>
          <button
            type="button"
            class="genre-chip"
            :class="{ selected: onlyUnrated }"
            @click="onlyUnrated = !onlyUnrated"
          >
            Not scored yet
          </button>
          <button
            type="button"
            class="genre-chip"
            :class="{ selected: onlyWithNote }"
            @click="onlyWithNote = !onlyWithNote"
          >
            Has a note
          </button>
        </div>
        <div class="filter-group">
          <span class="filter-label">Score</span>
          <button
            v-for="s in SCORE_OPTIONS"
            :key="s"
            type="button"
            class="genre-chip"
            :class="{ selected: minScore === s }"
            @click="minScore = minScore === s ? null : s"
          >
            {{ s }}+
          </button>
        </div>
        <div class="filter-group">
          <span class="filter-label">Year</span>
          <input
            :value="yearFrom"
            type="number"
            class="year-input"
            placeholder="From"
            aria-label="Released from year"
            @input="yearFrom = ($event.target as HTMLInputElement).value"
          />
          <span class="filter-dash">to</span>
          <input
            :value="yearTo"
            type="number"
            class="year-input"
            placeholder="To"
            aria-label="Released up to year"
            @input="yearTo = ($event.target as HTMLInputElement).value"
          />
        </div>
        <div v-if="allFormats.length > 1" class="filter-group">
          <span class="filter-label">Format</span>
          <button
            v-for="f in allFormats"
            :key="f"
            type="button"
            class="genre-chip"
            :class="{ selected: selectedFormats.has(f) }"
            @click="toggleFormat(f)"
          >
            {{ f }}
          </button>
        </div>
        <div v-if="allGenres.length" class="filter-group">
          <span class="filter-label">Genre</span>
          <button
            v-for="g in allGenres"
            :key="g"
            type="button"
            class="genre-chip"
            :class="{ selected: selectedGenres.has(g) }"
            @click="toggleGenre(g)"
          >
            {{ g }}
          </button>
          <button
            v-if="selectedGenres.size > 1"
            type="button"
            class="genre-chip match-mode"
            :class="{ selected: genreMatchAll }"
            title="Require every selected genre instead of any of them"
            @click="genreMatchAll = !genreMatchAll"
          >
            {{ genreMatchAll ? "Match all" : "Match any" }}
          </button>
        </div>
        <div class="filter-foot">
          <span class="filter-result"
            >{{ filteredItems.length }} of {{ total }} loaded/matching</span
          >
          <button
            v-if="activeFilterCount"
            type="button"
            class="filter-clear"
            @click="clearFilters"
          >
            Clear filters
          </button>
        </div>
      </div>

      <div class="status-tabs">
        <button
          type="button"
          class="status-tab"
          :class="{ active: activeStatus === 'all' }"
          @click="activeStatus = 'all'"
        >
          All <span class="n">{{ statusCounts.all }}</span>
        </button>
        <button
          v-for="s in STATUSES"
          :key="s.key"
          type="button"
          class="status-tab"
          :class="{ active: activeStatus === s.key }"
          @click="activeStatus = s.key"
        >
          {{ s.label }} <span class="n">{{ statusCounts[s.key] }}</span>
        </button>
      </div>

      <div class="body">
        <p v-if="loading" class="empty-state">Loading…</p>
        <p v-else-if="error" class="empty-state error">{{ error }}</p>

        <!-- ===== STATS ===== -->
        <!-- ===== LIST ===== -->
        <template v-else-if="layout === 'list'">
          <p v-if="!filteredItems.length" class="empty-state">
            Nothing matches. Try a different filter or search.
          </p>
          <div v-else class="list-scroll">
            <div class="list-row-header">
              <span></span><span>Title</span><span></span><span>Progress</span
              ><span>Score</span><span>Rank</span><span>Status</span>
            </div>
            <div class="list-rows">
              <div
                v-for="it in filteredItems"
                :key="it.id"
                class="list-row"
                @click="handleCardClick(it)"
              >
                <div class="list-thumb-wrap">
                  <div class="list-thumb">
                    <img
                      v-if="it.poster"
                      :src="it.poster"
                      :alt="it.title"
                      loading="lazy"
                      decoding="async"
                    />
                  </div>
                  <div
                    v-if="selectMode"
                    class="select-checkbox"
                    :class="{ checked: selectedIds.has(it.id) }"
                    @click.stop="toggleSelectItem(it.id)"
                  >
                    <CheckIcon v-if="selectedIds.has(it.id)" />
                  </div>
                </div>
                <div class="list-title-col">
                  <div class="list-title">{{ it.title }}</div>
                  <div class="list-type">
                    {{ it.format ?? typeLabel
                    }}<template v-if="it.releaseYear">
                      · {{ it.releaseYear }}</template
                    >
                  </div>
                  <div class="airing-tag" :class="{ invisible: !it.airing }">
                    <span class="dot"></span>Airing
                  </div>
                </div>
                <div class="icon-cluster no-card-click">
                  <button
                    type="button"
                    class="icon-btn"
                    :class="{ active: it.favorite }"
                    title="Favorite"
                    @click.stop="emit('toggle-favorite', it.id)"
                  >
                    <svg
                      v-if="it.favorite"
                      viewBox="0 0 24 24"
                      fill="currentColor"
                      stroke="none"
                    >
                      <path
                        d="M12 21s-7.5-4.9-10.2-9.4C.2 8.6 1.4 5 4.9 4.1c2-.5 3.9.3 5.1 2C11.2 4.4 13.1 3.6 15.1 4.1c3.5.9 4.7 4.5 3.1 7.5C15.5 16.1 12 21 12 21z"
                      />
                    </svg>
                    <svg
                      v-else
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    >
                      <path
                        d="M12 21s-7.5-4.9-10.2-9.4C.2 8.6 1.4 5 4.9 4.1c2-.5 3.9.3 5.1 2C11.2 4.4 13.1 3.6 15.1 4.1c3.5.9 4.7 4.5 3.1 7.5C15.5 16.1 12 21 12 21z"
                      />
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="icon-btn"
                    :class="{ active: it.note }"
                    :title="it.note ? 'Edit note' : 'Add note'"
                    @click.stop="openNote(it)"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <path d="M14 3v4a1 1 0 0 0 1 1h4" />
                      <path
                        d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"
                      />
                      <line x1="8" y1="13" x2="16" y2="13" />
                      <line x1="8" y1="17" x2="13" y2="17" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="icon-btn"
                    title="Edit"
                    @click.stop="openEdit(it)"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <path d="M12 20h9" />
                      <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                    </svg>
                  </button>
                </div>
                <div class="list-progress">
                  <div class="list-progress-label">{{ it.progressLabel }}</div>
                  <button
                    v-if="it.canAdvance"
                    type="button"
                    class="plus-btn no-card-click"
                    title="Mark next episode watched"
                    @click.stop="advanceEpisode(it)"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2.5"
                      stroke-linecap="round"
                    >
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                  </button>
                  <div v-else class="plus-btn-spacer"></div>
                </div>
                <div class="score-tag" :class="{ empty: !it.score }">
                  {{ it.score ? `★ ${it.score}` : "–" }}
                </div>
                <div class="rank-cell">
                  <span v-if="computedRank(it)" class="rank-badge"
                    >#{{ computedRank(it) }}</span
                  >
                  <span v-else class="rank-empty">–</span>
                </div>
                <div class="status-cell">
                  <span class="pill" :class="statusBucket(it.status)">{{
                    statusBucketLabel(it.status)
                  }}</span>
                </div>
              </div>
            </div>
          </div>
          <div v-if="items.length < total" class="load-more-indicator">
            {{ loading ? "Loading more…" : "Scroll for more" }}
          </div>
        </template>

        <!-- ===== SHELF ===== -->
        <template v-else-if="layout === 'shelf'">
          <p v-if="!filteredItems.length" class="empty-state">
            Nothing matches. Try a different filter or search.
          </p>
          <div
            v-else
            class="shelf-grid"
            :style="{
              gridTemplateColumns: `repeat(auto-fill, minmax(${shelfCardMinWidth}, 1fr))`,
            }"
          >
            <div
              v-for="it in filteredItems"
              :key="it.id"
              class="shelf-card"
              @click="handleCardClick(it)"
              @mouseleave="blurOnLeave"
            >
              <div class="shelf-art-wrap">
                <div class="shelf-art">
                  <img
                    v-if="it.poster"
                    :src="it.poster"
                    :alt="it.title"
                    loading="lazy"
                    decoding="async"
                  />
                </div>
                <div
                  v-if="selectMode"
                  class="select-checkbox"
                  :class="{ checked: selectedIds.has(it.id) }"
                  @click.stop="toggleSelectItem(it.id)"
                >
                  <CheckIcon v-if="selectedIds.has(it.id)" />
                </div>
                <span v-if="computedRank(it)" class="shelf-rank rank-badge"
                  >#{{ computedRank(it) }}</span
                >

                <div v-if="!selectMode" class="sc-actions no-card-click">
                  <button
                    v-if="it.canAdvance"
                    type="button"
                    class="sc-action"
                    title="Mark next episode watched"
                    @click.stop="advanceEpisode(it)"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2.5"
                      stroke-linecap="round"
                    >
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="sc-action"
                    :class="{ active: it.favorite }"
                    title="Favorite"
                    @click.stop="emit('toggle-favorite', it.id)"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      :fill="it.favorite ? 'currentColor' : 'none'"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linejoin="round"
                    >
                      <path
                        d="M12 21s-7.5-4.9-10.2-9.4C.2 8.6 1.4 5 4.9 4.1c2-.5 3.9.3 5.1 2C11.2 4.4 13.1 3.6 15.1 4.1c3.5.9 4.7 4.5 3.1 7.5C15.5 16.1 12 21 12 21z"
                      />
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="sc-action"
                    :class="{ active: it.note }"
                    :title="it.note ? 'Edit note' : 'Add note'"
                    @click.stop="openNote(it)"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <path d="M14 3v4a1 1 0 0 0 1 1h4" />
                      <path
                        d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"
                      />
                      <line x1="8" y1="13" x2="16" y2="13" />
                      <line x1="8" y1="17" x2="13" y2="17" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="sc-action"
                    title="Edit"
                    @click.stop="openEdit(it)"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <path d="M12 20h9" />
                      <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                    </svg>
                  </button>
                </div>
              </div>
              <div class="shelf-body">
                <div class="shelf-title-row">
                  <div class="shelf-title">{{ it.title }}</div>
                  <div class="score-tag" :class="{ empty: !it.score }">
                    {{ it.score ? `★ ${it.score}` : "–" }}
                  </div>
                </div>
                <div class="shelf-meta-row">
                  <span class="shelf-type">{{ it.format ?? typeLabel }}</span>
                  <span class="shelf-sub">{{ it.progressLabel }}</span>
                </div>
                <div class="shelf-progress-row">
                  <div class="list-progress-track">
                    <div
                      class="list-progress-fill"
                      :style="{ width: progressPct(it) + '%' }"
                    ></div>
                  </div>
                  <div v-if="it.airing" class="airing-tag">
                    <span class="dot"></span>Airing
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-if="items.length < total" class="load-more-indicator">
            {{ loading ? "Loading more…" : "Scroll for more" }}
          </div>
        </template>

        <!-- ===== BOARD ===== -->
        <template v-else-if="layout === 'board'">
          <p v-if="!boardGroups.length" class="empty-state">
            Nothing matches. Try a different filter or search.
          </p>
          <div
            v-for="group in boardGroups"
            :key="group.status.key"
            class="board-section"
          >
            <div class="board-heading">
              <h2>{{ group.status.label }}</h2>
              <span class="n">{{ group.rowItems.length }}</span>
              <div class="board-nav">
                <button
                  type="button"
                  :disabled="group.start === 0"
                  @click="moveBoard(group.status.key, -1, boardVisibleCount)"
                >
                  ‹
                </button>
                <button
                  type="button"
                  :disabled="
                    group.start + boardVisibleCount >= group.rowItems.length &&
                    items.length >= total
                  "
                  @click="moveBoard(group.status.key, 1, boardVisibleCount)"
                >
                  ›
                </button>
              </div>
            </div>
            <div ref="boardContainer" class="board-shelf">
              <div
                v-for="it in group.visibleItems"
                :key="it.id"
                class="board-card"
                :style="{ width: boardCardWidth }"
                @click="handleCardClick(it)"
              >
                <div class="board-art-wrap">
                  <div class="board-art">
                    <img
                      v-if="it.poster"
                      :src="it.poster"
                      :alt="it.title"
                      loading="lazy"
                      decoding="async"
                    />
                  </div>
                  <div
                    v-if="selectMode"
                    class="select-checkbox"
                    :class="{ checked: selectedIds.has(it.id) }"
                    @click.stop="toggleSelectItem(it.id)"
                  >
                    <CheckIcon v-if="selectedIds.has(it.id)" />
                  </div>
                  <span v-if="computedRank(it)" class="board-rank rank-badge"
                    >#{{ computedRank(it) }}</span
                  >
                </div>
                <div class="board-title-row">
                  <div class="board-title">{{ it.title }}</div>
                  <span class="score-tag" :class="{ empty: !it.score }">{{
                    it.score ? `★ ${it.score}` : "–"
                  }}</span>
                </div>
                <div class="shelf-type">{{ it.format ?? typeLabel }}</div>
                <div v-if="it.releaseYear" class="shelf-year">
                  {{ it.releaseYear }}
                </div>
                <div class="board-progress-row">
                  <div class="list-progress-track">
                    <div
                      class="list-progress-fill"
                      :style="{ width: progressPct(it) + '%' }"
                    ></div>
                  </div>
                  <div class="board-progress-info">
                    <span class="shelf-sub">{{ it.progressLabel }}</span>
                    <button
                      v-if="it.canAdvance"
                      type="button"
                      class="plus-btn no-card-click"
                      title="Mark next episode watched"
                      @click.stop="advanceEpisode(it)"
                    >
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2.5"
                        stroke-linecap="round"
                      >
                        <line x1="12" y1="5" x2="12" y2="19" />
                        <line x1="5" y1="12" x2="19" y2="12" />
                      </svg>
                    </button>
                  </div>
                  <div v-if="it.airing" class="airing-tag">
                    <span class="dot"></span>Airing
                  </div>
                </div>
                <div class="board-footer-row">
                  <div class="icon-cluster shelf-icon-cluster no-card-click">
                    <button
                      type="button"
                      class="icon-btn"
                      :class="{ active: it.favorite }"
                      title="Favorite"
                      @click.stop="emit('toggle-favorite', it.id)"
                    >
                      <svg
                        v-if="it.favorite"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        stroke="none"
                      >
                        <path
                          d="M12 21s-7.5-4.9-10.2-9.4C.2 8.6 1.4 5 4.9 4.1c2-.5 3.9.3 5.1 2C11.2 4.4 13.1 3.6 15.1 4.1c3.5.9 4.7 4.5 3.1 7.5C15.5 16.1 12 21 12 21z"
                        />
                      </svg>
                      <svg
                        v-else
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                      >
                        <path
                          d="M12 21s-7.5-4.9-10.2-9.4C.2 8.6 1.4 5 4.9 4.1c2-.5 3.9.3 5.1 2C11.2 4.4 13.1 3.6 15.1 4.1c3.5.9 4.7 4.5 3.1 7.5C15.5 16.1 12 21 12 21z"
                        />
                      </svg>
                    </button>
                    <button
                      type="button"
                      class="icon-btn"
                      :class="{ active: it.note }"
                      :title="it.note ? 'Edit note' : 'Add note'"
                      @click.stop="openNote(it)"
                    >
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <path d="M14 3v4a1 1 0 0 0 1 1h4" />
                        <path
                          d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"
                        />
                        <line x1="8" y1="13" x2="16" y2="13" />
                        <line x1="8" y1="17" x2="13" y2="17" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      class="icon-btn"
                      title="Edit"
                      @click.stop="openEdit(it)"
                    >
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <path d="M12 20h9" />
                        <path
                          d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"
                        />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- ===== Notes modal ===== -->
    <div v-if="noteOpen" class="modal-overlay" @click.self="closeNote">
      <div class="modal-card">
        <h3>Notes</h3>
        <div class="sub">Only visible to you.</div>
        <textarea
          v-model="noteText"
          placeholder="Nothing written yet: first impressions, things to remember, why you dropped it..."
        ></textarea>
        <div class="modal-actions">
          <button type="button" class="btn-outline" @click="closeNote">
            Cancel
          </button>
          <button type="button" class="btn-solid" @click="saveNote">
            Save
          </button>
        </div>
      </div>
    </div>

    <!-- ===== "You finished it" rating prompt ===== -->
    <div v-if="finishOpen" class="modal-overlay" @click.self="closeFinish">
      <div class="modal-card finish-card">
        <div
          v-if="finishPoster"
          class="finish-poster"
          :style="{ backgroundImage: `url(${finishPoster})` }"
        ></div>
        <div class="finish-body">
          <div class="finish-eyebrow">You finished it</div>
          <h3>{{ finishTitle }}</h3>
          <div class="sub">Give it a rating, or skip for now.</div>
          <div class="decimal-rate finish-rate">
            <button type="button" @click="stepFinishScore(-0.5)">−</button>
            <input
              v-model.number="finishScore"
              type="number"
              min="0"
              max="10"
              step="0.1"
              placeholder="–"
            />
            <span class="of10">/ 10</span>
            <button type="button" @click="stepFinishScore(0.5)">+</button>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn-outline" @click="closeFinish">
              Skip
            </button>
            <button type="button" class="btn-solid" @click="finishSave">
              Save rating
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== Small edit modal ===== -->
    <div v-if="editOpen" class="modal-overlay" @click.self="closeEdit">
      <div class="modal-card">
        <h3>Edit</h3>
        <div class="sub">Quick edit: status, rating, progress.</div>
        <div class="qa-field-grid">
          <label class="qa-field">
            <span>Status</span>
            <select v-model="editForm.status">
              <option v-for="s in STATUSES" :key="s.key" :value="s.key">
                {{ s.label }}
              </option>
            </select>
          </label>
          <label
            v-if="items.find((i) => i.id === editTargetId)?.isEpisodic"
            class="qa-field"
          >
            <span>Episodes watched</span>
            <input v-model.number="editForm.watched" type="number" min="0" />
          </label>
          <label
            v-if="items.find((i) => i.id === editTargetId)?.isEpisodic"
            class="qa-field"
          >
            <span>Total episodes</span>
            <input
              v-model.number="editForm.totalEpisodes"
              type="number"
              min="0"
              placeholder="Unknown"
            />
          </label>
          <label class="qa-field">
            <span>Your rating (0–10)</span>
            <input
              v-model.number="editForm.score"
              type="number"
              min="0"
              max="10"
              step="0.1"
              placeholder="–"
            />
          </label>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn-outline" @click="closeEdit">
            Cancel
          </button>
          <button type="button" class="btn-solid" @click="saveEdit">
            Save
          </button>
        </div>
      </div>
    </div>

    <!-- ===== Quick Add ===== -->
    <div v-if="quickAddOpen" class="modal-overlay" @click.self="closeQuickAdd">
      <div class="modal-card qa-card">
        <div v-if="quickAddStep === 'search'">
          <div class="qa-header">
            <div class="qa-header-row">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
              >
                <circle cx="11" cy="11" r="7" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <h3>{{ addLabel.replace("+ ", "") }}</h3>
            </div>
            <div class="sub">Search, then pick the right result.</div>
          </div>
          <div class="qa-body">
            <div class="qa-search-row">
              <input
                v-model="quickAddQuery"
                autofocus
                placeholder="Search by title..."
                @keyup.enter="runQuickAddSearch"
              />
              <button
                type="button"
                class="qa-add-btn"
                @click="runQuickAddSearch"
              >
                Search
              </button>
            </div>
            <p
              v-if="quickAddProviderErrors.length"
              class="empty-state error"
              style="padding: 8px 0; font-size: 0.78rem"
            >
              {{ quickAddProviderErrors.join(" · ") }}
            </p>
            <p v-if="quickAddSearching" class="empty-state">Searching…</p>
            <p v-else-if="!quickAddResults.length" class="empty-state">
              No results yet. Search above.
            </p>
            <div v-else class="qa-results">
              <div v-for="(r, i) in quickAddResults" :key="i" class="qa-result">
                <div
                  class="qa-result-art"
                  :style="
                    r.poster ? { backgroundImage: `url(${r.poster})` } : {}
                  "
                ></div>
                <div class="qa-result-titles">
                  <div class="qa-result-english">{{ r.title }}</div>
                  <div
                    v-if="r.releaseYear || r.episodeTotal"
                    class="qa-result-meta"
                  >
                    <span v-if="r.releaseYear">{{ r.releaseYear }}</span>
                    <span v-if="r.episodeTotal"
                      >{{ r.episodeTotal }} episode{{
                        r.episodeTotal === 1 ? "" : "s"
                      }}</span
                    >
                  </div>
                  <div v-if="r.description" class="qa-result-desc">
                    {{ r.description }}
                  </div>
                </div>
                <button
                  type="button"
                  class="qa-add-btn"
                  @click="pickQuickAddResult(r)"
                >
                  + Add
                </button>
              </div>
            </div>
            <div class="qa-search-foot">
              <button type="button" class="btn-outline" @click="closeQuickAdd">
                Cancel
              </button>
            </div>
          </div>
        </div>

        <div v-else>
          <div class="qa-body">
            <button
              type="button"
              class="qa-back-link"
              @click="quickAddBackToSearch"
            >
              &larr; Back to results
            </button>
            <div class="qa-form-header">
              <div
                class="qa-form-art"
                :style="
                  quickAddPick?.poster
                    ? { backgroundImage: `url(${quickAddPick.poster})` }
                    : {}
                "
              ></div>
              <div class="qa-form-titles">
                <div class="qa-result-english">{{ quickAddPick?.title }}</div>
                <div
                  v-if="quickAddPick?.releaseYear || quickAddPick?.episodeTotal"
                  class="qa-result-meta"
                >
                  <span v-if="quickAddPick?.releaseYear">{{
                    quickAddPick.releaseYear
                  }}</span>
                  <span v-if="quickAddPick?.episodeTotal"
                    >{{ quickAddPick.episodeTotal }} episode{{
                      quickAddPick.episodeTotal === 1 ? "" : "s"
                    }}</span
                  >
                </div>
              </div>
            </div>
            <p class="qa-section-label">Your progress</p>
            <div class="qa-field-grid">
              <label class="qa-field">
                <span>Status</span>
                <select v-model="quickAddForm.status">
                  <option v-for="s in STATUSES" :key="s.key" :value="s.key">
                    {{ s.label }}
                  </option>
                </select>
              </label>
              <label v-if="kind !== 'movie'" class="qa-field">
                <span
                  >Episodes watched<template v-if="quickAddPick?.episodeTotal">
                    of {{ quickAddPick.episodeTotal }}</template
                  ></span
                >
                <input
                  v-model.number="quickAddForm.watched"
                  type="number"
                  min="0"
                  :max="quickAddPick?.episodeTotal ?? undefined"
                  @change="clampQuickAddWatched"
                />
              </label>
              <label class="qa-field">
                <span>Your rating (0–10)</span>
                <input
                  v-model.number="quickAddForm.score"
                  type="number"
                  min="0"
                  max="10"
                  step="0.1"
                  placeholder="–"
                />
              </label>
              <label class="qa-field">
                <span>Start date</span>
                <input v-model="quickAddForm.startDate" type="date" />
              </label>
              <label class="qa-field">
                <span>End date</span>
                <input v-model="quickAddForm.endDate" type="date" />
              </label>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn-outline" @click="closeQuickAdd">
                Cancel
              </button>
              <button
                type="button"
                class="btn-solid"
                :disabled="quickAddSaving"
                @click="saveQuickAdd"
              >
                {{ quickAddSaving ? "Adding…" : "Add to Library" }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Ported 1:1 from the "Library Layouts" design mockup — same tokens,
   same component shapes. */
.lib-root {
  --bg: #0d0d0d;
  --surface: #1a1a1a;
  --surface-2: #222222;
  --border: #2b2b2b;
  --border-soft: #202020;
  --accent: #d68a34;
  --accent-soft: rgba(214, 138, 52, 0.16);
  --accent-line: rgba(214, 138, 52, 0.4);
  --good: #6fbf73;
  --good-soft: rgba(111, 191, 115, 0.16);
  --hold: #7ba7d9;
  --hold-soft: rgba(123, 167, 217, 0.16);
  --dropped: #d96f6f;
  --dropped-soft: rgba(217, 111, 111, 0.16);
  --plan: #9d8cd9;
  --plan-soft: rgba(157, 140, 217, 0.16);
  --live: #e5484d;
  --text: #f2f2f2;
  --text-dim: #9c9c9c;
  --text-faint: #666;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, sans-serif;
}
.lib-root * {
  box-sizing: border-box;
}
.lib-root svg {
  display: block;
}
.lib-inner {
  padding: 24px 24px 60px 48px;
  box-sizing: border-box;
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.page-head h1 {
  font-weight: 800;
  font-size: 1.7rem;
  margin: 0;
}
.page-head .sub {
  color: var(--text-faint);
  font-size: 0.85rem;
  margin-top: 4px;
}
.add-btn {
  background: var(--accent);
  border: none;
  color: #14100a;
  border-radius: 8px;
  padding: 0 18px;
  height: 38px;
  font-family: inherit;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
}
.add-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.select-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 8px;
  padding: 0 16px;
  height: 38px;
  font-family: inherit;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
}
.select-btn.on {
  background: var(--accent-soft);
  border-color: var(--accent-line);
  color: var(--accent);
}

.bulk-bar {
  margin-top: 12px;
  padding: 10px 16px;
  background: var(--accent-soft);
  border: 1px solid var(--accent-line);
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.bulk-bar .count {
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--accent);
  white-space: nowrap;
}
.bulk-bar select {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 7px;
  padding: 7px 10px;
  font-family: inherit;
  font-size: 0.82rem;
  cursor: pointer;
}
.bulk-bar .spacer {
  flex: 1;
}

.toolbar {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.search-wrap {
  position: relative;
  flex: 1;
  min-width: 140px;
  max-width: 340px;
}
.search-wrap svg {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  width: 15px;
  height: 15px;
  color: var(--text-faint);
  pointer-events: none;
}
.search-wrap input {
  box-sizing: border-box;
  height: 38px;
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 0 12px 0 34px;
  font-family: inherit;
  font-size: 0.85rem;
}
.search-wrap input:focus {
  outline: none;
  border-color: var(--accent-line);
}
.sort-select {
  box-sizing: border-box;
  height: 38px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 0 12px;
  font-family: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}
.filter-btn {
  box-sizing: border-box;
  height: 38px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 8px;
  padding: 0 14px;
  font-family: inherit;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.filter-btn.active-filter {
  border-color: var(--accent-line);
  color: var(--accent);
}
.filter-btn .count {
  background: var(--accent);
  color: #14100a;
  border-radius: 999px;
  font-size: 0.66rem;
  font-weight: 800;
  padding: 1px 6px;
}
.card-size-toggle {
  display: flex;
  gap: 2px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 3px;
}
.card-size-button {
  background: none;
  border: none;
  color: var(--text-faint);
  width: 26px;
  height: 26px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.7rem;
  font-weight: 700;
}
.card-size-button:hover {
  color: var(--text);
  background: rgba(255, 255, 255, 0.06);
}
.card-size-button.active {
  color: #14100a;
  background: var(--accent);
}
.filter-panel {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-label {
  min-width: 56px;
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.year-input {
  box-sizing: border-box;
  width: 84px;
  height: 28px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 0 10px;
  font-size: 0.78rem;
}
.filter-dash {
  font-size: 0.76rem;
  color: var(--text-dim);
}
.match-mode {
  margin-left: 6px;
}
.filter-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--border-soft);
}
.filter-result {
  font-size: 0.76rem;
  color: var(--text-dim);
}
.filter-clear {
  background: none;
  border: none;
  color: var(--accent);
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
}
.genre-chip {
  box-sizing: border-box;
  height: 28px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 999px;
  padding: 0 12px;
  font-size: 0.76rem;
  font-weight: 700;
  cursor: pointer;
}
.genre-chip.selected {
  background: var(--accent-soft);
  border-color: var(--accent-line);
  color: var(--accent);
}

.status-tabs {
  margin-top: 14px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--border-soft);
}
.status-tab {
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  display: flex;
  align-items: center;
  gap: 7px;
}
.status-tab.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}
.status-tab .n {
  font-variant-numeric: tabular-nums;
  color: var(--text-faint);
  font-weight: 500;
}
.status-tab.active .n {
  color: var(--text-dim);
}

.body {
  padding-top: 22px;
}
.empty-state {
  color: var(--text-faint);
  font-size: 0.9rem;
  padding: 40px 0;
  text-align: center;
}
.empty-state.error {
  color: #e57373;
}

/* Solid-fill chips, same visual language as the app's own active-tab
   buttons (the segmented tabs' active state: solid color, dark text) so
   status reads as a confident, deliberate color instead of a faint tint
   with a stray dot in front of it. */
/* A small masked icon per status (currentColor-tinted, so one image works
   for every state) reads faster than color alone and gives each status a
   distinct silhouette instead of relying purely on hue. */
.pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  width: 128px;
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.01em;
  padding: 5px 10px;
  border-radius: 999px;
  white-space: nowrap;
  text-align: center;
}
.pill::before {
  content: "";
  width: 10px;
  height: 10px;
  flex-shrink: 0;
  background: currentColor;
  -webkit-mask-repeat: no-repeat;
  mask-repeat: no-repeat;
  -webkit-mask-position: center;
  mask-position: center;
  -webkit-mask-size: contain;
  mask-size: contain;
}
.pill.watching {
  background: var(--accent-soft);
  color: var(--accent);
}
.pill.watching::before {
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M8 5v14l11-7z'/%3E%3C/svg%3E");
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M8 5v14l11-7z'/%3E%3C/svg%3E");
}
.pill.completed {
  background: var(--good-soft);
  color: var(--good);
}
.pill.completed::before {
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='4 12 9 17 20 6'/%3E%3C/svg%3E");
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='4 12 9 17 20 6'/%3E%3C/svg%3E");
}
.pill.hold {
  background: var(--hold-soft);
  color: var(--hold);
}
.pill.hold::before {
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect x='5' y='4' width='5' height='16'/%3E%3Crect x='14' y='4' width='5' height='16'/%3E%3C/svg%3E");
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect x='5' y='4' width='5' height='16'/%3E%3Crect x='14' y='4' width='5' height='16'/%3E%3C/svg%3E");
}
.pill.dropped {
  background: var(--dropped-soft);
  color: var(--dropped);
}
.pill.dropped::before {
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='3' stroke-linecap='round'%3E%3Cline x1='5' y1='5' x2='19' y2='19'/%3E%3Cline x1='19' y1='5' x2='5' y2='19'/%3E%3C/svg%3E");
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='3' stroke-linecap='round'%3E%3Cline x1='5' y1='5' x2='19' y2='19'/%3E%3Cline x1='19' y1='5' x2='5' y2='19'/%3E%3C/svg%3E");
}
.pill.plan {
  background: var(--plan-soft);
  color: var(--plan);
}
.pill.plan::before {
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M6 3h12v18l-6-4-6 4z'/%3E%3C/svg%3E");
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M6 3h12v18l-6-4-6 4z'/%3E%3C/svg%3E");
}

.airing-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--live);
  margin-top: 3px;
  height: 14px;
}
.airing-tag.invisible {
  visibility: hidden;
}
.airing-tag .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--live);
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  border-radius: 5px;
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid var(--accent-line);
  font-size: 0.68rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}
.rank-cell {
  display: flex;
  align-items: center;
  justify-content: center;
}
.rank-empty {
  color: var(--text-faint);
  font-size: 0.75rem;
}
.status-cell {
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon-cluster {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.icon-btn {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-faint);
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}
.icon-btn svg {
  width: 12px;
  height: 12px;
}
.icon-btn:hover {
  border-color: var(--accent-line);
  color: var(--text);
}
.icon-btn.active {
  color: var(--accent);
  border-color: var(--accent-line);
  background: var(--accent-soft);
}
.plus-btn {
  background: transparent;
  border: 1.5px solid var(--accent-line);
  color: var(--accent);
  width: 26px;
  height: 26px;
  border-radius: 50%;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}
/* Reserves the plus button's own footprint even when it isn't rendered,
   so the episode-count label's right edge stays put instead of drifting
   further right on rows that have no advance button. */
.plus-btn-spacer {
  width: 26px;
  flex-shrink: 0;
}
.plus-btn svg {
  width: 12px;
  height: 12px;
  display: block;
}
.plus-btn:hover {
  background: var(--accent);
  color: #14100a;
}
.plus-btn:disabled {
  opacity: 0.3;
  cursor: default;
  background: var(--surface-2);
  border-color: var(--border);
  color: var(--text-faint);
}
.score-tag {
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  text-align: right;
}
/* In the List row specifically, the score sits in its own centered grid
   column (unlike Shelf/Board, where it's right-aligned inline next to the
   title) — so it needs to line up under the "Score" header instead. */
.list-row > .score-tag {
  text-align: center;
}
.score-tag.empty {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  border-radius: 5px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-faint);
  font-weight: 600;
}
.select-checkbox {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: rgba(10, 10, 10, 0.8);
  border: 1.5px solid rgba(255, 255, 255, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--accent);
  font-size: 0.85rem;
  font-weight: 800;
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 4;
}
.select-checkbox.checked {
  background: var(--accent);
  border-color: var(--accent);
  color: #14100a;
}

/* LIST */
.list-scroll {
  overflow-x: auto;
}
.list-row-header,
.list-rows {
  min-width: 870px;
}
.list-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.list-row {
  display: grid;
  grid-template-columns:
    76px minmax(180px, 1fr)
    90px 170px 60px 46px 128px;
  align-items: center;
  gap: 20px;
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: 10px;
  padding: 10px 16px;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.list-row:hover {
  border-color: var(--accent-line);
}
.list-thumb-wrap {
  position: relative;
  width: 76px;
}
.list-thumb {
  width: 76px;
  aspect-ratio: 2 / 3;
  border-radius: 6px;
  background-color: var(--surface-2);
  overflow: hidden;
}
.list-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.list-title-col {
  min-width: 0;
}
.list-title {
  font-weight: 700;
  font-size: 1.02rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}
.list-type {
  font-size: 0.72rem;
  color: var(--text-faint);
}
/* One line: episode count, then the advance button, centered as a unit
   under the "Progress" header — matching how Score/Rank/Status center
   under their own headers. */
.list-progress {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.list-progress-track {
  flex: 1;
  min-width: 40px;
  height: 7px;
  border-radius: 999px;
  background: var(--border-soft);
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.3);
}
.list-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), #e8a552);
  border-radius: 999px;
}
.list-progress-label {
  font-size: 0.7rem;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
/* Bigger in the List row specifically — with the bar gone, the count is
   the only content in that cell, so it carries more visual weight. A
   fixed width, right-aligned, means "37/37" and "0/6" both end at the
   same x position instead of drifting depending on digit count. */
.list-progress > .list-progress-label {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text);
  width: 56px;
  text-align: right;
}
.list-row-header {
  display: grid;
  grid-template-columns:
    76px minmax(180px, 1fr)
    90px 170px 60px 46px 128px;
  gap: 20px;
  padding: 0 16px 8px;
  font-size: 0.66rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-faint);
  font-weight: 700;
}
.list-row-header span:nth-child(4),
.list-row-header span:nth-child(5),
.list-row-header span:nth-child(6),
.list-row-header span:nth-child(7) {
  text-align: center;
}

/* SHELF */
.shelf-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 14px;
  align-items: stretch;
}
.shelf-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  cursor: pointer;
}
.shelf-art-wrap {
  position: relative;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border-soft);
}
.shelf-art {
  aspect-ratio: 2 / 3;
  background-color: var(--surface-2);
  overflow: hidden;
  transition: transform 0.2s ease;
}
.shelf-art img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.shelf-art-wrap:hover .shelf-art {
  transform: scale(1.04);
}
.shelf-rank {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
}
.shelf-card {
  transition: transform 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}
.shelf-card:hover {
  transform: translateY(-3px);
}
.shelf-art-wrap {
  transition:
    box-shadow 0.28s ease,
    border-color 0.2s ease;
}
.shelf-card:hover .shelf-art-wrap {
  border-color: var(--border);
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.45);
}
/* Actions ride on the poster and only appear while the card is hovered
   or has keyboard focus, like the Games cards. */
.sc-actions {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 3;
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding: 26px 8px 8px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.65), transparent);
  opacity: 0;
  transform: translateY(6px);
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
  pointer-events: none;
}
.shelf-card:hover .sc-actions,
.shelf-card:focus-within .sc-actions {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}
.sc-action {
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(20, 20, 20, 0.6);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s ease;
}
.sc-action svg {
  width: 13px;
  height: 13px;
}
.sc-action:hover {
  background: rgba(60, 60, 60, 0.9);
}
.sc-action.active {
  color: #ff6f91;
  border-color: rgba(255, 111, 145, 0.4);
  background: rgba(224, 86, 122, 0.2);
}
.shelf-meta-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-top: 2px;
  min-width: 0;
}
.shelf-meta-row .shelf-type {
  margin: 0;
}
.shelf-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  margin-top: 8px;
}
.shelf-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
}
.shelf-title {
  min-width: 0;
  font-size: 0.85rem;
  font-weight: 700;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  /* Reserved so every card in a row keeps its progress/status rows lined
     up regardless of title length — a one-line title leaves blank space
     here rather than everything below it drifting up. */
  min-height: calc(1.3em * 2);
}
.shelf-type {
  margin-top: 2px;
  font-size: 0.7rem;
  color: var(--text-faint);
}
.shelf-year {
  margin-top: 1px;
  font-size: 0.68rem;
  color: var(--text-faint);
  opacity: 0.75;
}
.shelf-progress-row {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.shelf-progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}
.shelf-sub {
  font-size: 0.72rem;
  color: var(--text-faint);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
}
.shelf-progress-info .plus-btn {
  flex-shrink: 0;
}
/* Shared by Board: bar, then episode count, then the advance button, all
   on one line — same order as the List layout's row. */
.shelf-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 8px;
  margin-top: 8px;
}
/* Shrunk a notch versus List's icon buttons so favorite/note/edit never
   force a Shelf card wider than its own art — the footer still wraps to
   a second line at the smallest card size rather than clipping. */
.shelf-icon-cluster {
  gap: 6px;
}
.shelf-icon-cluster .icon-btn {
  width: 24px;
  height: 24px;
}
.shelf-icon-cluster .icon-btn svg {
  width: 11px;
  height: 11px;
}

/* BOARD */
.board-section {
  margin-top: 24px;
}
.board-section:first-child {
  margin-top: 16px;
}
.board-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-soft);
}
.board-nav {
  margin-left: auto;
  display: flex;
  gap: 6px;
}
.board-nav button {
  width: 30px;
  height: 30px;
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text);
  cursor: pointer;
}
.board-nav button:disabled {
  opacity: 0.35;
  cursor: default;
}
.load-more-indicator {
  padding: 14px;
  text-align: center;
  color: var(--text-faint);
  font-size: 0.8rem;
}
.board-heading h2 {
  font-size: 1rem;
  font-weight: 800;
  margin: 0;
}
.board-heading .n {
  font-size: 0.78rem;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}
.board-shelf {
  display: flex;
  gap: 14px;
  overflow: hidden;
  padding-bottom: 8px;
}
.board-card {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: 10px;
  padding: 10px;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.board-card:hover {
  border-color: var(--accent-line);
}
.board-art-wrap {
  position: relative;
  border-radius: 7px;
  overflow: hidden;
  margin-bottom: 8px;
}
.board-art {
  aspect-ratio: 2 / 3;
  background-color: var(--surface-2);
  overflow: hidden;
  transition: transform 0.2s ease;
}
.board-art img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.board-art-wrap:hover .board-art {
  transform: scale(1.04);
}
.board-rank {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 2;
}
.board-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
}
.board-title {
  min-width: 0;
  font-size: 0.84rem;
  font-weight: 700;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: calc(1.3em * 2);
}
.board-progress-row {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.board-progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}
.board-progress-info .plus-btn {
  flex-shrink: 0;
}
.board-footer-row {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  margin-top: 8px;
}

/* Top rated — the one Stats panel built from real artwork instead of
   bars, so the page isn't wall-to-wall charts. */

/* Modals */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--ui-z-modal);
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.modal-card {
  width: 100%;
  max-width: 440px;
  background: var(--ui-popover);
  border: 1px solid var(--border);
  border-radius: var(--ui-radius-dialog);
  padding: 22px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}
.modal-card h3 {
  margin: 0 0 4px;
  font-size: 1.05rem;
  font-weight: 800;
}
.modal-card .sub {
  font-size: 0.78rem;
  color: var(--text-faint);
  margin-bottom: 14px;
}
.modal-card textarea {
  width: 100%;
  min-height: 100px;
  resize: vertical;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 10px;
  font-family: inherit;
  font-size: 0.88rem;
  line-height: 1.5;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
.btn-outline {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 8px;
  padding: 0 16px;
  height: 36px;
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
}
.btn-solid {
  background: var(--accent);
  border: none;
  color: #14100a;
  border-radius: 8px;
  padding: 0 16px;
  height: 36px;
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
}
.btn-solid:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.decimal-rate {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin: 10px 0 4px;
}
.decimal-rate button {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 1.2rem;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.decimal-rate button:hover {
  border-color: var(--accent-line);
  color: var(--accent);
}
.decimal-rate input {
  width: 100px;
  text-align: center;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--accent);
  border-radius: 10px;
  padding: 8px 0;
  font-family: inherit;
  font-size: 1.6rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}
.decimal-rate input:focus {
  outline: none;
  border-color: var(--accent-line);
}
.decimal-rate .of10 {
  color: var(--text-faint);
  font-size: 0.9rem;
}
.finish-card {
  max-width: 460px;
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.finish-poster {
  width: 88px;
  aspect-ratio: 2 / 3;
  border-radius: 10px;
  background-size: cover;
  background-position: center;
  background-color: var(--surface-2);
  flex-shrink: 0;
  box-shadow: 0 12px 26px -10px rgba(0, 0, 0, 0.6);
}
.finish-body {
  flex: 1;
  min-width: 0;
}
.finish-eyebrow {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 800;
  color: var(--accent);
  margin-bottom: 4px;
}
.finish-card h3 {
  margin: 0 0 4px;
  font-size: 1.15rem;
  font-weight: 800;
}
.finish-rate {
  justify-content: flex-start;
  margin: 16px 0 4px;
}

.qa-card {
  max-width: 540px;
  padding: 0;
  overflow: hidden;
}
.qa-header {
  padding: 22px 24px 18px;
  border-bottom: 1px solid var(--border-soft);
  background: linear-gradient(160deg, var(--accent-soft), transparent 70%);
}
.qa-search-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
.qa-header-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.qa-header-row svg {
  width: 20px;
  height: 20px;
  color: var(--accent);
  flex-shrink: 0;
}
.qa-header h3 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 800;
}
.qa-header .sub {
  margin: 4px 0 0;
}
.qa-body {
  padding: 20px 24px 24px;
}
.qa-search-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.qa-search-row input {
  flex: 1;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 9px;
  padding: 11px 14px;
  font-family: inherit;
  font-size: 0.9rem;
}
.qa-search-row input:focus {
  outline: none;
  border-color: var(--accent-line);
}
.qa-results {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 360px;
  overflow-y: auto;
}
.qa-result {
  display: grid;
  grid-template-columns: 58px 1fr auto;
  gap: 14px;
  align-items: center;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
  transition: border-color 0.15s ease;
}
.qa-result:hover {
  border-color: var(--accent-line);
}
.qa-result-art {
  width: 58px;
  aspect-ratio: 2 / 3;
  border-radius: 6px;
  background-size: cover;
  background-position: center;
  background-color: var(--surface);
  box-shadow: 0 8px 18px -6px rgba(0, 0, 0, 0.6);
}
.qa-result-titles {
  min-width: 0;
}
.qa-result-english {
  font-size: 0.94rem;
  font-weight: 700;
  margin: 1px 0 4px;
}
.qa-result-meta {
  display: flex;
  gap: 8px;
  font-size: 0.74rem;
  color: var(--text-faint);
  margin: 0 0 4px;
}
.qa-result-desc {
  font-size: 0.78rem;
  color: var(--text-dim);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.qa-add-btn {
  background: var(--accent);
  border: none;
  color: #14100a;
  border-radius: 8px;
  padding: 0 18px;
  height: 40px;
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}
.qa-add-btn:hover {
  filter: brightness(1.08);
}
.qa-form-header {
  display: flex;
  gap: 14px;
  align-items: center;
  margin: -20px -24px 20px;
  padding: 20px 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-soft);
}
.qa-form-art {
  width: 64px;
  aspect-ratio: 2 / 3;
  border-radius: 7px;
  background-size: cover;
  background-position: center;
  background-color: var(--surface);
  flex-shrink: 0;
  box-shadow: 0 10px 22px -8px rgba(0, 0, 0, 0.6);
}
.qa-form-titles .qa-result-english {
  font-size: 1.05rem;
}
.qa-section-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-weight: 700;
  color: var(--text-faint);
  margin: 0 0 10px;
}
.qa-field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 18px;
}
.qa-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.qa-field.full {
  grid-column: 1 / -1;
}
.qa-field span {
  font-size: 0.74rem;
  color: var(--text-dim);
  font-weight: 600;
}
.qa-field select,
.qa-field input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 9px 11px;
  font-family: inherit;
  font-size: 0.86rem;
}
.qa-field select:focus,
.qa-field input:focus {
  outline: none;
  border-color: var(--accent-line);
}
.qa-back-link {
  background: none;
  border: none;
  color: var(--text-faint);
  font-family: inherit;
  font-size: 0.78rem;
  cursor: pointer;
  margin-bottom: 14px;
  padding: 0;
  display: flex;
  align-items: center;
  gap: 4px;
}
.qa-back-link:hover {
  color: var(--accent);
}

/* phones and narrow windows: the seven-column list row can't fit, so it
   collapses to poster + title with the status/progress/score tags stacked
   underneath, and the padding meant for the sidebar gutter shrinks */
@media (max-width: 720px) {
  .lib-inner {
    padding: 16px 14px 60px;
  }
  .page-head {
    align-items: flex-start;
  }
  .list-row-header {
    display: none;
  }
  .list-row-header,
  .list-rows {
    min-width: 0;
  }
  .list-row {
    grid-template-columns: 56px minmax(0, 1fr);
    gap: 6px 12px;
  }
  .list-row > *:nth-child(n + 3) {
    grid-column: 2;
    justify-self: start;
  }
  .list-thumb-wrap {
    width: 56px;
  }
  .list-thumb {
    width: 100%;
  }
  /* the columns are set inline from the card size, so this needs !important */
  .shelf-grid {
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)) !important;
  }
}
</style>
