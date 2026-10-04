<script setup lang="ts">
// Shared across Movie/TV/Anime detail pages: rewatch log and "add to
// list", styled and placed as two more icon buttons right next to Edit
// and the favorite heart — one component instead of tripling this UI.
// The airing countdown lives on the Episodes tab instead (see
// utils/countdown.ts), not here.
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";
import { useConfirm } from "../state/dialog";
import { blurOnLeave } from "../utils/blurOnLeave";
import {
  fetchRewatches,
  addRewatch,
  deleteRewatch,
  fetchMediaLists,
  createMediaList,
  addToMediaList,
  removeFromMediaList,
  fetchListMembership,
  updateMediaList,
  deleteMediaList,
} from "../services/mediaExtras";
import type {
  MediaType,
  Rewatch,
  MediaListSummary,
  ListMembership,
} from "../services/mediaExtras";

const props = defineProps<{
  mediaType: MediaType;
  mediaId: string;
}>();

const router = useRouter();
const root = ref<HTMLElement | null>(null);
const rewatchBtn = ref<HTMLElement | null>(null);
const listBtn = ref<HTMLElement | null>(null);
// The popovers are teleported to <body> and positioned by these fixed
// coordinates. Nesting them inside the component's own tree put them
// under the hero section's `overflow: hidden` (used to crop the
// backdrop image), which silently clipped them off-screen despite a
// correct z-index — teleporting sidesteps that ancestor entirely, and
// any future page with its own clipping/stacking context is safe too.
const popoverStyle = ref<{ top: string; left: string }>({
  top: "0px",
  left: "0px",
});
function positionPopover(anchor: HTMLElement | null) {
  if (!anchor) return;
  const rect = anchor.getBoundingClientRect();
  popoverStyle.value = {
    top: `${rect.bottom + 10}px`,
    // 280px wide: keep it fully on screen with a 16px margin on phones
    left: `${Math.max(16, Math.min(rect.left, window.innerWidth - 296))}px`,
  };
}

function goToLists() {
  showListPopover.value = false;
  router.push("/lists");
}

// ---- rewatch log ----
const rewatches = ref<Rewatch[]>([]);
const rewatchesError = ref<string | null>(null);
const showRewatchPopover = ref(false);
const logDate = ref(new Date().toISOString().slice(0, 10));
const logNote = ref("");
const logging = ref(false);

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});
function formatRewatchDate(iso: string): string {
  // finished_on comes back as a bare "YYYY-MM-DD" — parsing that with
  // `new Date(...)` directly reads it as UTC midnight and can print the
  // previous day in a negative-UTC-offset timezone, so it's split apart
  // and built as a local date instead.
  const [y, m, d] = iso.split("-").map(Number);
  return dateFormatter.format(new Date(y, m - 1, d));
}

async function loadRewatches() {
  try {
    rewatches.value = await fetchRewatches(props.mediaType, props.mediaId);
  } catch (e) {
    rewatchesError.value =
      e instanceof Error ? e.message : "Failed to load rewatch history.";
  }
}

async function submitRewatch() {
  logging.value = true;
  try {
    const created = await addRewatch(
      props.mediaType,
      props.mediaId,
      logDate.value || undefined,
      logNote.value || null,
    );
    rewatches.value = [created, ...rewatches.value].sort((a, b) =>
      b.finishedOn.localeCompare(a.finishedOn),
    );
    logNote.value = "";
    logDate.value = new Date().toISOString().slice(0, 10);
  } catch (e) {
    rewatchesError.value =
      e instanceof Error ? e.message : "Failed to log rewatch.";
  } finally {
    logging.value = false;
  }
}

async function removeRewatch(id: string) {
  try {
    await deleteRewatch(id);
    rewatches.value = rewatches.value.filter((r) => r.id !== id);
  } catch (e) {
    rewatchesError.value =
      e instanceof Error ? e.message : "Failed to remove rewatch.";
  }
}

// ---- add to list ----
const lists = ref<MediaListSummary[]>([]);
const listsLoaded = ref(false);
const membership = ref<ListMembership[]>([]);
const showListPopover = ref(false);
const newListName = ref("");
const addingToList = ref<string | null>(null);
const listError = ref<string | null>(null);

const membershipByList = computed(() => {
  const map = new Map<string, string>();
  for (const m of membership.value) map.set(m.listId, m.itemId);
  return map;
});

async function loadLists() {
  listError.value = null;
  try {
    const [allLists, mine] = await Promise.all([
      fetchMediaLists(),
      fetchListMembership(props.mediaType, props.mediaId),
    ]);
    // smart lists fill themselves from a rule, so they are never an add target
    lists.value = allLists.filter((l) => !l.isSmart);
    membership.value = mine;
    listsLoaded.value = true;
  } catch (e) {
    listError.value = e instanceof Error ? e.message : "Failed to load lists.";
  }
}

async function toggleListMembership(listId: string) {
  addingToList.value = listId;
  listError.value = null;
  try {
    const itemId = membershipByList.value.get(listId);
    if (itemId) {
      await removeFromMediaList(listId, itemId);
      membership.value = membership.value.filter((m) => m.listId !== listId);
    } else {
      await addToMediaList(listId, props.mediaType, props.mediaId);
      const fresh = await fetchListMembership(props.mediaType, props.mediaId);
      membership.value = fresh;
    }
  } catch (e) {
    listError.value = e instanceof Error ? e.message : "Failed to update list.";
  } finally {
    addingToList.value = null;
  }
}

// ---- editing lists from here, so a list can be fixed without leaving
// the title you're looking at ----
const renamingId = ref<string | null>(null);
const renameDraft = ref("");
function startRename(l: MediaListSummary) {
  renamingId.value = l.id;
  renameDraft.value = l.name;
}
async function commitRename(l: MediaListSummary) {
  const name = renameDraft.value.trim();
  renamingId.value = null;
  if (!name || name === l.name) return;
  if (
    lists.value.some(
      (o) => o.id !== l.id && o.name.toLowerCase() === name.toLowerCase(),
    )
  ) {
    listError.value = `"${name}" already exists.`;
    return;
  }
  try {
    const updated = await updateMediaList(l.id, { name });
    lists.value = lists.value.map((o) => (o.id === l.id ? updated : o));
  } catch (e) {
    listError.value = e instanceof Error ? e.message : "Failed to rename list.";
  }
}
async function useAsCover(l: MediaListSummary) {
  try {
    const updated = await updateMediaList(l.id, {
      coverMediaId: props.mediaId,
    });
    lists.value = lists.value.map((o) => (o.id === l.id ? updated : o));
  } catch (e) {
    listError.value =
      e instanceof Error ? e.message : "Failed to set the cover.";
  }
}
const confirm = useConfirm();
async function removeList(l: MediaListSummary) {
  const ok = await confirm({
    message: `Delete "${l.name}"? This doesn't delete the titles in it, just the list.`,
    confirmLabel: "Delete list",
    danger: true,
  });
  if (!ok) return;
  try {
    await deleteMediaList(l.id);
    lists.value = lists.value.filter((o) => o.id !== l.id);
    membership.value = membership.value.filter((m) => m.listId !== l.id);
  } catch (e) {
    listError.value = e instanceof Error ? e.message : "Failed to delete list.";
  }
}

async function submitNewList() {
  const name = newListName.value.trim();
  if (!name) return;
  try {
    const created = await createMediaList(name);
    lists.value = [...lists.value, created];
    newListName.value = "";
    await toggleListMembership(created.id);
  } catch (e) {
    listError.value = e instanceof Error ? e.message : "Failed to create list.";
  }
}

// ---- popover open/close, one at a time, click-outside closes ----
function toggleRewatchPopover() {
  showListPopover.value = false;
  showRewatchPopover.value = !showRewatchPopover.value;
  if (showRewatchPopover.value) positionPopover(rewatchBtn.value);
}
async function toggleListPopover() {
  showRewatchPopover.value = false;
  showListPopover.value = !showListPopover.value;
  if (showListPopover.value) {
    positionPopover(listBtn.value);
    await loadLists();
  }
}
// Teleported popovers sit outside `root`, so click-outside checks both
// the trigger row and the (now-detached) popover elements themselves.
function onDocumentClick(e: MouseEvent) {
  const target = e.target as Node;
  const insideTriggers = root.value?.contains(target);
  const insidePopover = (target as HTMLElement).closest?.(".popover");
  if (!insideTriggers && !insidePopover) {
    showRewatchPopover.value = false;
    showListPopover.value = false;
  }
}

onMounted(() => {
  loadRewatches();
  document.addEventListener("click", onDocumentClick);
});
onBeforeUnmount(() => document.removeEventListener("click", onDocumentClick));
</script>

<template>
  <div ref="root" class="media-extras">
    <div class="extras-item">
      <button
        ref="rewatchBtn"
        type="button"
        class="icon-btn"
        :class="{ active: rewatches.length > 0 }"
        title="Rewatch history"
        @click.stop="toggleRewatchPopover"
      >
        <svg
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M3 12a9 9 0 1 0 3-6.7" />
          <path d="M3 4v5h5" />
        </svg>
        <span v-if="rewatches.length" class="badge-count">{{
          rewatches.length
        }}</span>
      </button>
    </div>

    <div class="extras-item">
      <button
        ref="listBtn"
        type="button"
        class="icon-btn"
        :class="{ active: membership.length > 0 }"
        title="Add to list"
        @click.stop="toggleListPopover"
      >
        <svg
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />
        </svg>
        <span v-if="membership.length" class="badge-count">{{
          membership.length
        }}</span>
      </button>
    </div>
  </div>

  <Teleport to="body">
    <Transition name="pop">
      <div
        v-if="showRewatchPopover"
        class="popover"
        :style="{ top: popoverStyle.top, left: popoverStyle.left }"
        @click.stop
      >
        <div class="popover-header">
          <svg
            class="popover-icon"
            viewBox="0 0 24 24"
            width="15"
            height="15"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M3 12a9 9 0 1 0 3-6.7" />
            <path d="M3 4v5h5" />
          </svg>
          <p class="popover-title">Rewatches</p>
          <span v-if="rewatches.length" class="popover-count">{{
            rewatches.length
          }}</span>
        </div>

        <ul v-if="rewatches.length" class="rewatch-list">
          <li v-for="r in rewatches" :key="r.id">
            <span class="rewatch-dot"></span>
            <div class="rewatch-info">
              <span class="rewatch-date">{{
                formatRewatchDate(r.finishedOn)
              }}</span>
              <span v-if="r.note" class="rewatch-note">{{ r.note }}</span>
            </div>
            <button
              type="button"
              class="remove-btn"
              title="Remove"
              @click="removeRewatch(r.id)"
            >
              ×
            </button>
          </li>
        </ul>
        <p v-else class="empty-hint">No rewatches logged yet.</p>
        <p v-if="rewatchesError" class="extras-error">{{ rewatchesError }}</p>

        <div class="popover-divider"></div>
        <div class="log-form">
          <input v-model="logDate" type="date" class="log-date" />
          <input
            v-model="logNote"
            type="text"
            placeholder="Note (optional)"
            class="log-note"
          />
          <button
            type="button"
            class="popover-primary-btn"
            :disabled="logging"
            @click="submitRewatch"
          >
            + Log
          </button>
        </div>
      </div>
    </Transition>

    <Transition name="pop">
      <div
        v-if="showListPopover"
        class="popover"
        :style="{ top: popoverStyle.top, left: popoverStyle.left }"
        @click.stop
      >
        <div class="popover-header">
          <svg
            class="popover-icon"
            viewBox="0 0 24 24"
            width="15"
            height="15"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />
          </svg>
          <p class="popover-title">Add to list</p>
        </div>

        <p v-if="listError" class="extras-error">{{ listError }}</p>
        <p v-if="listsLoaded && !lists.length" class="empty-hint">
          No lists yet. Create one below.
        </p>
        <ul v-else class="list-options">
          <li
            v-for="l in lists"
            :key="l.id"
            class="list-row"
            @mouseleave="blurOnLeave"
          >
            <input
              v-if="renamingId === l.id"
              v-model="renameDraft"
              class="rename-input"
              type="text"
              autofocus
              @keyup.enter="commitRename(l)"
              @keyup.esc="renamingId = null"
              @blur="commitRename(l)"
            />
            <template v-else>
              <button
                type="button"
                class="list-option"
                :class="{ checked: membershipByList.has(l.id) }"
                :disabled="addingToList === l.id"
                @click="toggleListMembership(l.id)"
              >
                <span class="list-check">
                  <svg
                    v-if="membershipByList.has(l.id)"
                    viewBox="0 0 24 24"
                    width="12"
                    height="12"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="3"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </span>
                <span class="list-option-name">{{ l.name }}</span>
                <span class="list-option-count">{{ l.itemCount }}</span>
              </button>
              <span class="list-row-actions">
                <button
                  v-if="
                    membershipByList.has(l.id) && l.coverMediaId !== mediaId
                  "
                  type="button"
                  title="Use this title as the list cover"
                  @click="useAsCover(l)"
                >
                  ★
                </button>
                <button
                  type="button"
                  title="Rename list"
                  @click="startRename(l)"
                >
                  ✎
                </button>
                <button
                  type="button"
                  title="Delete list"
                  @click="removeList(l)"
                >
                  ✕
                </button>
              </span>
            </template>
          </li>
        </ul>

        <div class="popover-divider"></div>
        <div class="new-list-row">
          <input
            v-model="newListName"
            type="text"
            placeholder="New list name…"
            class="new-list-input"
            @keyup.enter="submitNewList"
          />
          <button
            type="button"
            class="popover-primary-btn"
            @click="submitNewList"
          >
            Create
          </button>
        </div>
        <button type="button" class="manage-lists-btn" @click="goToLists">
          Manage all lists →
        </button>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.media-extras {
  display: flex;
  align-items: center;
  gap: 8px;
}
.extras-item {
  position: relative;
}
.icon-btn {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #f2f2f2;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  position: relative;
}
.icon-btn:hover {
  border-color: rgba(214, 138, 52, 0.4);
}
.icon-btn.active {
  color: #d68a34;
  border-color: rgba(214, 138, 52, 0.4);
  background: rgba(214, 138, 52, 0.16);
}
.badge-count {
  position: absolute;
  top: -4px;
  right: -4px;
  background: #d68a34;
  color: #14100a;
  font-size: 0.6rem;
  font-weight: 800;
  border-radius: 999px;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.pop-enter-active,
.pop-leave-active {
  transition:
    opacity 0.12s ease,
    transform 0.12s ease;
}
.pop-enter-from,
.pop-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.popover {
  position: fixed;
  z-index: var(--ui-z-popover);
  width: 280px;
  max-width: calc(100vw - 32px);
  box-sizing: border-box;
  background: #171717;
  border: 1px solid #2b2b2b;
  border-radius: 14px;
  padding: 14px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
}
.popover-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.popover-icon {
  color: #d68a34;
  flex-shrink: 0;
}
.popover-title {
  margin: 0;
  font-size: 0.82rem;
  font-weight: 700;
  color: #f2f2f2;
}
.popover-count {
  margin-left: auto;
  background: rgba(214, 138, 52, 0.16);
  color: #d68a34;
  font-size: 0.7rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 2px 8px;
  font-variant-numeric: tabular-nums;
}
.popover-divider {
  height: 1px;
  background: #262626;
  margin: 10px 0;
}
.log-form {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.log-date {
  flex: 1;
  min-width: 118px;
}
.log-note {
  flex: 2;
  min-width: 100px;
}
.log-date,
.log-note {
  background: #141414;
  border: 1px solid #2a2a2a;
  border-radius: 7px;
  color: #eee;
  padding: 7px 9px;
  font-size: 0.78rem;
  font-family: inherit;
  box-sizing: border-box;
}
.log-date:focus,
.log-note:focus,
.new-list-input:focus {
  outline: none;
  border-color: rgba(214, 138, 52, 0.5);
}
.popover-primary-btn {
  background: #d68a34;
  color: #14100a;
  border: none;
  border-radius: 7px;
  padding: 7px 12px;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
}
.popover-primary-btn:hover {
  filter: brightness(1.08);
}
.popover-primary-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
.rewatch-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 180px;
  overflow-y: auto;
}
.rewatch-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 2px;
  border-radius: 7px;
}
.rewatch-list li:hover {
  background: rgba(255, 255, 255, 0.04);
}
.rewatch-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #d68a34;
  flex-shrink: 0;
}
.rewatch-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.rewatch-date {
  font-size: 0.78rem;
  color: #eee;
  font-weight: 600;
}
.rewatch-note {
  font-size: 0.72rem;
  color: #888;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.remove-btn {
  background: none;
  border: none;
  color: #555;
  cursor: pointer;
  font-size: 0.95rem;
  line-height: 1;
  padding: 2px 4px;
  flex-shrink: 0;
}
.remove-btn:hover {
  color: #e57373;
}
.list-options {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 220px;
  overflow-y: auto;
}
.list-row {
  position: relative;
  display: flex;
  align-items: center;
}
.list-row-actions {
  display: flex;
  gap: 2px;
  margin-left: 2px;
  opacity: 0;
  transition: opacity 0.12s ease;
}
.list-row:hover .list-row-actions,
.list-row:focus-within .list-row-actions {
  opacity: 1;
}
@media (hover: none) {
  .list-row-actions {
    opacity: 1;
  }
}
.list-row-actions button {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: none;
  background: none;
  color: #888;
  font-size: 0.78rem;
  cursor: pointer;
}
.list-row-actions button:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #d68a34;
}
.list-row-actions button[title^="Delete"]:hover {
  color: #e57373;
}
.rename-input {
  flex: 1;
  background: #111;
  border: 1px solid #d68a34;
  border-radius: 8px;
  color: #fff;
  padding: 7px 10px;
  font: inherit;
  font-size: 0.82rem;
}
.rename-input:focus {
  outline: none;
  box-shadow: 0 0 0 2px rgba(214, 138, 52, 0.35);
}
.list-option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  color: #ddd;
  padding: 8px 7px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.82rem;
  font-family: inherit;
}
.list-option:hover {
  background: rgba(255, 255, 255, 0.06);
}
.list-option:disabled {
  opacity: 0.6;
  cursor: default;
}
.list-check {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  border: 1.5px solid #3a3a3a;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #14100a;
}
.list-option.checked .list-check {
  background: #d68a34;
  border-color: #d68a34;
}
.list-option-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.list-option-count {
  color: #777;
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.empty-hint {
  color: #777;
  font-size: 0.78rem;
  margin: 4px 0;
}
.new-list-row {
  display: flex;
  gap: 6px;
}
.new-list-input {
  flex: 1;
  min-width: 0;
  background: #0d0d0d;
  border: 1px solid #2a2a2a;
  border-radius: 7px;
  color: #eee;
  padding: 7px 9px;
  font-size: 0.78rem;
  font-family: inherit;
}
.extras-error {
  color: #e57373;
  font-size: 0.76rem;
  margin: 4px 0;
}
.manage-lists-btn {
  display: block;
  width: 100%;
  text-align: center;
  background: none;
  border: none;
  color: #d68a34;
  padding: 10px 0 0;
  margin-top: 8px;
  font-size: 0.76rem;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
}
.manage-lists-btn:hover {
  color: #eaa752;
}
</style>
