<script setup lang="ts">
import { usePageTitle } from "../state/pageTitle";
import { formatDisplayDate } from "../utils/dates";
import { activePriority, priorityLabel } from "../utils/priority";
import { computed, ref, watch, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  createGameNote,
  deleteGame,
  deleteGameNote,
  fetchGame,
  fetchGameVariants,
  fetchGameAchievements,
  fetchGameFieldChanges,
  fetchGameNote,
  fetchGames,
  renameGameNote,
  listGameNotes,
  saveGameNote,
  setFavorite,
  setResumeNote,
  setPlaytimeSeconds,
} from "../services/games";
import type { FieldChange } from "../services/games";
import { listCardsForGame, createCard } from "../services/cards";
import type { Card } from "../types/card";
import { fetchBounties } from "../services/bounties";
import type { Bounty } from "../services/bounties";
import { peekAdjacentGameId } from "../state/libraryNav";
import {
  uploadGameScreenshots,
  listGameScreenshots,
  deleteGameScreenshot,
  updateMediaItem,
  uploadGameFiles,
  listGameFiles,
  deleteGameFile,
  fetchGameMediaTrash,
  restoreGameMedia,
  fetchGameFileTrash,
  restoreGameFile,
} from "../services/media";
import type {
  MediaItem,
  GameFile,
  GameFileKind,
  TrashedMediaItem,
  TrashedGameFile,
} from "../services/media";
import {
  listGameProfiles,
  createGameProfile,
  renameGameProfile,
  updateGameProfile,
  deleteGameProfile,
  syncProfileWiseOldMan,
  fetchProfileStatHistory,
  listChecklist,
  createChecklistItem,
  updateChecklistItem,
  deleteChecklistItem,
  reorderChecklist,
} from "../services/gameProfiles";
import type {
  GameProfile,
  ChecklistItem,
  StatSnapshot,
} from "../services/gameProfiles";
import {
  fetchArchives,
  createArchive,
  addArchiveVersion,
  renameArchive,
  deleteArchive,
  deleteArchiveVersion,
  fetchWorldMaps,
  renderWorldMap,
  worldMapViewUrl,
  worldMapThumbnailUrl,
  fetchArchiveTrash,
  restoreArchive,
} from "../services/gameArchives";
import type {
  GameArchiveData,
  ArchiveVersion,
  WorldMapEntry,
  TrashedArchive,
} from "../services/gameArchives";
import UploadDropzone from "../components/UploadDropzone.vue";
import ViewUploadSidebar from "../components/ViewUploadSidebar.vue";
import SkeletonBlock from "../components/SkeletonBlock.vue";
import MediaTile from "../components/MediaTile.vue";
import {
  startTask,
  updateTask,
  completeTask,
  errorTask,
  addFeedItem,
  setTaskRetry,
} from "../state/taskProgress";
import type { Achievement, AchievementTier, Game } from "../types/game";
import GameFormModal from "../components/GameFormModal.vue";
import CollectionPickerModal from "../components/CollectionPickerModal.vue";
import BackButton from "../components/BackButton.vue";
import AccountChip from "../components/AccountChip.vue";
import { computeScore } from "../utils/scoring";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { useConfirm, usePrompt } from "../state/dialog";

const confirm = useConfirm();
const prompt = usePrompt();

const route = useRoute();
const router = useRouter();

function goBackToLibrary() {
  if (window.history.length > 1) {
    router.back();
  } else {
    router.push("/games");
  }
}

const game = ref<Game | null>(null);
usePageTitle(() => game.value?.title);
const loading = ref(true);
const error = ref<string | null>(null);
const showEditModal = ref(false);

const deleting = ref(false);
const deleteError = ref<string | null>(null);
const showDeleteConfirm = ref(false);

const noteNames = ref<string[]>([]);
const noteMode = ref<"list" | "view" | "editor">("list");
const viewingNoteName = ref<string | null>(null);
const viewingNoteContent = ref("");
const editingNoteName = ref<string | null>(null);
const draftName = ref("");
const draftContent = ref("");
const noteLoading = ref(false);
const noteSaving = ref(false);
const noteError = ref<string | null>(null);

const hasDraft = computed(
  () =>
    editingNoteName.value === null &&
    (draftName.value.trim() !== "" || draftContent.value.trim() !== ""),
);

const renderedNoteHtml = computed(
  () => marked.parse(viewingNoteContent.value || "") as string,
);

function startNewNote() {
  if (!hasDraft.value) {
    draftName.value = "";
    draftContent.value = "";
  }
  editingNoteName.value = null;
  noteMode.value = "editor";
}

async function viewNote(noteName: string) {
  if (!game.value) return;
  viewingNoteName.value = noteName;
  noteLoading.value = true;
  noteError.value = null;
  try {
    viewingNoteContent.value = await fetchGameNote(game.value.id, noteName);
    noteMode.value = "view";
  } catch (err) {
    noteError.value =
      err instanceof Error ? err.message : "Failed to load note";
  } finally {
    noteLoading.value = false;
  }
}

function editFromView() {
  if (!viewingNoteName.value) return;
  editingNoteName.value = viewingNoteName.value;
  draftName.value = viewingNoteName.value;
  draftContent.value = viewingNoteContent.value;
  noteMode.value = "editor";
}

function backToList() {
  noteMode.value = "list";
  viewingNoteName.value = null;
}

async function saveDraft() {
  if (!game.value) return;
  const newName = draftName.value.trim();
  if (!newName) {
    noteError.value = "Enter a note name first.";
    return;
  }

  noteSaving.value = true;
  noteError.value = null;

  try {
    if (editingNoteName.value) {
      const originalName = editingNoteName.value;
      await saveGameNote(game.value.id, originalName, draftContent.value);
      if (originalName !== newName) {
        await renameGameNote(game.value.id, originalName, newName);
      }
    } else {
      await createGameNote(game.value.id, newName, draftContent.value);
    }
    editingNoteName.value = null;
    draftName.value = "";
    draftContent.value = "";
    noteMode.value = "list";
    await loadNotes();
  } catch (err) {
    noteError.value =
      err instanceof Error ? err.message : "Failed to save note";
  } finally {
    noteSaving.value = false;
  }
}

async function deleteNote(noteName: string) {
  if (!game.value) return;

  noteSaving.value = true;
  noteError.value = null;

  try {
    await deleteGameNote(game.value.id, noteName);
    if (
      viewingNoteName.value === noteName ||
      editingNoteName.value === noteName
    ) {
      noteMode.value = "list";
      viewingNoteName.value = null;
      editingNoteName.value = null;
    }
    await loadNotes();
  } catch (err) {
    noteError.value =
      err instanceof Error ? err.message : "Failed to delete note";
  } finally {
    noteSaving.value = false;
  }
}

// Steam's "About This Game" section is rich HTML (headers, screenshots,
// gifs), sanitize it instead of stripping it down to plain text so that
// content survives
const descriptionHtml = computed(() => {
  if (!game.value?.description) return "";
  return DOMPurify.sanitize(game.value.description);
});

// resolved separately from game.value.parentGameId (which is only an id),
// see loadGame()
const parentGameTitle = ref<string | null>(null);
const RELATIONSHIP_LABELS: Record<string, string> = {
  mod: "Mod",
  modpack: "Modpack",
  expansion: "Expansion",
  dlc: "DLC",
  standalone_expansion: "Standalone Expansion",
  total_conversion: "Total Conversion",
};

// games whose parentGameId points at this one, e.g. Minecraft's page
// listing GTNH, Vanilla, Create Pack as variants of itself. The reverse of
// the parent-breadcrumb link above.
const variants = ref<Game[]>([]);

// --- Profiles (e.g. separate OSRS accounts) --------------------------------
// shared across the Notes checklist and the Screenshots/Clips/Soundtrack
// gallery, one "which account am I looking at" selector, not two, so a
// game with several accounts doesn't need everything dug through together.
const profiles = ref<GameProfile[]>([]);
const profilesLoadedFor = ref<string | null>(null);
// null = "General" (unscoped), the default, matching how most games (no
// multi-account concept) never need to touch this at all
const activeProfileId = ref<string | null>(null);
const newProfileName = ref("");
const profileError = ref<string | null>(null);

async function loadProfiles() {
  if (!game.value || profilesLoadedFor.value === game.value.id) return;
  try {
    profiles.value = await listGameProfiles(game.value.id);
    profilesLoadedFor.value = game.value.id;
  } catch (err) {
    profileError.value =
      err instanceof Error ? err.message : "Failed to load profiles";
  }
}

async function addProfile() {
  if (!game.value) return;
  const name = newProfileName.value.trim();
  if (!name) return;
  profileError.value = null;
  try {
    const created = await createGameProfile(game.value.id, name);
    profiles.value = [...profiles.value, created];
    newProfileName.value = "";
    activeProfileId.value = created.id;
  } catch (err) {
    profileError.value =
      err instanceof Error ? err.message : "Failed to create profile";
  }
}

async function promptRenameProfile(profile: GameProfile) {
  const name = await prompt({
    title: "Rename account",
    message: "Account name",
    defaultValue: profile.name,
    confirmLabel: "Rename",
  });
  if (name) void renameProfile(profile, name);
}

async function renameProfile(profile: GameProfile, name: string) {
  if (!game.value) return;
  const trimmed = name.trim();
  if (!trimmed || trimmed === profile.name) return;
  try {
    const updated = await renameGameProfile(game.value.id, profile.id, trimmed);
    const idx = profiles.value.findIndex((p) => p.id === profile.id);
    if (idx !== -1) profiles.value[idx] = updated;
  } catch (err) {
    profileError.value =
      err instanceof Error ? err.message : "Failed to rename profile";
  }
}

async function removeProfile(profile: GameProfile) {
  if (!game.value) return;
  try {
    await deleteGameProfile(game.value.id, profile.id);
    profiles.value = profiles.value.filter((p) => p.id !== profile.id);
    if (activeProfileId.value === profile.id) activeProfileId.value = null;
  } catch (err) {
    profileError.value =
      err instanceof Error ? err.message : "Failed to delete profile";
  }
}

// --- Accounts tab: selected account's note/stats/WiseOldMan sync -----------
// null activeProfileId means the sidebar's "General" entry, there's no
// GameProfile row for that, so note/stats/WiseOldMan simply don't apply
const selectedProfile = computed(
  () => profiles.value.find((p) => p.id === activeProfileId.value) ?? null,
);

const profileNoteDraft = ref("");
const profileNoteSaving = ref(false);
watch(selectedProfile, (profile) => {
  profileNoteDraft.value = profile?.note ?? "";
});

async function saveProfileNote() {
  if (!game.value || !selectedProfile.value) return;
  profileNoteSaving.value = true;
  try {
    const updated = await updateGameProfile(
      game.value.id,
      selectedProfile.value.id,
      {
        note: profileNoteDraft.value.trim() || null,
      },
    );
    const idx = profiles.value.findIndex((p) => p.id === updated.id);
    if (idx !== -1) profiles.value[idx] = updated;
  } catch (err) {
    profileError.value =
      err instanceof Error ? err.message : "Failed to save note";
  } finally {
    profileNoteSaving.value = false;
  }
}

interface StatRow {
  key: string;
  value: string;
}
const statRows = ref<StatRow[]>([]);
// display mode by default (a clean read-only grid), editing mode swaps in
// the raw label/value rows, entered explicitly rather than always showing
// 30+ input pairs for an account with a full WiseOldMan sync
const editingStats = ref(false);
watch(selectedProfile, (profile) => {
  statRows.value = profile
    ? Object.entries(profile.stats).map(([key, value]) => ({ key, value }))
    : [];
  editingStats.value = false;
});
function startEditStats() {
  if (selectedProfile.value) {
    statRows.value = Object.entries(selectedProfile.value.stats).map(
      ([key, value]) => ({ key, value }),
    );
  }
  editingStats.value = true;
}
function cancelEditStats() {
  if (selectedProfile.value) {
    statRows.value = Object.entries(selectedProfile.value.stats).map(
      ([key, value]) => ({ key, value }),
    );
  }
  editingStats.value = false;
}
function addStatRow() {
  statRows.value = [...statRows.value, { key: "", value: "" }];
}
function removeStatRow(index: number) {
  statRows.value = statRows.value.filter((_, i) => i !== index);
}
async function saveProfileStats() {
  if (!game.value || !selectedProfile.value) return;
  const stats: Record<string, string> = {};
  for (const row of statRows.value) {
    const key = row.key.trim();
    if (key) stats[key] = row.value.trim();
  }
  try {
    const updated = await updateGameProfile(
      game.value.id,
      selectedProfile.value.id,
      { stats },
    );
    const idx = profiles.value.findIndex((p) => p.id === updated.id);
    if (idx !== -1) profiles.value[idx] = updated;
    statRows.value = Object.entries(updated.stats).map(([key, value]) => ({
      key,
      value,
    }));
    editingStats.value = false;
    if (showStatHistory.value) await loadStatHistory();
  } catch (err) {
    profileError.value =
      err instanceof Error ? err.message : "Failed to save stats";
  }
}

const womUsername = ref("");
watch(selectedProfile, (profile) => {
  womUsername.value = profile?.wiseoldman_username ?? "";
});
const womSyncing = ref(false);
const womError = ref<string | null>(null);
async function syncWiseOldMan() {
  if (!game.value || !selectedProfile.value) return;
  const username = womUsername.value.trim();
  if (!username) {
    womError.value = "Enter a RuneScape username first.";
    return;
  }
  womSyncing.value = true;
  womError.value = null;
  try {
    const updated = await syncProfileWiseOldMan(
      game.value.id,
      selectedProfile.value.id,
      username,
    );
    const idx = profiles.value.findIndex((p) => p.id === updated.id);
    if (idx !== -1) profiles.value[idx] = updated;
    statRows.value = Object.entries(updated.stats).map(([key, value]) => ({
      key,
      value,
    }));
    await loadStatHistory();
  } catch (err) {
    womError.value =
      err instanceof Error ? err.message : "Failed to sync WiseOldMan";
  } finally {
    womSyncing.value = false;
  }
}

// --- Stat history: dated snapshots, so progression is visible over time ----
const statHistory = ref<StatSnapshot[]>([]);
const statHistoryLoading = ref(false);
const showStatHistory = ref(false);
const historyShowAll = ref(false);
const HISTORY_PAGE_SIZE = 12;
watch(selectedProfile, () => {
  statHistory.value = [];
  showStatHistory.value = false;
  historyShowAll.value = false;
});
async function loadStatHistory() {
  if (!game.value || !selectedProfile.value) return;
  statHistoryLoading.value = true;
  try {
    statHistory.value = await fetchProfileStatHistory(
      game.value.id,
      selectedProfile.value.id,
    );
  } catch {
    // history is a nice-to-have alongside the live stats, not worth
    // failing the whole Stats card over
  } finally {
    statHistoryLoading.value = false;
  }
}
async function toggleStatHistory() {
  showStatHistory.value = !showStatHistory.value;
  if (showStatHistory.value && !statHistory.value.length)
    await loadStatHistory();
}
function formatSnapshotDate(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// "on this day" gains, each snapshot compared against the next-older one
// in the list (statHistory is newest-first) using the raw xp/kc integers,
// not the display-string levels (a single level can span tens of
// thousands of XP, so diffing levels would be meaningless). A manually-
// edited snapshot has empty xp/kc, so it simply contributes no gain lines
//, nothing to divide by zero on, just nothing to show.
const statGains = computed<Record<string, string[]>>(() => {
  const gains: Record<string, string[]> = {};
  const list = statHistory.value;
  for (let i = 0; i < list.length; i++) {
    const current = list[i];
    const older = list[i + 1];
    if (!older) {
      gains[current.id] = [];
      continue;
    }
    const lines: string[] = [];
    for (const [skill, xp] of Object.entries(current.xp)) {
      const oldXp = older.xp[skill];
      if (oldXp !== undefined && xp > oldXp) {
        lines.push(`+${(xp - oldXp).toLocaleString()} ${skill} XP`);
      }
    }
    for (const [boss, kc] of Object.entries(current.kc)) {
      const oldKc = older.kc[boss];
      if (oldKc !== undefined && kc > oldKc) {
        lines.push(`+${kc - oldKc} ${boss} KC`);
      }
    }
    gains[current.id] = lines;
  }
  return gains;
});
const visibleHistory = computed(() =>
  historyShowAll.value
    ? statHistory.value
    : statHistory.value.slice(0, HISTORY_PAGE_SIZE),
);

// grouped for display: Overall/Combat as headline tiles, boss kill counts
// (WOM always formats these as "N KC") in their own section instead of
// mixed in alphabetically with skill levels
const HEADLINE_STAT_KEYS = ["Overall", "Combat"];
const headlineStats = computed(() =>
  HEADLINE_STAT_KEYS.filter((key) => selectedProfile.value?.stats[key]).map(
    (key) => ({
      key,
      value: selectedProfile.value!.stats[key],
    }),
  ),
);
const skillStats = computed(() =>
  Object.entries(selectedProfile.value?.stats ?? {}).filter(
    ([key, value]) =>
      !HEADLINE_STAT_KEYS.includes(key) && !value.endsWith(" KC"),
  ),
);
const bossStats = computed(() =>
  Object.entries(selectedProfile.value?.stats ?? {}).filter(([, value]) =>
    value.endsWith(" KC"),
  ),
);

// real OSRS Wiki icons for skills/Overall/Combat, the wiki's own
// "<Name>_icon.png" naming is reliable for these (verified: 22/23 skills
// match directly, "Runecrafting" is the one renamed in-game to
// "Runecraft"). Boss/activity icons on the same wiki follow no reliable
// pattern (spot-checked well under half of ~60 names resolve), so those
// get one shared generic icon instead of a wall of broken images.
const SKILL_ICON_OVERRIDES: Record<string, string> = {
  Runecrafting: "Runecraft",
  Overall: "Stats",
};
function skillIconUrl(label: string): string {
  const name = SKILL_ICON_OVERRIDES[label] ?? label;
  return `https://oldschool.runescape.wiki/images/${encodeURIComponent(name.replace(/ /g, "_"))}_icon.png`;
}

// --- Accounts tab: gallery, split by kind + free-form category (tag) -------
const ACCOUNT_MEDIA_KINDS = ["screenshot", "clip", "soundtrack"] as const;
const accountMediaKind =
  ref<(typeof ACCOUNT_MEDIA_KINDS)[number]>("screenshot");
const accountMediaCategory = ref<string | null>(null);
watch(activeProfileId, () => {
  accountMediaCategory.value = null;
});
const accountMediaByKind = computed(() =>
  mediaItems.value.filter((m) => m.kind === accountMediaKind.value),
);
// distinct tags present among this account's items of the current kind,
// e.g. "Levelups"/"Quests"/"Achievement diary" for OSRS screenshots, built
// from whatever tags you've actually used rather than a fixed list
const accountMediaCategories = computed(() => {
  const set = new Set<string>();
  for (const item of accountMediaByKind.value) {
    for (const tag of item.tags) set.add(tag);
  }
  return [...set].sort();
});
const accountMediaFiltered = computed(() =>
  accountMediaCategory.value
    ? accountMediaByKind.value.filter((m) =>
        m.tags.includes(accountMediaCategory.value as string),
      )
    : accountMediaByKind.value,
);

// --- Checklist (per-game, or per-profile when one account is selected) -----
const checklistItems = ref<ChecklistItem[]>([]);
const checklistLoading = ref(false);
const checklistError = ref<string | null>(null);
const newChecklistText = ref("");
const editingItemId = ref<string | null>(null);
const editingText = ref("");

const checklistProgress = computed(() => {
  const real = checklistItems.value.filter((i) => !i.is_header);
  return { done: real.filter((i) => i.done).length, total: real.length };
});

// groups the flat, already-ordered list into sections at each header row,
// a header just being another row in the same sort order, not a separate
// table, keeps "move an item above/below a header" a plain reorder
interface ChecklistSection {
  header: ChecklistItem | null;
  items: ChecklistItem[];
}
const checklistSections = computed<ChecklistSection[]>(() => {
  const sections: ChecklistSection[] = [{ header: null, items: [] }];
  for (const item of checklistItems.value) {
    if (item.is_header) {
      sections.push({ header: item, items: [] });
    } else {
      sections[sections.length - 1].items.push(item);
    }
  }
  return sections.filter((s) => s.header !== null || s.items.length > 0);
});

// collapsed section state, per game, remembered across visits
const collapsedSections = ref<Set<string>>(new Set());
function collapsedStorageKey(gameId: string) {
  return `checklist-collapsed-${gameId}`;
}
function loadCollapsedSections() {
  if (!game.value) return;
  try {
    const raw = localStorage.getItem(collapsedStorageKey(game.value.id));
    collapsedSections.value = new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    collapsedSections.value = new Set();
  }
}
function saveCollapsedSections() {
  if (!game.value) return;
  try {
    localStorage.setItem(
      collapsedStorageKey(game.value.id),
      JSON.stringify([...collapsedSections.value]),
    );
  } catch {
    // best-effort, a checklist with no persisted collapse state just
    // starts fully expanded next time, not worth failing over
  }
}
function toggleSectionCollapsed(headerId: string) {
  if (collapsedSections.value.has(headerId))
    collapsedSections.value.delete(headerId);
  else collapsedSections.value.add(headerId);
  collapsedSections.value = new Set(collapsedSections.value);
  saveCollapsedSections();
}
function sectionProgress(section: ChecklistSection) {
  return {
    done: section.items.filter((i) => i.done).length,
    total: section.items.length,
  };
}

async function loadChecklist() {
  if (!game.value) return;
  checklistLoading.value = true;
  checklistError.value = null;
  loadCollapsedSections();
  try {
    checklistItems.value = await listChecklist(
      game.value.id,
      activeProfileId.value,
    );
  } catch (err) {
    checklistError.value =
      err instanceof Error ? err.message : "Failed to load checklist";
  } finally {
    checklistLoading.value = false;
  }
}

async function addChecklistItem() {
  if (!game.value) return;
  const text = newChecklistText.value.trim();
  if (!text) return;
  try {
    const created = await createChecklistItem(
      game.value.id,
      text,
      activeProfileId.value,
    );
    checklistItems.value = [...checklistItems.value, created];
    newChecklistText.value = "";
  } catch (err) {
    checklistError.value =
      err instanceof Error ? err.message : "Failed to add item";
  }
}

async function addChecklistSection() {
  if (!game.value) return;
  const name = await prompt({
    title: "New section",
    message: 'Section name (e.g. "Quest cape reqs")',
    confirmLabel: "Add",
  });
  const text = name?.trim();
  if (!text) return;
  createChecklistItem(game.value.id, text, activeProfileId.value, true)
    .then((created) => {
      checklistItems.value = [...checklistItems.value, created];
    })
    .catch((err) => {
      checklistError.value =
        err instanceof Error ? err.message : "Failed to add section";
    });
}

async function toggleChecklistItem(item: ChecklistItem) {
  if (!game.value) return;
  const next = !item.done;
  item.done = next;
  try {
    await updateChecklistItem(game.value.id, item.id, { done: next });
  } catch (err) {
    item.done = !next;
    checklistError.value =
      err instanceof Error ? err.message : "Failed to update item";
  }
}

function startEditItem(item: ChecklistItem) {
  editingItemId.value = item.id;
  editingText.value = item.text;
}

async function commitEditItem(item: ChecklistItem) {
  if (!game.value) return;
  const text = editingText.value.trim();
  editingItemId.value = null;
  if (!text || text === item.text) return;
  item.text = text;
  try {
    await updateChecklistItem(game.value.id, item.id, { text });
  } catch (err) {
    checklistError.value =
      err instanceof Error ? err.message : "Failed to rename item";
  }
}

function cancelEditItem() {
  editingItemId.value = null;
}

async function moveChecklistItem(item: ChecklistItem, direction: -1 | 1) {
  if (!game.value) return;
  const list = checklistItems.value;
  const index = list.indexOf(item);
  const targetIndex = index + direction;
  if (index === -1 || targetIndex < 0 || targetIndex >= list.length) return;
  const reordered = [...list];
  [reordered[index], reordered[targetIndex]] = [
    reordered[targetIndex],
    reordered[index],
  ];
  checklistItems.value = reordered;
  try {
    await reorderChecklist(
      game.value.id,
      activeProfileId.value,
      reordered.map((i) => i.id),
    );
  } catch (err) {
    checklistError.value =
      err instanceof Error ? err.message : "Failed to reorder checklist";
    await loadChecklist();
  }
}

async function removeChecklistItem(item: ChecklistItem) {
  if (!game.value) return;
  try {
    await deleteChecklistItem(game.value.id, item.id);
    checklistItems.value = checklistItems.value.filter((i) => i.id !== item.id);
  } catch (err) {
    checklistError.value =
      err instanceof Error ? err.message : "Failed to delete item";
  }
}

// the Accounts tab's sidebar selection, reload that account's checklist
// and media whenever it changes
watch(activeProfileId, () => {
  if (activeTab.value !== "Accounts") return;
  void loadChecklist();
  void reloadMediaForCurrentTab();
});

async function loadGame(id: string) {
  loading.value = true;
  error.value = null;
  try {
    const fetched = await fetchGame(id);
    // the route can change again while this was in flight (fast
    // click-through on the parent breadcrumb or a variant card), a
    // slower response for the game we've already navigated away from
    // must not overwrite the newer one that may have already loaded
    if (route.params.id !== id) return;
    game.value = fetched;
    if (game.value) {
      try {
        const achievements = await fetchGameAchievements(id);
        if (route.params.id !== id) return;
        game.value.achievements = achievements;
        game.value.achievementTotal = achievements.length;
        game.value.achievementPercent = achievements.length
          ? Math.round(
              (achievements.filter((a) => a.unlockedAt !== null).length /
                achievements.length) *
                100,
            )
          : 0;
      } catch {
        // achievements are a nice-to-have overlay, a failure here
        // shouldn't block the rest of the game page from rendering
      }
      mediaItems.value = [];
      mediaLoadedFor.value = null;
      mediaTrash.value = [];
      showMediaTrash.value = false;
      fieldChanges.value = [];
      fieldChangesError.value = null;
      docsFiles.value = [];
      modpackFiles.value = [];
      filesLoaded.value = { doc: null, modpack: null };
      docsTrash.value = [];
      modpackTrash.value = [];
      showDocsTrash.value = false;
      showModpackTrash.value = false;
      saveArchives.value = [];
      saveArchivesLoaded.value = false;
      saveTrash.value = [];
      showSaveTrash.value = false;
      stopWorldMapPolling();
      worldMaps.value = [];
      worldMapsLoaded.value = false;
      worldTrash.value = [];
      showWorldTrash.value = false;
      activeMapArchiveId.value = null;
      profiles.value = [];
      profilesLoadedFor.value = null;
      activeProfileId.value = null;
      checklistItems.value = [];
      if (
        activeTab.value === "Screenshots" ||
        activeTab.value === "Clips" ||
        activeTab.value === "Soundtrack"
      ) {
        void loadProfiles();
        void loadMedia();
        void refreshMediaTrash();
      }
      if (activeTab.value === "Accounts") {
        void loadProfiles();
        void loadChecklist();
        void reloadMediaForCurrentTab();
      }
      if (activeTab.value === "Saves") {
        void refreshSaveArchives();
        void refreshSaveTrash();
      }
      if (activeTab.value === "Docs") {
        void loadGameFiles("doc");
        void refreshFileTrash("doc");
      }
      if (activeTab.value === "World Map") {
        void loadGameFiles("modpack");
        void refreshFileTrash("modpack");
        void refreshWorldMaps();
        void refreshWorldTrash();
      }

      parentGameTitle.value = null;
      if (game.value.parentGameId) {
        try {
          const parent = await fetchGame(game.value.parentGameId);
          parentGameTitle.value = parent?.title ?? null;
        } catch {
          // breadcrumb just doesn't show a name, not worth failing the page
        }
      }

      variants.value = [];
      try {
        variants.value = await fetchGameVariants(id);
      } catch {
        // variants section just doesn't show, not worth failing the page
      }

      void loadRelatedBounties(id);
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load game";
  } finally {
    loading.value = false;
  }
}

async function onGameSaved() {
  showEditModal.value = false;
  await loadGame(route.params.id as string);
}

// --- resume note ("where I left off") ---------------------------------
const resumeNoteDraft = ref("");
const resumeNoteEditing = ref(false);
const resumeNoteSaving = ref(false);
const resumeNoteError = ref<string | null>(null);
watch(
  () => game.value?.id,
  () => {
    resumeNoteDraft.value = game.value?.resumeNote ?? "";
    resumeNoteEditing.value = false;
    resumeNoteError.value = null;
  },
);
function startEditResumeNote() {
  resumeNoteDraft.value = game.value?.resumeNote ?? "";
  resumeNoteEditing.value = true;
}
async function saveResumeNote() {
  if (!game.value) return;
  resumeNoteSaving.value = true;
  resumeNoteError.value = null;
  try {
    const trimmed = resumeNoteDraft.value.trim() || null;
    const updated = await setResumeNote(game.value.id, trimmed);
    game.value.resumeNote = updated.resumeNote;
    resumeNoteEditing.value = false;
  } catch (err) {
    resumeNoteError.value =
      err instanceof Error ? err.message : "Failed to save note";
  } finally {
    resumeNoteSaving.value = false;
  }
}

// --- quick playtime logging --------------------------------------------
const loggingPlaytime = ref(false);
async function logPlaytime(minutes: number) {
  if (!game.value || loggingPlaytime.value) return;
  loggingPlaytime.value = true;
  try {
    const currentSeconds = game.value.platforms.reduce(
      (sum, p) => sum + p.playtimeMinutes * 60,
      0,
    );
    const updated = await setPlaytimeSeconds(
      game.value.id,
      currentSeconds + minutes * 60,
    );
    game.value.platforms = updated.platforms;
    game.value.lastPlayedAt = updated.lastPlayedAt;
  } catch {
    // the button just doesn't reflect the change, not worth a whole error banner for this
  } finally {
    loggingPlaytime.value = false;
  }
}

// --- similar games in the library, by shared tags -----------------------
// fetched once per page visit (not per-game), cheap enough at this
// library's scale and avoids a second heavier endpoint just for this
const libraryGames = ref<Game[]>([]);
async function loadLibraryForSimilar() {
  try {
    libraryGames.value = await fetchGames();
  } catch {
    // similar-games section just doesn't show, not worth failing the page
  }
}
onMounted(() => void loadLibraryForSimilar());

const similarGames = computed(() => {
  if (!game.value || !libraryGames.value.length) return [];
  const tagSet = new Set(game.value.tags);
  if (!tagSet.size) return [];
  return libraryGames.value
    .filter((g) => g.id !== game.value!.id)
    .map((g) => ({
      game: g,
      shared: g.tags.filter((t) => tagSet.has(t)).length,
    }))
    .filter((e) => e.shared > 0)
    .sort((a, b) => b.shared - a.shared)
    .slice(0, 8)
    .map((e) => e.game);
});

// --- related bounty(ies) targeting this game ----------------------------
const relatedBounties = ref<Bounty[]>([]);
async function loadRelatedBounties(gameId: string) {
  try {
    const active = await fetchBounties({ status: "active" });
    relatedBounties.value = active.filter((b) => b.game_id === gameId);
  } catch {
    relatedBounties.value = [];
  }
}

// --- J/K next/prev game, mirroring the library grid's own shortcut -------
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}
function onDetailKeydown(e: KeyboardEvent) {
  if (isTypingTarget(e.target)) return;
  if (
    showEditModal.value ||
    showDeleteConfirm.value ||
    showCollectionPicker.value
  )
    return;
  if (!game.value) return;
  if (e.key === "j" || e.key === "k") {
    const nextId = peekAdjacentGameId(game.value.id, e.key === "j" ? 1 : -1);
    if (nextId) {
      e.preventDefault();
      router.push(`/games/${nextId}`);
    }
  }
}
window.addEventListener("keydown", onDetailKeydown);
onUnmounted(() => window.removeEventListener("keydown", onDetailKeydown));

async function toggleFavorite() {
  if (!game.value) return;
  const next = !game.value.favorite;
  game.value.favorite = next;
  try {
    await setFavorite(game.value.id, next);
  } catch {
    game.value.favorite = !next;
  }
}

const showCollectionPicker = ref(false);

async function onCollectionAdded() {
  await loadGame(route.params.id as string);
}

function onDeleteFromModal() {
  showEditModal.value = false;
  deleteError.value = null;
  showDeleteConfirm.value = true;
}

async function confirmDelete() {
  if (!game.value) return;
  deleting.value = true;
  deleteError.value = null;
  try {
    await deleteGame(game.value.id);
    router.push("/games");
  } catch (err) {
    deleteError.value =
      err instanceof Error ? err.message : "Failed to delete game";
  } finally {
    deleting.value = false;
  }
}

async function loadNotes() {
  if (!game.value) {
    noteNames.value = [];
    return;
  }
  noteLoading.value = true;
  noteError.value = null;
  try {
    noteNames.value = await listGameNotes(game.value.id);
  } catch (err) {
    noteError.value =
      err instanceof Error ? err.message : "Failed to load notes";
  } finally {
    noteLoading.value = false;
  }
}

// re-fetches automatically if you ever navigate from one game's page
// straight to another, not just on the first load
watch(() => route.params.id as string, loadGame, { immediate: true });
watch(
  () => game.value?.id,
  () => {
    if (game.value) {
      void loadNotes();
    }
  },
);

const recentActivity = computed(() => game.value?.lastPlayedAt ?? null);

const tally = computed(() => (game.value ? computeScore(game.value) : null));

const statsPlaytimeMinutes = computed(() =>
  game.value
    ? game.value.platforms.reduce((sum, p) => sum + p.playtimeMinutes, 0)
    : 0,
);
const statsPlaytimeLabel = computed(() => {
  const minutes = statsPlaytimeMinutes.value;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours === 0) return `${mins}m`;
  return `${hours}h ${mins}m`;
});
const unlockedAchievements = computed(
  () => game.value?.achievements.filter((a) => a.unlockedAt !== null) ?? [],
);
const firstUnlockedAt = computed(() => {
  const dates = unlockedAchievements.value
    .map((a) => a.unlockedAt)
    .filter((d): d is string => d !== null);
  return dates.length
    ? dates.reduce((earliest, d) => (d < earliest ? d : earliest))
    : null;
});
const lastUnlockedAt = computed(() => {
  const dates = unlockedAchievements.value
    .map((a) => a.unlockedAt)
    .filter((d): d is string => d !== null);
  return dates.length
    ? dates.reduce((latest, d) => (d > latest ? d : latest))
    : null;
});
function formatStatsDate(iso: string | null): string {
  if (!iso) return "N/A";
  return formatDisplayDate(iso, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const tabs = [
  "Overview",
  "Achievements",
  "Screenshots",
  "Clips",
  "Soundtrack",
  "Saves",
  "Docs",
  "World Map",
  "Notes",
  "Accounts",
  "Stats",
  "History",
  "Collector Card",
] as const;
const activeTab = ref<(typeof tabs)[number]>("Overview");

// World Map only makes sense for Minecraft (BlueMap is Minecraft-specific)
//, checks this game's own title, and its parent's if it's a mod/modpack
// variant (e.g. "GregTech: New Horizons" has no "Minecraft" in its own
// title, but its parent breadcrumb does).
const isMinecraftGame = computed(() => {
  const title = game.value?.title ?? "";
  const parentTitle = parentGameTitle.value ?? "";
  return /minecraft/i.test(title) || /minecraft/i.test(parentTitle);
});
const isCompletedGame = computed(
  () => game.value?.status === "beaten" || game.value?.status === "mastered",
);
const visibleTabs = computed(() =>
  tabs.filter(
    (tab) =>
      (tab !== "World Map" || isMinecraftGame.value) &&
      (tab !== "Accounts" || game.value?.profilesEnabled) &&
      (tab !== "Collector Card" || isCompletedGame.value),
  ),
);

// Screenshots/Clips/Soundtrack/Saves/Docs/World Map all share the same
// RomM-style layout: a small View/Upload sidebar instead of the dropzone
// always sitting at the top. One shared ref is enough since only one of
// these panels is ever visible at a time, reset to 'view' on every tab
// switch so leaving a panel mid-upload-mode doesn't leak into the next one.
const panelMode = ref<"view" | "upload">("view");
watch(activeTab, () => {
  panelMode.value = "view";
});
function onDropError(message: string) {
  filesError.value = message;
  mediaError.value = message;
}
function onPreviewMedia(url: string) {
  if (
    activeTab.value === "Screenshots" ||
    (activeTab.value === "Accounts" && accountMediaKind.value === "screenshot")
  ) {
    lightboxUrl.value = url;
  }
}

watch(isMinecraftGame, (isMinecraft) => {
  if (!isMinecraft && activeTab.value === "World Map")
    activeTab.value = "Overview";
});

watch(
  () => game.value?.profilesEnabled,
  (enabled) => {
    if (!enabled && activeTab.value === "Accounts")
      activeTab.value = "Overview";
  },
);

// --- Screenshots / Clips / Soundtrack --------------------------------------
// same backend media store (kind is auto-classified by content-type on
// upload), split into three tabs client-side by filtering on `kind`
const mediaItems = ref<MediaItem[]>([]);
const mediaLoading = ref(false);
const mediaError = ref<string | null>(null);
const mediaLoadedFor = ref<string | null>(null);
const screenshots = computed(() =>
  mediaItems.value.filter((m) => m.kind === "screenshot"),
);
const clips = computed(() => mediaItems.value.filter((m) => m.kind === "clip"));
const soundtrackItems = computed(() =>
  mediaItems.value.filter((m) => m.kind === "soundtrack"),
);
const lightboxUrl = ref<string | null>(null);

// no args: every item regardless of account (the plain Screenshots/Clips/
// Soundtrack tabs, which have no account concept of their own). Passed
// explicitly by the Accounts tab to scope to one account or "General".
async function loadMedia(profileId?: string | null, unscopedOnly = false) {
  if (!game.value) return;
  mediaLoading.value = true;
  mediaError.value = null;
  try {
    mediaItems.value = await listGameScreenshots(
      game.value.id,
      profileId,
      unscopedOnly,
    );
    mediaLoadedFor.value = game.value.id;
  } catch (err) {
    mediaError.value =
      err instanceof Error ? err.message : "Failed to load media";
  } finally {
    mediaLoading.value = false;
  }
}

watch(activeTab, (tab) => {
  if (tab === "Screenshots" || tab === "Clips" || tab === "Soundtrack") {
    void loadProfiles();
    void loadMedia();
    void refreshMediaTrash();
  }
  if (tab === "Accounts") {
    void loadProfiles();
    void loadChecklist();
    void reloadMediaForCurrentTab();
  }
});

// media is scoped to an account only from within the Accounts tab, the
// plain Screenshots/Clips/Soundtrack tabs upload unscoped, same as any
// game without accounts enabled
function reloadMediaForCurrentTab() {
  mediaLoadedFor.value = null;
  if (activeTab.value === "Accounts") {
    return loadMedia(activeProfileId.value, activeProfileId.value === null);
  }
  return loadMedia();
}

const uploadingMedia = ref(false);
async function onMediaFilesSelected(files: File[]) {
  if (!files.length || !game.value) return;
  const gameId = game.value.id;
  uploadingMedia.value = true;
  const taskId = startTask(
    `Uploading ${files.length} file${files.length === 1 ? "" : "s"}`,
    100,
  );
  const uploadProfileId =
    activeTab.value === "Accounts" ? activeProfileId.value : null;

  const attempt = async () => {
    try {
      const results = await uploadGameScreenshots(
        gameId,
        files,
        (fraction, speedLabel) =>
          updateTask(taskId, Math.round(fraction * 100), undefined, speedLabel),
        uploadProfileId,
      );
      for (const r of results) {
        addFeedItem(
          taskId,
          r.status === "saved"
            ? `${r.filename} uploaded`
            : `${r.filename}: ${r.reason ?? "rejected"}`,
        );
      }
      const saved = results.filter((r) => r.status === "saved").length;
      const summary = `${saved} uploaded${results.length > saved ? `, ${results.length - saved} rejected` : ""}`;
      if (saved === 0) {
        errorTask(taskId, summary);
      } else {
        completeTask(taskId, summary);
      }
      await reloadMediaForCurrentTab();
    } catch (err) {
      // a network blip shouldn't force re-picking files from scratch
      errorTask(taskId, err instanceof Error ? err.message : "Upload failed");
      setTaskRetry(taskId, () => void attempt());
    } finally {
      uploadingMedia.value = false;
    }
  };
  await attempt();
}

async function removeMedia(item: MediaItem) {
  if (!game.value) return;
  try {
    await deleteGameScreenshot(game.value.id, item.kind, item.filename);
    mediaItems.value = mediaItems.value.filter((m) => m !== item);
    await refreshMediaTrash();
  } catch (err) {
    mediaError.value = err instanceof Error ? err.message : "Failed to delete";
  }
}

// --- Trash: soft-deleted media stays recoverable for 7 days before the
// background sweep purges it for good (features/trash/sweep.py) ----------
const mediaTrash = ref<TrashedMediaItem[]>([]);
const showMediaTrash = ref(false);
const trashedScreenshots = computed(() =>
  mediaTrash.value.filter((m) => m.kind === "screenshot"),
);
const trashedClips = computed(() =>
  mediaTrash.value.filter((m) => m.kind === "clip"),
);
const trashedSoundtrack = computed(() =>
  mediaTrash.value.filter((m) => m.kind === "soundtrack"),
);
const activeTabTrash = computed(() => {
  if (activeTab.value === "Screenshots") return trashedScreenshots.value;
  if (activeTab.value === "Clips") return trashedClips.value;
  if (activeTab.value === "Soundtrack") return trashedSoundtrack.value;
  return [];
});

async function refreshMediaTrash() {
  if (!game.value) return;
  try {
    mediaTrash.value = await fetchGameMediaTrash(game.value.id);
  } catch {
    // trash listing failing silently isn't worth blocking the main view
  }
}

async function restoreMediaItem(item: TrashedMediaItem) {
  if (!game.value) return;
  try {
    await restoreGameMedia(game.value.id, item.kind, item.filename);
    mediaLoadedFor.value = null;
    await loadMedia();
    await refreshMediaTrash();
  } catch (err) {
    mediaError.value = err instanceof Error ? err.message : "Failed to restore";
  }
}

async function saveMediaItem(
  item: MediaItem,
  tags: string[],
  note: string | null,
  linkedAchievementId: string | null,
  profileId: string | null,
) {
  if (!game.value) return;
  try {
    const updated = await updateMediaItem(game.value.id, item.id, {
      tags,
      note,
      linked_achievement_id: linkedAchievementId,
      profile_id: profileId,
    });
    const index = mediaItems.value.findIndex((m) => m.id === item.id);
    if (index !== -1) mediaItems.value[index] = updated;
    // the item may have just moved out of the Accounts tab's currently
    // selected scope (or into it), refetch so the gallery reflects that
    if (
      activeTab.value === "Accounts" &&
      (activeProfileId.value !== null || profileId !== null)
    ) {
      await reloadMediaForCurrentTab();
    }
  } catch (err) {
    mediaError.value = err instanceof Error ? err.message : "Failed to save";
  }
}

// --- Docs / Modpack ---------------------------------------------------------
// generic flat-file attachments (any format), Saves/World Save moved to
// named, versioned archives below; docs/modpacks stay simple since
// naming/history doesn't add much for a single manual or modpack zip
type FlatFileKind = Extract<GameFileKind, "doc" | "modpack">;
const docsFiles = ref<GameFile[]>([]);
const modpackFiles = ref<GameFile[]>([]);
const filesLoaded = ref<Record<FlatFileKind, string | null>>({
  doc: null,
  modpack: null,
});
const filesError = ref<string | null>(null);
const uploadingFiles = ref(false);

const FILE_REFS: Record<FlatFileKind, typeof docsFiles> = {
  doc: docsFiles,
  modpack: modpackFiles,
};
function filesRefFor(kind: FlatFileKind) {
  return FILE_REFS[kind];
}

async function loadGameFiles(kind: FlatFileKind) {
  if (!game.value || filesLoaded.value[kind] === game.value.id) return;
  filesError.value = null;
  try {
    filesRefFor(kind).value = await listGameFiles(game.value.id, kind);
    filesLoaded.value[kind] = game.value.id;
  } catch (err) {
    filesError.value =
      err instanceof Error ? err.message : "Failed to load files";
  }
}

watch(activeTab, (tab) => {
  if (tab === "Docs") {
    void loadGameFiles("doc");
    void refreshFileTrash("doc");
  }
  if (tab === "Saves") {
    void refreshSaveArchives();
    void refreshSaveTrash();
  }
  if (tab === "World Map") {
    void loadGameFiles("modpack");
    void refreshFileTrash("modpack");
    void refreshWorldMaps();
    void refreshWorldTrash();
  }
  if (tab === "History") {
    void loadFieldChanges();
  }
  if (tab === "Collector Card") {
    void loadGameCards();
  }
});

const gameCards = ref<Card[]>([]);
const gameCardsLoading = ref(false);
const creatingCard = ref(false);
const cardTabError = ref<string | null>(null);
async function loadGameCards() {
  if (!game.value) return;
  gameCardsLoading.value = true;
  try {
    gameCards.value = await listCardsForGame(game.value.id);
  } finally {
    gameCardsLoading.value = false;
  }
}
async function createCardForGame() {
  if (!game.value) return;
  creatingCard.value = true;
  cardTabError.value = null;
  try {
    const card = await createCard({ gameId: game.value.id });
    router.push(`/cards/${card.id}`);
  } catch (err) {
    cardTabError.value =
      err instanceof Error ? err.message : "Failed to create card";
  } finally {
    creatingCard.value = false;
  }
}

// --- metadata history: which fields a manual edit or a metadata
// search/refresh actually changed, and when (see FIELD_CHANGE_TRACKED_FIELDS
// in api/routes/games.py for exactly which fields are tracked) -----------
const fieldChanges = ref<FieldChange[]>([]);
const fieldChangesLoading = ref(false);
const fieldChangesError = ref<string | null>(null);
async function loadFieldChanges() {
  if (!game.value) return;
  fieldChangesLoading.value = true;
  fieldChangesError.value = null;
  try {
    fieldChanges.value = await fetchGameFieldChanges(game.value.id);
  } catch (err) {
    fieldChangesError.value =
      err instanceof Error ? err.message : "Failed to load history";
  } finally {
    fieldChangesLoading.value = false;
  }
}
const FIELD_CHANGE_LABELS: Record<string, string> = {
  developer: "Developer",
  publisher: "Publisher",
  series: "Series",
  tags: "Tags",
  features: "Features",
  description: "Description",
  age_rating: "Age rating",
  release_date: "Release date",
  time_to_beat_hours: "Time to beat",
};
function formatFieldChangeDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

async function onGameFilesSelected(files: File[], kind: FlatFileKind) {
  if (!files.length || !game.value) return;
  const gameId = game.value.id;
  uploadingFiles.value = true;
  const taskId = startTask(
    `Uploading ${files.length} file${files.length === 1 ? "" : "s"}`,
    100,
  );

  const attempt = async () => {
    try {
      const results = await uploadGameFiles(
        gameId,
        kind,
        files,
        (fraction, speedLabel) =>
          updateTask(taskId, Math.round(fraction * 100), undefined, speedLabel),
      );
      for (const r of results) {
        addFeedItem(
          taskId,
          r.status === "saved"
            ? `${r.filename} uploaded`
            : `${r.filename}: ${r.reason ?? "rejected"}`,
        );
      }
      const saved = results.filter((r) => r.status === "saved").length;
      const summary = `${saved} uploaded${results.length > saved ? `, ${results.length - saved} rejected` : ""}`;
      if (saved === 0) {
        errorTask(taskId, summary);
      } else {
        completeTask(taskId, summary);
      }
      filesLoaded.value[kind] = null;
      await loadGameFiles(kind);
    } catch (err) {
      errorTask(taskId, err instanceof Error ? err.message : "Upload failed");
      setTaskRetry(taskId, () => void attempt());
    } finally {
      uploadingFiles.value = false;
    }
  };
  await attempt();
}

async function removeGameFile(kind: FlatFileKind, file: GameFile) {
  if (!game.value) return;
  try {
    await deleteGameFile(game.value.id, kind, file.filename);
    filesRefFor(kind).value = filesRefFor(kind).value.filter((f) => f !== file);
    await refreshFileTrash(kind);
  } catch (err) {
    filesError.value = err instanceof Error ? err.message : "Failed to delete";
  }
}

// --- Trash: soft-deleted docs/modpacks stay recoverable for 7 days before
// the background sweep purges them for good (features/trash/sweep.py) ----
const docsTrash = ref<TrashedGameFile[]>([]);
const modpackTrash = ref<TrashedGameFile[]>([]);
const showDocsTrash = ref(false);
const showModpackTrash = ref(false);
const FILE_TRASH_REFS: Record<FlatFileKind, typeof docsTrash> = {
  doc: docsTrash,
  modpack: modpackTrash,
};
function fileTrashRefFor(kind: FlatFileKind) {
  return FILE_TRASH_REFS[kind];
}

async function refreshFileTrash(kind: FlatFileKind) {
  if (!game.value) return;
  try {
    fileTrashRefFor(kind).value = await fetchGameFileTrash(game.value.id, kind);
  } catch {
    // trash listing failing silently isn't worth blocking the main view
  }
}

async function restoreFileItem(kind: FlatFileKind, item: TrashedGameFile) {
  if (!game.value) return;
  try {
    await restoreGameFile(game.value.id, kind, item.filename);
    filesLoaded.value[kind] = null;
    await loadGameFiles(kind);
    await refreshFileTrash(kind);
  } catch (err) {
    filesError.value = err instanceof Error ? err.message : "Failed to restore";
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatArchiveDate(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// --- Saves (named, versioned archives) --------------------------------------
const saveArchives = ref<GameArchiveData[]>([]);
const saveArchivesLoaded = ref(false);
const expandedSaveId = ref<string | null>(null);
const saveUploading = ref<Set<string>>(new Set()); // archive id, or '' for "new save"

async function refreshSaveArchives() {
  if (!game.value) return;
  try {
    saveArchives.value = await fetchArchives(game.value.id, "save");
    saveArchivesLoaded.value = true;
  } catch (err) {
    filesError.value =
      err instanceof Error ? err.message : "Failed to load saves";
  }
}

async function onNewSaveSelected(files: File[]) {
  const file = files[0];
  if (!file || !game.value) return;
  const gameId = game.value.id;
  const name = await prompt({
    title: "Name this save",
    message: "Save name",
    defaultValue: file.name.replace(/\.[^.]+$/, ""),
    confirmLabel: "Upload",
  });
  if (!name || !name.trim()) return;
  const trimmedName = name.trim();
  const taskId = startTask(`Uploading "${trimmedName}"`, 100);

  const attempt = async () => {
    saveUploading.value = new Set(saveUploading.value).add("");
    try {
      await createArchive(gameId, "save", trimmedName, file, (f, speedLabel) =>
        updateTask(taskId, Math.round(f * 100), undefined, speedLabel),
      );
      completeTask(taskId, "Saved");
      await refreshSaveArchives();
    } catch (err) {
      errorTask(taskId, err instanceof Error ? err.message : "Upload failed");
      setTaskRetry(taskId, () => void attempt());
    } finally {
      const next = new Set(saveUploading.value);
      next.delete("");
      saveUploading.value = next;
    }
  };
  await attempt();
}

async function onAddSaveVersion(archive: GameArchiveData, files: File[]) {
  const file = files[0];
  if (!file || !game.value) return;
  const gameId = game.value.id;
  const taskId = startTask(`Uploading new version of "${archive.name}"`, 100);

  const attempt = async () => {
    saveUploading.value = new Set(saveUploading.value).add(archive.id);
    try {
      await addArchiveVersion(gameId, archive.id, file, (f, speedLabel) =>
        updateTask(taskId, Math.round(f * 100), undefined, speedLabel),
      );
      completeTask(taskId, "Saved");
      await refreshSaveArchives();
    } catch (err) {
      errorTask(taskId, err instanceof Error ? err.message : "Upload failed");
      setTaskRetry(taskId, () => void attempt());
    } finally {
      const next = new Set(saveUploading.value);
      next.delete(archive.id);
      saveUploading.value = next;
    }
  };
  await attempt();
}

async function onRenameArchive(archive: GameArchiveData, isWorld: boolean) {
  if (!game.value) return;
  const name = await prompt({
    title: "Rename",
    message: "Name",
    defaultValue: archive.name,
    confirmLabel: "Rename",
  });
  if (!name || !name.trim() || name.trim() === archive.name) return;
  try {
    await renameArchive(game.value.id, archive.id, name.trim());
    if (isWorld) await refreshWorldMaps();
    else await refreshSaveArchives();
  } catch (err) {
    filesError.value = err instanceof Error ? err.message : "Failed to rename";
  }
}

async function onDeleteArchive(archive: GameArchiveData, isWorld: boolean) {
  if (!game.value) return;
  const ok = await confirm({
    title: "Move to trash",
    message: `Move "${archive.name}" (${archive.versions.length} version(s)) to trash? It stays recoverable for 7 days, then is purged for good.`,
    confirmLabel: "Move to trash",
    danger: true,
  });
  if (!ok) return;
  try {
    await deleteArchive(game.value.id, archive.id);
    if (isWorld) {
      worldMaps.value = worldMaps.value.filter((w) => w.id !== archive.id);
      if (activeMapArchiveId.value === archive.id)
        activeMapArchiveId.value = null;
      await refreshWorldTrash();
    } else {
      saveArchives.value = saveArchives.value.filter(
        (a) => a.id !== archive.id,
      );
      await refreshSaveTrash();
    }
  } catch (err) {
    filesError.value = err instanceof Error ? err.message : "Failed to delete";
  }
}

// --- Trash: soft-deleted archives stay recoverable for 7 days before the
// background sweep purges them for good (features/trash/sweep.py) ---------
const saveTrash = ref<TrashedArchive[]>([]);
const worldTrash = ref<TrashedArchive[]>([]);
const showSaveTrash = ref(false);
const showWorldTrash = ref(false);

async function refreshSaveTrash() {
  if (!game.value) return;
  try {
    saveTrash.value = await fetchArchiveTrash(game.value.id, "save");
  } catch {
    // trash listing failing silently isn't worth blocking the main view
  }
}

async function refreshWorldTrash() {
  if (!game.value) return;
  try {
    worldTrash.value = await fetchArchiveTrash(game.value.id, "world_save");
  } catch {
    // same as above
  }
}

function daysUntil(unixSeconds: number): number {
  return Math.max(0, Math.ceil((unixSeconds - Date.now() / 1000) / 86400));
}

async function onRestoreArchive(archive: TrashedArchive, isWorld: boolean) {
  if (!game.value) return;
  try {
    await restoreArchive(game.value.id, archive.id);
    if (isWorld) {
      await refreshWorldMaps();
      await refreshWorldTrash();
    } else {
      await refreshSaveArchives();
      await refreshSaveTrash();
    }
  } catch (err) {
    filesError.value = err instanceof Error ? err.message : "Failed to restore";
  }
}

async function onDeleteVersion(
  archive: GameArchiveData,
  version: ArchiveVersion,
  isWorld: boolean,
) {
  if (!game.value) return;
  if (archive.versions.length <= 1) {
    filesError.value =
      "Delete the whole save to remove its last remaining version.";
    return;
  }
  const ok = await confirm({
    title: "Move to trash",
    message: `Move this version (${formatFileSize(version.size)}, ${formatArchiveDate(version.uploaded_at)}) to trash? Recoverable for 7 days.`,
    confirmLabel: "Move to trash",
    danger: true,
  });
  if (!ok) return;
  try {
    await deleteArchiveVersion(game.value.id, archive.id, version.id);
    if (isWorld) await refreshWorldMaps();
    else await refreshSaveArchives();
  } catch (err) {
    filesError.value =
      err instanceof Error ? err.message : "Failed to delete version";
  }
}

// --- World Map (BlueMap render of a world_save archive) --------------------
// a game (e.g. a modpack) can have several worlds, one card, many worlds,
// each named, versioned, rendered, and viewed independently
const worldMaps = ref<WorldMapEntry[]>([]);
const worldMapsLoaded = ref(false);
const worldMapStarting = ref<Set<string>>(new Set());
const activeMapArchiveId = ref<string | null>(null);
let worldMapPollTimer: ReturnType<typeof setInterval> | null = null;

function stopWorldMapPolling() {
  if (worldMapPollTimer) {
    clearInterval(worldMapPollTimer);
    worldMapPollTimer = null;
  }
}

async function refreshWorldMaps() {
  if (!game.value) return;
  try {
    worldMaps.value = await fetchWorldMaps(game.value.id);
    worldMapsLoaded.value = true;
    const anyRendering = worldMaps.value.some((w) => w.status === "rendering");
    if (anyRendering && !worldMapPollTimer) {
      // no push mechanism for a background render, poll every few
      // seconds only while at least one world is actually in flight
      worldMapPollTimer = setInterval(refreshWorldMaps, 4000);
    } else if (!anyRendering) {
      stopWorldMapPolling();
    }
  } catch {
    // list just doesn't update this tick, not worth surfacing an error
    // for a polling request
  }
}

async function onNewWorldSelected(files: File[]) {
  const file = files[0];
  if (!file || !game.value) return;
  const gameId = game.value.id;
  const name = await prompt({
    title: "Name this world",
    message: "World name",
    defaultValue: file.name.replace(/\.[^.]+$/, ""),
    confirmLabel: "Upload",
  });
  if (!name || !name.trim()) return;
  const trimmedName = name.trim();
  const taskId = startTask(`Uploading "${trimmedName}"`, 100);

  const attempt = async () => {
    saveUploading.value = new Set(saveUploading.value).add("");
    try {
      await createArchive(
        gameId,
        "world_save",
        trimmedName,
        file,
        (f, speedLabel) =>
          updateTask(taskId, Math.round(f * 100), undefined, speedLabel),
      );
      completeTask(taskId, "Saved");
      await refreshWorldMaps();
    } catch (err) {
      errorTask(taskId, err instanceof Error ? err.message : "Upload failed");
      setTaskRetry(taskId, () => void attempt());
    } finally {
      const next = new Set(saveUploading.value);
      next.delete("");
      saveUploading.value = next;
    }
  };
  await attempt();
}

async function onAddWorldVersion(archive: WorldMapEntry, files: File[]) {
  const file = files[0];
  if (!file || !game.value) return;
  const gameId = game.value.id;
  const taskId = startTask(`Uploading new version of "${archive.name}"`, 100);

  const attempt = async () => {
    saveUploading.value = new Set(saveUploading.value).add(archive.id);
    try {
      await addArchiveVersion(gameId, archive.id, file, (f, speedLabel) =>
        updateTask(taskId, Math.round(f * 100), undefined, speedLabel),
      );
      completeTask(taskId, "Saved: render again to update the map");
      await refreshWorldMaps();
    } catch (err) {
      errorTask(taskId, err instanceof Error ? err.message : "Upload failed");
      setTaskRetry(taskId, () => void attempt());
    } finally {
      const next = new Set(saveUploading.value);
      next.delete(archive.id);
      saveUploading.value = next;
    }
  };
  await attempt();
}

async function startWorldMapRender(archiveId: string) {
  if (!game.value) return;
  worldMapStarting.value = new Set(worldMapStarting.value).add(archiveId);
  filesError.value = null;
  try {
    await renderWorldMap(game.value.id, archiveId);
    await refreshWorldMaps();
  } catch (err) {
    filesError.value =
      err instanceof Error ? err.message : "Failed to start render";
  } finally {
    const next = new Set(worldMapStarting.value);
    next.delete(archiveId);
    worldMapStarting.value = next;
  }
}

function viewWorldMap(archiveId: string) {
  activeMapArchiveId.value = archiveId;
}

onUnmounted(stopWorldMapPolling);

function displayFileName(filename: string): string {
  // strip the random 8-char dedupe prefix save_media_bytes adds
  const parts = filename.split("_");
  return parts.length > 1 ? parts.slice(1).join("_") : filename;
}

function sortedAchievements(achievements: Achievement[]) {
  return [...achievements].sort((a, b) => {
    if (a.unlockedAt === null && b.unlockedAt === null) return 0;
    if (a.unlockedAt === null) return 1;
    if (b.unlockedAt === null) return -1;
    return b.unlockedAt.localeCompare(a.unlockedAt);
  });
}

function deriveTier(achievement: Achievement): AchievementTier {
  if (achievement.tierOverride) return achievement.tierOverride;
  const rarity = achievement.rarityPercent;
  if (rarity === null || rarity === undefined) return "bronze";
  if (rarity <= 20) return "gold";
  if (rarity <= 50) return "silver";
  return "bronze";
}

const isPlatinumEarned = computed(
  () =>
    !!game.value &&
    game.value.achievements.length > 0 &&
    game.value.achievements.every((a) => a.unlockedAt !== null),
);

const trophyCounts = computed(() => {
  const counts = { bronze: 0, silver: 0, gold: 0 };
  if (!game.value) return counts;
  for (const a of game.value.achievements) {
    if (a.unlockedAt !== null) counts[deriveTier(a)]++;
  }
  return counts;
});

function formatUnlockedAt(dateStr: string) {
  const d = new Date(dateStr);
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function formatPlaytime(minutes: number) {
  if (minutes === 0) return "Not played yet";
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}
</script>

<template>
  <main v-if="loading" class="detail loading-state">
    <div class="detail-skeleton">
      <SkeletonBlock height="320px" radius="0" />
      <div class="detail-skeleton-body">
        <SkeletonBlock width="45%" height="28px" />
        <div class="detail-skeleton-pills">
          <SkeletonBlock width="80px" height="24px" radius="999px" />
          <SkeletonBlock width="100px" height="24px" radius="999px" />
          <SkeletonBlock width="70px" height="24px" radius="999px" />
        </div>
        <div class="detail-skeleton-tabs">
          <SkeletonBlock
            v-for="i in 6"
            :key="i"
            width="70px"
            height="30px"
            radius="8px"
          />
        </div>
        <SkeletonBlock height="140px" />
      </div>
    </div>
  </main>

  <main v-else-if="error" class="detail error-state">
    <p>{{ error }}</p>
  </main>

  <main v-else-if="game" class="detail">
    <!-- heavily blurred, dimmed copy of the cover image behind the whole page,
         separate from the sharp version used in .hero itself -->
    <div
      class="ambient-bg"
      :style="{ backgroundImage: `url(${game.bannerImageUrl})` }"
    ></div>

    <BackButton fixed @click="goBackToLibrary" />

    <AccountChip fixed />

    <GameFormModal
      v-if="showEditModal"
      :game="game"
      @close="showEditModal = false"
      @saved="onGameSaved"
      @delete="onDeleteFromModal"
    />

    <CollectionPickerModal
      v-if="showCollectionPicker"
      :game="game"
      @close="showCollectionPicker = false"
      @added="onCollectionAdded"
    />

    <div
      v-if="showDeleteConfirm"
      class="confirm-backdrop"
      @click.self="showDeleteConfirm = false"
    >
      <div class="confirm-dialog">
        <h3>Delete {{ game.title }}?</h3>
        <p>This can't be undone.</p>
        <div v-if="deleteError" class="confirm-error">{{ deleteError }}</div>
        <div class="confirm-actions">
          <button
            type="button"
            class="secondary-button"
            @click="showDeleteConfirm = false"
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

    <section
      class="hero"
      :style="{ backgroundImage: `url(${game.bannerImageUrl})` }"
    >
      <div class="hero-overlay"></div>
      <div class="hero-actions">
        <button
          class="hero-icon-button"
          type="button"
          title="Add to collection"
          @click="showCollectionPicker = true"
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
            <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
          </svg>
        </button>
        <button
          class="hero-icon-button"
          :class="{ active: game.favorite }"
          type="button"
          :title="game.favorite ? 'Remove from favorites' : 'Add to favorites'"
          @click="toggleFavorite"
        >
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            :fill="game.favorite ? 'currentColor' : 'none'"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path
              d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.6z"
            />
          </svg>
        </button>
        <button class="edit-button" type="button" @click="showEditModal = true">
          Edit
        </button>
      </div>
      <div class="hero-inner">
        <router-link
          v-if="game.parentGameId"
          :to="`/games/${game.parentGameId}`"
          class="parent-breadcrumb"
        >
          {{ parentGameTitle ?? "…" }}
          <span v-if="game.relationshipType" class="relationship-tag">{{
            RELATIONSHIP_LABELS[game.relationshipType] ?? game.relationshipType
          }}</span>
          →
        </router-link>
        <h1>{{ game.title }}</h1>
        <div class="badges">
          <span class="badge status-badge">{{ game.status }}</span>
          <span v-if="tally" class="badge rating-badge">
            ★ {{ tally.sum.toFixed(1) }}
          </span>
          <span v-if="game.dateAdded" class="badge">
            {{ new Date(game.dateAdded).toLocaleDateString() }}
          </span>
          <span v-if="game.platforms.length" class="badge">{{
            game.platforms[0].platform
          }}</span>
          <button
            v-if="game.achievementTotal > 0"
            type="button"
            class="badge achievement-progress-badge"
            title="Jump to Achievements"
            @click="activeTab = 'Achievements'"
          >
            <svg
              viewBox="0 0 24 24"
              width="13"
              height="13"
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
            {{ game.achievementPercent }}%
          </button>
          <span
            v-if="game.staleSince"
            class="badge stale-badge"
            :title="`Last sync (${new Date(game.staleSince).toLocaleDateString()}) no longer saw this in your ${game.source} library.`"
          >
            Not currently in your {{ game.source }} library
          </span>
        </div>
      </div>
    </section>

    <nav class="tabs">
      <button
        v-for="tab in visibleTabs"
        :key="tab"
        type="button"
        class="tab"
        :class="{ active: activeTab === tab }"
        @click="activeTab = tab"
      >
        {{ tab }}
      </button>
    </nav>

    <section v-if="activeTab === 'Overview'" class="overview">
      <div class="overview-main">
        <div v-if="relatedBounties.length" class="related-bounties">
          <router-link
            v-for="b in relatedBounties"
            :key="b.id"
            to="/bounties"
            class="related-bounty-card"
          >
            <span class="related-bounty-icon">🎯</span>
            <span class="related-bounty-body">
              <span class="related-bounty-title">{{ b.title }}</span>
              <span class="related-bounty-meta">
                Active bounty on this game<span v-if="b.difficulty">
                  · {{ b.difficulty }}</span
                ><span v-if="b.points_reward">
                  · {{ b.points_reward }} pts</span
                >
              </span>
            </span>
          </router-link>
        </div>

        <div class="resume-note-card">
          <div class="resume-note-header">
            <h3>Where I left off</h3>
            <button
              v-if="!resumeNoteEditing"
              type="button"
              class="text-button"
              @click="startEditResumeNote"
            >
              {{ game.resumeNote ? "Edit" : "+ Add note" }}
            </button>
          </div>
          <template v-if="resumeNoteEditing">
            <textarea
              v-model="resumeNoteDraft"
              class="resume-note-textarea"
              rows="3"
              placeholder="e.g. Just beat the third boss, about to start the desert region…"
            ></textarea>
            <div v-if="resumeNoteError" class="form-error-inline">
              {{ resumeNoteError }}
            </div>
            <div class="resume-note-actions">
              <button
                type="button"
                class="secondary-button"
                @click="resumeNoteEditing = false"
              >
                Cancel
              </button>
              <button
                type="button"
                class="primary-button"
                :disabled="resumeNoteSaving"
                @click="saveResumeNote"
              >
                {{ resumeNoteSaving ? "Saving…" : "Save" }}
              </button>
            </div>
          </template>
          <p v-else-if="game.resumeNote" class="resume-note-text">
            {{ game.resumeNote }}
          </p>
          <p v-else class="resume-note-empty">
            Nothing noted yet. Jot down what to do next time you pick this up.
          </p>
        </div>

        <div v-if="descriptionHtml" class="description-wrap">
          <div class="description-html" v-html="descriptionHtml"></div>
        </div>

        <div v-if="variants.length" class="variants-section">
          <h3 class="variants-heading">Variants</h3>
          <div class="variants-row">
            <router-link
              v-for="variant in variants"
              :key="variant.id"
              :to="`/games/${variant.id}`"
              class="variant-card"
            >
              <img :src="variant.coverImageUrl" alt="" class="variant-cover" />
              <span class="variant-title">{{ variant.title }}</span>
              <span v-if="variant.relationshipType" class="relationship-tag">
                {{
                  RELATIONSHIP_LABELS[variant.relationshipType] ??
                  variant.relationshipType
                }}
              </span>
            </router-link>
          </div>
        </div>

        <div v-if="similarGames.length" class="similar-games-section">
          <h3 class="variants-heading">Similar games in your library</h3>
          <div class="variants-row">
            <router-link
              v-for="g in similarGames"
              :key="g.id"
              :to="`/games/${g.id}`"
              class="variant-card"
            >
              <img :src="g.coverImageUrl" alt="" class="variant-cover" />
              <span class="variant-title">{{ g.title }}</span>
            </router-link>
          </div>
        </div>

        <div
          class="rating-breakdown"
          v-if="
            game.ratingOverall !== null ||
            game.ratingStory !== null ||
            game.ratingGameplay !== null ||
            game.ratingSound !== null
          "
        >
          <div v-if="game.ratingOverall !== null" class="rating-item">
            <span class="rating-label">Atmosphere</span>
            <span class="rating-score"
              >★ {{ game.ratingOverall.toFixed(1) }}</span
            >
          </div>
          <div v-if="game.ratingStory !== null" class="rating-item">
            <span class="rating-label">Story</span>
            <span class="rating-score"
              >★ {{ game.ratingStory.toFixed(1) }}</span
            >
          </div>
          <div v-if="game.ratingGameplay !== null" class="rating-item">
            <span class="rating-label">Gameplay</span>
            <span class="rating-score"
              >★ {{ game.ratingGameplay.toFixed(1) }}</span
            >
          </div>
          <div v-if="game.ratingSound !== null" class="rating-item">
            <span class="rating-label">Sound</span>
            <span class="rating-score"
              >★ {{ game.ratingSound.toFixed(1) }}</span
            >
          </div>
          <div v-if="tally" class="rating-item">
            <span class="rating-label">Score</span>
            <span class="rating-score">{{ tally.sum.toFixed(1) }}</span>
          </div>
        </div>
      </div>

      <aside class="details-panel">
        <h3 class="panel-title">Details</h3>
        <div class="detail-row">
          <span class="detail-label">Developer</span>
          <span class="detail-value">{{ game.developer ?? "N/A" }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Publisher</span>
          <span class="detail-value">{{ game.publisher ?? "N/A" }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Series</span>
          <span class="detail-value">{{ game.series ?? "N/A" }}</span>
        </div>
        <div v-if="game.releaseDate" class="detail-row">
          <span class="detail-label">Release Date</span>
          <span class="detail-value">{{
            formatDisplayDate(game.releaseDate)
          }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Date Added</span>
          <span class="detail-value">
            {{
              game.dateAdded
                ? new Date(game.dateAdded).toLocaleDateString()
                : "N/A"
            }}
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Recent Activity</span>
          <span class="detail-value">
            {{
              recentActivity
                ? new Date(recentActivity).toLocaleDateString()
                : "N/A"
            }}
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Platforms</span>
          <ul class="platforms">
            <li
              v-for="p in game.platforms"
              :key="p.platform"
              class="platform-row"
            >
              <div class="platform-line">
                <span class="platform-name">{{ p.platform }}</span>
                <span class="platform-meta">
                  {{ formatPlaytime(p.playtimeMinutes)
                  }}<span v-if="p.completionPercent !== null">
                    · {{ p.completionPercent }}%</span
                  >
                </span>
              </div>
              <div v-if="p.lastPlayedAt" class="platform-last-played">
                last played {{ new Date(p.lastPlayedAt).toLocaleDateString() }}
              </div>
            </li>
          </ul>
          <button
            type="button"
            class="text-button log-playtime-button"
            :disabled="loggingPlaytime"
            title="Log a session just played, without editing the total by hand"
            @click="logPlaytime(30)"
          >
            + Log 30 min just played
          </button>
        </div>
        <div v-if="game.tags.length" class="detail-row">
          <span class="detail-label">Tags</span>
          <span class="feature-pills">
            <span v-for="tag in game.tags" :key="tag" class="feature-pill">{{
              tag
            }}</span>
          </span>
        </div>
        <div v-if="game.features.length" class="detail-row">
          <span class="detail-label">Features</span>
          <span class="feature-pills">
            <span v-for="f in game.features" :key="f" class="feature-pill">{{
              f
            }}</span>
          </span>
        </div>
        <div v-if="game.source" class="detail-row">
          <span class="detail-label">Source</span>
          <span class="detail-value">{{ game.source }}</span>
        </div>
        <div v-if="activePriority(game) !== null" class="detail-row">
          <span class="detail-label">Priority</span>
          <span class="detail-value">{{
            priorityLabel(activePriority(game)!)
          }}</span>
        </div>
        <div v-if="game.ageRating" class="detail-row">
          <span class="detail-label">Age Rating</span>
          <span class="detail-value">{{ game.ageRating }}</span>
        </div>
        <div v-if="game.timeToBeatHours" class="detail-row">
          <span class="detail-label">Time to Beat</span>
          <span class="detail-value">{{ game.timeToBeatHours }}h</span>
        </div>
        <div v-if="game.region" class="detail-row">
          <span class="detail-label">Region</span>
          <span class="detail-value">{{ game.region }}</span>
        </div>
        <div v-if="game.language" class="detail-row">
          <span class="detail-label">Language</span>
          <span class="detail-value">{{ game.language }}</span>
        </div>
        <div v-if="game.achievementsProvider" class="detail-row">
          <span class="detail-label">Achievement Tracking</span>
          <span class="detail-value">{{
            game.achievementsProvider === "retroachievements"
              ? "RetroAchievements"
              : "Native"
          }}</span>
        </div>
        <div v-if="game.links.length" class="detail-row">
          <span class="detail-label">Links</span>
          <ul class="links-list">
            <li v-for="link in game.links" :key="link.url">
              <a :href="link.url" target="_blank" rel="noopener noreferrer">{{
                link.label
              }}</a>
            </li>
          </ul>
        </div>
        <div
          v-if="
            game.ownership.format ||
            game.ownership.purchaseDate ||
            game.ownership.price !== null
          "
          class="detail-row"
        >
          <span class="detail-label">Ownership</span>
          <div class="ownership-info">
            <span v-if="game.ownership.format" class="ownership-format">{{
              game.ownership.format
            }}</span>
            <span v-if="game.ownership.purchaseDate">
              Purchased
              {{ formatDisplayDate(game.ownership.purchaseDate) }}
            </span>
            <span v-if="game.ownership.price !== null">
              {{ game.ownership.priceCurrency ?? "USD" }}
              {{ game.ownership.price.toFixed(2) }}
            </span>
            <span v-if="game.ownership.condition">{{
              game.ownership.condition
            }}</span>
          </div>
        </div>
        <div v-if="game.folderLocation" class="detail-row">
          <span class="detail-label">Folder</span>
          <span class="detail-value">{{ game.folderLocation }}</span>
        </div>
      </aside>
    </section>

    <section v-else-if="activeTab === 'Achievements'" class="achievements">
      <div class="achievements-header">
        <h2>Achievements</h2>
        <span class="percent">{{ game.achievementPercent }}%</span>
      </div>

      <div class="trophy-summary">
        <div class="trophy-count">
          <span
            class="trophy-badge trophy-badge-platinum"
            :class="{ dim: !isPlatinumEarned }"
          ></span>
          <span>{{ isPlatinumEarned ? 1 : 0 }}</span>
        </div>
        <div class="trophy-count">
          <span class="trophy-badge trophy-badge-gold"></span>
          <span>{{ trophyCounts.gold }}</span>
        </div>
        <div class="trophy-count">
          <span class="trophy-badge trophy-badge-silver"></span>
          <span>{{ trophyCounts.silver }}</span>
        </div>
        <div class="trophy-count">
          <span class="trophy-badge trophy-badge-bronze"></span>
          <span>{{ trophyCounts.bronze }}</span>
        </div>
      </div>

      <ul class="achievement-list">
        <li
          v-for="achievement in sortedAchievements(game.achievements)"
          :key="achievement.id"
        >
          <router-link
            :to="{
              name: 'achievement-detail',
              params: { gameId: game.id, achievementId: achievement.id },
            }"
            class="achievement-row"
            :class="{ unlocked: achievement.unlockedAt !== null }"
          >
            <div
              class="achievement-icon"
              :style="
                achievement.hidden && achievement.unlockedAt === null
                  ? {}
                  : { backgroundImage: `url(${game.coverImageUrl})` }
              "
            >
              <span
                class="achievement-badge"
                :class="
                  achievement.unlockedAt !== null
                    ? `badge-${deriveTier(achievement)}`
                    : 'badge-locked'
                "
              >
                <template
                  v-if="achievement.hidden && achievement.unlockedAt === null"
                  >?</template
                >
              </span>
            </div>

            <div class="achievement-info">
              <template
                v-if="achievement.hidden && achievement.unlockedAt === null"
              >
                <span class="achievement-name">Hidden Trophy</span>
                <span class="achievement-description"
                  >Unlock this achievement to reveal it.</span
                >
              </template>
              <template v-else>
                <span class="achievement-name">{{ achievement.name }}</span>
                <span
                  v-if="achievement.description"
                  class="achievement-description"
                  >{{ achievement.description }}</span
                >
              </template>

              <div
                v-if="achievement.unlockedAt !== null"
                class="achievement-unlocked-at"
              >
                Unlocked {{ formatUnlockedAt(achievement.unlockedAt) }}
              </div>
              <div
                v-else-if="
                  achievement.progressCurrent != null &&
                  achievement.progressTarget
                "
                class="achievement-progress"
              >
                <div class="progress-bar">
                  <div
                    class="progress-fill"
                    :style="{
                      width: `${Math.min(100, (achievement.progressCurrent / achievement.progressTarget) * 100)}%`,
                    }"
                  ></div>
                </div>
                <span class="progress-label"
                  >{{ achievement.progressCurrent }} /
                  {{ achievement.progressTarget }}</span
                >
              </div>
            </div>
          </router-link>
        </li>
      </ul>
    </section>

    <section v-else-if="activeTab === 'Notes'" class="notes-panel">
      <div v-if="noteMode === 'list'" class="notes-list-view">
        <div class="notes-header-row">
          <h2>Notes</h2>
          <button type="button" class="primary-button" @click="startNewNote">
            {{ hasDraft ? "Continue Draft" : "New Note" }}
          </button>
        </div>

        <div v-if="noteError" class="note-error">{{ noteError }}</div>

        <p v-if="noteLoading" class="empty-state">Loading…</p>
        <p v-else-if="!noteNames.length" class="empty-state">No notes yet.</p>
        <ul v-else class="notes-list">
          <li
            v-for="note in noteNames"
            :key="note"
            class="notes-list-row"
            @click="void viewNote(note)"
          >
            <span class="note-name">{{ note }}</span>
            <div class="notes-list-actions">
              <button
                type="button"
                class="danger-button"
                :disabled="noteSaving"
                @click.stop="void deleteNote(note)"
              >
                Delete
              </button>
            </div>
          </li>
        </ul>
      </div>

      <div v-else-if="noteMode === 'view'" class="notes-editor">
        <div class="notes-editor-card">
          <div class="notes-toolbar">
            <button type="button" class="small-button" @click="backToList">
              ← Back
            </button>
            <span class="selected-note">{{ viewingNoteName }}</span>
            <button type="button" class="small-button" @click="editFromView">
              Edit
            </button>
          </div>

          <div v-if="noteLoading" class="empty-state">Loading…</div>
          <div v-else class="note-rendered" v-html="renderedNoteHtml"></div>

          <div v-if="noteError" class="note-error">{{ noteError }}</div>
        </div>
      </div>

      <div v-else class="notes-editor">
        <div class="notes-editor-card">
          <div class="notes-toolbar">
            <button type="button" class="small-button" @click="backToList">
              ← Back
            </button>
          </div>

          <label class="field">
            <span>Note name</span>
            <input
              v-model="draftName"
              type="text"
              placeholder="Meeting notes"
              autocomplete="off"
            />
          </label>

          <textarea
            v-model="draftContent"
            placeholder="Write markdown here…"
            spellcheck="true"
          ></textarea>

          <div v-if="noteError" class="note-error">{{ noteError }}</div>

          <div class="notes-editor-actions">
            <button type="button" class="small-button" @click="backToList">
              Cancel
            </button>
            <button
              type="button"
              class="primary-button"
              :disabled="noteSaving || !draftName.trim()"
              @click="void saveDraft()"
            >
              {{
                noteSaving
                  ? "Saving…"
                  : editingNoteName
                    ? "Save changes"
                    : "Create note"
              }}
            </button>
          </div>
        </div>
      </div>
    </section>

    <section v-else-if="activeTab === 'Accounts'" class="accounts-panel">
      <div class="accounts-layout">
        <aside class="accounts-sidebar">
          <button
            type="button"
            class="account-list-item"
            :class="{ active: activeProfileId === null }"
            @click="activeProfileId = null"
          >
            <span class="account-list-name">General</span>
          </button>
          <button
            v-for="profile in profiles"
            :key="profile.id"
            type="button"
            class="account-list-item"
            :class="{ active: activeProfileId === profile.id }"
            @click="activeProfileId = profile.id"
          >
            <span class="account-list-name">{{ profile.name }}</span>
            <span v-if="profile.stats.Overall" class="account-list-meta"
              >Lvl {{ profile.stats.Overall }}</span
            >
          </button>
          <form class="account-add" @submit.prevent="void addProfile()">
            <input
              v-model="newProfileName"
              type="text"
              placeholder="Add account…"
            />
            <button
              type="submit"
              title="Add account"
              :disabled="!newProfileName.trim()"
            >
              +
            </button>
          </form>
          <div v-if="profileError" class="note-error">{{ profileError }}</div>
        </aside>

        <div class="accounts-detail">
          <div class="accounts-detail-header">
            <h2>{{ selectedProfile ? selectedProfile.name : "General" }}</h2>
            <div v-if="selectedProfile" class="accounts-detail-actions">
              <button
                type="button"
                class="small-button"
                @click="promptRenameProfile(selectedProfile)"
              >
                Rename
              </button>
              <button
                type="button"
                class="danger-button"
                @click="void removeProfile(selectedProfile)"
              >
                Delete
              </button>
            </div>
          </div>

          <template v-if="selectedProfile">
            <div class="account-note-card">
              <h3>Note</h3>
              <textarea
                v-model="profileNoteDraft"
                rows="3"
                placeholder="What are you working toward on this account?"
              ></textarea>
              <button
                type="button"
                class="small-button"
                :disabled="profileNoteSaving"
                @click="void saveProfileNote()"
              >
                {{ profileNoteSaving ? "Saving…" : "Save note" }}
              </button>
            </div>
          </template>

          <div class="checklist-card">
            <div class="checklist-card-header">
              <h3>Checklist</h3>
              <span
                v-if="checklistProgress.total"
                class="checklist-progress-label"
              >
                {{ checklistProgress.done }}/{{ checklistProgress.total }}
              </span>
            </div>
            <div v-if="checklistProgress.total" class="checklist-progress-bar">
              <div
                class="checklist-progress-fill"
                :style="{
                  width: `${Math.round((checklistProgress.done / checklistProgress.total) * 100)}%`,
                }"
              ></div>
            </div>
            <div v-if="checklistError" class="note-error">
              {{ checklistError }}
            </div>
            <p v-if="checklistLoading" class="empty-state">Loading…</p>
            <p v-else-if="!checklistItems.length" class="empty-state">
              Nothing on the checklist yet.
            </p>
            <template v-else>
              <div
                v-for="section in checklistSections"
                :key="section.header?.id ?? 'default'"
                class="checklist-section"
              >
                <div
                  v-if="section.header"
                  class="checklist-section-header"
                  @click="toggleSectionCollapsed(section.header.id)"
                >
                  <span class="checklist-section-caret">{{
                    collapsedSections.has(section.header.id) ? "▸" : "▾"
                  }}</span>
                  <template v-if="editingItemId === section.header.id">
                    <input
                      v-model="editingText"
                      type="text"
                      class="checklist-edit-input"
                      autofocus
                      @click.stop
                      @keydown.enter="commitEditItem(section.header)"
                      @keydown.escape="cancelEditItem"
                      @blur="commitEditItem(section.header)"
                    />
                  </template>
                  <span
                    v-else
                    class="checklist-section-title"
                    @click.stop="startEditItem(section.header)"
                  >
                    {{ section.header.text }}
                  </span>
                  <span class="checklist-section-count"
                    >{{ sectionProgress(section).done }}/{{
                      sectionProgress(section).total
                    }}</span
                  >
                  <button
                    type="button"
                    class="checklist-remove"
                    title="Delete section"
                    @click.stop="void removeChecklistItem(section.header)"
                  >
                    ×
                  </button>
                </div>
                <ul
                  v-if="
                    !section.header || !collapsedSections.has(section.header.id)
                  "
                  class="checklist-items"
                >
                  <li
                    v-for="item in section.items"
                    :key="item.id"
                    class="checklist-row"
                  >
                    <div class="checklist-move-buttons">
                      <button
                        type="button"
                        class="checklist-move"
                        title="Move up"
                        @click="void moveChecklistItem(item, -1)"
                      >
                        ▲
                      </button>
                      <button
                        type="button"
                        class="checklist-move"
                        title="Move down"
                        @click="void moveChecklistItem(item, 1)"
                      >
                        ▼
                      </button>
                    </div>
                    <label class="checklist-label">
                      <input
                        type="checkbox"
                        :checked="item.done"
                        @change="void toggleChecklistItem(item)"
                      />
                      <input
                        v-if="editingItemId === item.id"
                        v-model="editingText"
                        type="text"
                        class="checklist-edit-input"
                        autofocus
                        @keydown.enter="commitEditItem(item)"
                        @keydown.escape="cancelEditItem"
                        @blur="commitEditItem(item)"
                      />
                      <span
                        v-else
                        :class="{ done: item.done }"
                        @click="startEditItem(item)"
                        >{{ item.text }}</span
                      >
                    </label>
                    <button
                      type="button"
                      class="checklist-remove"
                      title="Delete"
                      @click="void removeChecklistItem(item)"
                    >
                      ×
                    </button>
                  </li>
                </ul>
              </div>
            </template>
            <div class="checklist-add-row">
              <form
                class="checklist-add"
                @submit.prevent="void addChecklistItem()"
              >
                <input
                  v-model="newChecklistText"
                  type="text"
                  placeholder="Add a checklist item…"
                />
                <button
                  type="submit"
                  class="small-button"
                  :disabled="!newChecklistText.trim()"
                >
                  Add
                </button>
              </form>
              <button
                type="button"
                class="small-button"
                @click="addChecklistSection"
              >
                + Section
              </button>
            </div>
          </div>

          <div class="account-gallery-card">
            <div class="account-gallery-header">
              <h3>Media</h3>
              <div class="account-gallery-kinds">
                <button
                  v-for="kind in ACCOUNT_MEDIA_KINDS"
                  :key="kind"
                  type="button"
                  class="account-chip"
                  :class="{ active: accountMediaKind === kind }"
                  @click="accountMediaKind = kind"
                >
                  {{ kind }}
                </button>
              </div>
            </div>

            <UploadDropzone
              :accept="
                accountMediaKind === 'screenshot'
                  ? 'image/*'
                  : accountMediaKind === 'clip'
                    ? 'video/*'
                    : 'audio/*'
              "
              :uploading="uploadingMedia"
              :title="`Drop ${accountMediaKind}s here`"
              :hint="`Drag and drop, or click to browse, tagged to ${selectedProfile ? selectedProfile.name : 'General'}`"
              @files-selected="onMediaFilesSelected"
              @drop-error="onDropError"
            />
            <div v-if="mediaError" class="form-error">{{ mediaError }}</div>

            <div v-if="accountMediaCategories.length" class="account-bar">
              <button
                type="button"
                class="account-chip"
                :class="{ active: accountMediaCategory === null }"
                @click="accountMediaCategory = null"
              >
                All
              </button>
              <button
                v-for="category in accountMediaCategories"
                :key="category"
                type="button"
                class="account-chip"
                :class="{ active: accountMediaCategory === category }"
                @click="accountMediaCategory = category"
              >
                {{ category }}
              </button>
            </div>

            <p v-if="mediaLoading" class="empty-row">Loading…</p>
            <p v-else-if="!accountMediaFiltered.length" class="empty-row">
              No {{ accountMediaKind }}s yet.
            </p>
            <div v-else class="media-grid">
              <MediaTile
                v-for="item in accountMediaFiltered"
                :key="item.id"
                :item="item"
                :achievements="game.achievements"
                :profiles="profiles"
                @preview="onPreviewMedia($event.url)"
                @delete="removeMedia"
                @save="saveMediaItem"
              />
            </div>
          </div>

          <div v-if="selectedProfile" class="account-stats-card">
            <div class="account-stats-header">
              <h3>Stats</h3>
              <button
                v-if="!editingStats"
                type="button"
                class="small-button"
                @click="startEditStats"
              >
                Edit
              </button>
            </div>
            <div v-if="game.osrsStatsEnabled" class="wom-sync-row">
              <input
                v-model="womUsername"
                type="text"
                placeholder="RuneScape username (WiseOldMan)"
              />
              <button
                type="button"
                class="small-button"
                :disabled="womSyncing"
                @click="void syncWiseOldMan()"
              >
                {{ womSyncing ? "Syncing…" : "Sync from WiseOldMan" }}
              </button>
            </div>
            <div v-if="womError" class="note-error">{{ womError }}</div>

            <p
              v-if="!editingStats && !Object.keys(selectedProfile.stats).length"
              class="empty-state small"
            >
              No stats yet, add one manually{{
                game.osrsStatsEnabled ? ", or sync from WiseOldMan above" : ""
              }}.
            </p>
            <template v-else-if="!editingStats && game.osrsStatsEnabled">
              <div v-if="headlineStats.length" class="stat-grid headline">
                <div
                  v-for="entry in headlineStats"
                  :key="entry.key"
                  class="account-stat-tile headline"
                >
                  <img
                    :src="skillIconUrl(entry.key)"
                    alt=""
                    class="stat-tile-icon"
                    @error="
                      ($event.target as HTMLElement).style.visibility = 'hidden'
                    "
                  />
                  <span class="stat-tile-label">{{ entry.key }}</span>
                  <span class="stat-tile-value">{{ entry.value }}</span>
                </div>
              </div>
              <template v-if="skillStats.length">
                <h4 class="stat-group-heading">Skills</h4>
                <div class="stat-grid">
                  <div
                    v-for="[key, value] in skillStats"
                    :key="key"
                    class="account-stat-tile"
                  >
                    <img
                      :src="skillIconUrl(key)"
                      alt=""
                      class="stat-tile-icon"
                      @error="
                        ($event.target as HTMLElement).style.visibility =
                          'hidden'
                      "
                    />
                    <span class="stat-tile-label">{{ key }}</span>
                    <span class="stat-tile-value">{{ value }}</span>
                  </div>
                </div>
              </template>
              <template v-if="bossStats.length">
                <h4 class="stat-group-heading">Bosses &amp; Activities</h4>
                <div class="stat-grid">
                  <div
                    v-for="[key, value] in bossStats"
                    :key="key"
                    class="account-stat-tile"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      width="20"
                      height="20"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.6"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      class="stat-tile-boss-icon"
                    >
                      <path d="M6.5 2 3 6l3.5 2M17.5 2 21 6l-3.5 2" />
                      <path
                        d="M12 2c-3 0-5 2-5 5 0 2.5 1.5 4 2 5.5L8 21h8l-1-8.5c.5-1.5 2-3 2-5.5 0-3-2-5-5-5z"
                      />
                      <circle
                        cx="9.5"
                        cy="8"
                        r="1"
                        fill="currentColor"
                        stroke="none"
                      />
                      <circle
                        cx="14.5"
                        cy="8"
                        r="1"
                        fill="currentColor"
                        stroke="none"
                      />
                    </svg>
                    <span class="stat-tile-label">{{ key }}</span>
                    <span class="stat-tile-value">{{ value }}</span>
                  </div>
                </div>
              </template>
            </template>
            <div v-else-if="!editingStats" class="stat-grid">
              <div
                v-for="(value, key) in selectedProfile.stats"
                :key="key"
                class="account-stat-tile"
              >
                <span class="stat-tile-label">{{ key }}</span>
                <span class="stat-tile-value">{{ value }}</span>
              </div>
            </div>

            <template v-else>
              <div v-if="statRows.length" class="stat-rows">
                <div
                  v-for="(row, index) in statRows"
                  :key="index"
                  class="stat-row"
                >
                  <input
                    v-model="row.key"
                    type="text"
                    placeholder="Label (e.g. Overall)"
                  />
                  <input v-model="row.value" type="text" placeholder="Value" />
                  <button
                    type="button"
                    class="checklist-remove"
                    title="Remove"
                    @click="removeStatRow(index)"
                  >
                    ×
                  </button>
                </div>
              </div>
              <div class="stat-actions">
                <button type="button" class="small-button" @click="addStatRow">
                  + Add stat
                </button>
                <button
                  type="button"
                  class="small-button"
                  @click="cancelEditStats"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  class="primary-button"
                  @click="void saveProfileStats()"
                >
                  Save stats
                </button>
              </div>
            </template>
          </div>

          <div v-if="selectedProfile" class="account-history-card">
            <button
              type="button"
              class="account-history-toggle"
              @click="void toggleStatHistory()"
            >
              <span>History</span>
              <span class="account-history-caret">{{
                showStatHistory ? "▾" : "▸"
              }}</span>
            </button>
            <div v-if="showStatHistory">
              <p v-if="statHistoryLoading" class="empty-state small">
                Loading…
              </p>
              <p v-else-if="!statHistory.length" class="empty-state small">
                No history yet, it builds up automatically every time you sync
                or save stats.
              </p>
              <template v-else>
                <ul class="stat-history-list">
                  <li
                    v-for="snapshot in visibleHistory"
                    :key="snapshot.id"
                    class="stat-history-row"
                  >
                    <span class="stat-history-date">{{
                      formatSnapshotDate(snapshot.recorded_at)
                    }}</span>
                    <span
                      v-if="statGains[snapshot.id]?.length"
                      class="stat-history-values"
                    >
                      <span
                        v-for="line in statGains[snapshot.id]"
                        :key="line"
                        class="stat-history-chip gain"
                        >{{ line }}</span
                      >
                    </span>
                    <span v-else class="stat-history-values">
                      <span
                        v-for="(value, key) in snapshot.stats"
                        :key="key"
                        class="stat-history-chip"
                        >{{ key }}: {{ value }}</span
                      >
                    </span>
                  </li>
                </ul>
                <button
                  v-if="
                    !historyShowAll && statHistory.length > HISTORY_PAGE_SIZE
                  "
                  type="button"
                  class="small-button"
                  @click="historyShowAll = true"
                >
                  Show all {{ statHistory.length }}
                </button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section
      v-else-if="
        activeTab === 'Screenshots' ||
        activeTab === 'Clips' ||
        activeTab === 'Soundtrack'
      "
      class="media-panel"
    >
      <h2>{{ activeTab }}</h2>
      <div class="panel-body">
        <ViewUploadSidebar v-model="panelMode" />
        <div class="panel-content">
          <template v-if="panelMode === 'upload'">
            <UploadDropzone
              :accept="
                activeTab === 'Screenshots'
                  ? 'image/*'
                  : activeTab === 'Clips'
                    ? 'video/*'
                    : 'audio/*'
              "
              :uploading="uploadingMedia"
              :title="`Drop ${activeTab.toLowerCase()} here`"
              :hint="`Drag and drop ${activeTab === 'Soundtrack' ? 'audio' : activeTab.toLowerCase()}, or click to browse`"
              @files-selected="onMediaFilesSelected"
              @drop-error="onDropError"
            />
            <div v-if="mediaError" class="form-error">{{ mediaError }}</div>
          </template>

          <template v-else>
            <p v-if="mediaLoading">Loading…</p>
            <p
              v-else-if="
                (activeTab === 'Screenshots' && !screenshots.length) ||
                (activeTab === 'Clips' && !clips.length) ||
                (activeTab === 'Soundtrack' && !soundtrackItems.length)
              "
              class="empty-row"
            >
              No {{ activeTab.toLowerCase() }} yet: switch to Upload to add
              some.
            </p>
            <div v-else class="media-grid">
              <MediaTile
                v-for="item in activeTab === 'Screenshots'
                  ? screenshots
                  : activeTab === 'Clips'
                    ? clips
                    : soundtrackItems"
                :key="item.id"
                :item="item"
                :achievements="game.achievements"
                :profiles="game.profilesEnabled ? profiles : undefined"
                @preview="onPreviewMedia($event.url)"
                @delete="removeMedia"
                @save="saveMediaItem"
              />
            </div>

            <div v-if="activeTabTrash.length" class="trash-section">
              <button
                type="button"
                class="trash-toggle"
                @click="showMediaTrash = !showMediaTrash"
              >
                {{ showMediaTrash ? "▾" : "▸" }} Recently deleted ({{
                  activeTabTrash.length
                }})
              </button>
              <ul v-if="showMediaTrash" class="trash-list">
                <li
                  v-for="item in activeTabTrash"
                  :key="item.id"
                  class="trash-row"
                >
                  <span class="trash-name">{{
                    item.filename.split("_").slice(1).join("_")
                  }}</span>
                  <span class="trash-meta"
                    >purges in {{ daysUntil(item.purge_at) }}d</span
                  >
                  <button
                    type="button"
                    class="secondary-button small"
                    @click="restoreMediaItem(item)"
                  >
                    Restore
                  </button>
                </li>
              </ul>
            </div>
          </template>
        </div>
      </div>
      <div
        v-if="lightboxUrl"
        class="lightbox-backdrop"
        @click="lightboxUrl = null"
      >
        <img :src="lightboxUrl" alt="" class="lightbox-image" />
      </div>
    </section>

    <section v-else-if="activeTab === 'Saves'" class="files-panel">
      <h2>Saves</h2>
      <div class="panel-body">
        <ViewUploadSidebar v-model="panelMode" />
        <div class="panel-content">
          <template v-if="panelMode === 'upload'">
            <UploadDropzone
              accept="*/*"
              :uploading="saveUploading.has('')"
              title="Drop a new save here"
              hint="You'll be asked to name it: one game can hold as many named saves as you want"
              @files-selected="onNewSaveSelected"
              @drop-error="onDropError"
            />
            <div v-if="filesError" class="form-error">{{ filesError }}</div>
          </template>

          <template v-else>
            <p
              v-if="!saveArchives.length && saveArchivesLoaded"
              class="empty-row"
            >
              No saves yet: switch to Upload to add one.
            </p>
            <div v-else class="archive-grid">
              <div
                v-for="archive in saveArchives"
                :key="archive.id"
                class="archive-card"
              >
                <div class="archive-card-header">
                  <span class="archive-name">{{ archive.name }}</span>
                  <div class="archive-card-actions">
                    <button
                      type="button"
                      class="icon-button"
                      title="Rename"
                      @click="onRenameArchive(archive, false)"
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      class="icon-button"
                      title="Delete"
                      @click="onDeleteArchive(archive, false)"
                    >
                      ✕
                    </button>
                  </div>
                </div>
                <p class="archive-meta">
                  {{ archive.versions.length }} version{{
                    archive.versions.length === 1 ? "" : "s"
                  }}
                  · latest
                  {{
                    archive.versions[0]
                      ? formatArchiveDate(archive.versions[0].uploaded_at)
                      : "N/A"
                  }}
                </p>
                <div class="archive-actions-row">
                  <a
                    v-if="archive.versions[0]"
                    :href="archive.versions[0].url"
                    class="secondary-button small"
                    >Download latest</a
                  >
                  <label class="secondary-button small upload-label">
                    {{
                      saveUploading.has(archive.id)
                        ? "Uploading…"
                        : "Add new version"
                    }}
                    <input
                      type="file"
                      class="hidden-input"
                      :disabled="saveUploading.has(archive.id)"
                      @change="
                        onAddSaveVersion(
                          archive,
                          Array.from(
                            ($event.target as HTMLInputElement).files ?? [],
                          ),
                        )
                      "
                    />
                  </label>
                  <button
                    v-if="archive.versions.length > 1"
                    type="button"
                    class="secondary-button small"
                    @click="
                      expandedSaveId =
                        expandedSaveId === archive.id ? null : archive.id
                    "
                  >
                    {{
                      expandedSaveId === archive.id ? "Hide history" : "History"
                    }}
                  </button>
                </div>
                <ul
                  v-if="expandedSaveId === archive.id"
                  class="archive-history"
                >
                  <li
                    v-for="version in archive.versions.slice(1)"
                    :key="version.id"
                    class="archive-history-row"
                  >
                    <a :href="version.url" class="file-name">{{
                      formatArchiveDate(version.uploaded_at)
                    }}</a>
                    <span class="file-size">{{
                      formatFileSize(version.size)
                    }}</span>
                    <button
                      type="button"
                      class="tile-remove-inline"
                      title="Delete this version"
                      @click="onDeleteVersion(archive, version, false)"
                    >
                      ✕
                    </button>
                  </li>
                </ul>
              </div>
            </div>
          </template>

          <div v-if="saveTrash.length" class="trash-section">
            <button
              type="button"
              class="trash-toggle"
              @click="showSaveTrash = !showSaveTrash"
            >
              {{ showSaveTrash ? "▾" : "▸" }} Recently deleted ({{
                saveTrash.length
              }})
            </button>
            <ul v-if="showSaveTrash" class="trash-list">
              <li
                v-for="archive in saveTrash"
                :key="archive.id"
                class="trash-row"
              >
                <span class="trash-name">{{ archive.name }}</span>
                <span class="trash-meta"
                  >purges in {{ daysUntil(archive.purge_at) }}d</span
                >
                <button
                  type="button"
                  class="secondary-button small"
                  @click="onRestoreArchive(archive, false)"
                >
                  Restore
                </button>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </section>

    <section v-else-if="activeTab === 'Docs'" class="files-panel">
      <h2>Docs</h2>
      <div class="panel-body">
        <ViewUploadSidebar v-model="panelMode" />
        <div class="panel-content">
          <template v-if="panelMode === 'upload'">
            <UploadDropzone
              accept="*/*"
              :uploading="uploadingFiles"
              title="Drop documents here"
              hint="Any file format: drag and drop, or click to browse"
              @files-selected="onGameFilesSelected($event, 'doc')"
              @drop-error="onDropError"
            />
            <p class="section-hint">
              Manuals, walkthroughs, strategy guides: any file format.
            </p>
            <div v-if="filesError" class="form-error">{{ filesError }}</div>
          </template>

          <template v-else>
            <p v-if="!docsFiles.length" class="empty-row">
              No docs yet: switch to Upload to add one.
            </p>
            <ul v-else class="file-list">
              <li
                v-for="file in docsFiles"
                :key="file.filename"
                class="file-row"
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
                  <path
                    d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
                  />
                  <path d="M14 2v6h6" />
                </svg>
                <a
                  :href="file.url"
                  class="file-name"
                  target="_blank"
                  rel="noopener noreferrer"
                  >{{ displayFileName(file.filename) }}</a
                >
                <span class="file-size">{{ formatFileSize(file.size) }}</span>
                <button
                  type="button"
                  class="tile-remove-inline"
                  title="Delete"
                  @click="removeGameFile('doc', file)"
                >
                  ✕
                </button>
              </li>
            </ul>
          </template>

          <div v-if="docsTrash.length" class="trash-section">
            <button
              type="button"
              class="trash-toggle"
              @click="showDocsTrash = !showDocsTrash"
            >
              {{ showDocsTrash ? "▾" : "▸" }} Recently deleted ({{
                docsTrash.length
              }})
            </button>
            <ul v-if="showDocsTrash" class="trash-list">
              <li
                v-for="file in docsTrash"
                :key="file.filename"
                class="trash-row"
              >
                <span class="trash-name">{{
                  displayFileName(file.filename)
                }}</span>
                <span class="trash-meta"
                  >purges in {{ daysUntil(file.purge_at) }}d</span
                >
                <button
                  type="button"
                  class="secondary-button small"
                  @click="restoreFileItem('doc', file)"
                >
                  Restore
                </button>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </section>

    <section v-else-if="activeTab === 'World Map'" class="world-map-panel">
      <h2>World Map</h2>
      <div class="panel-body">
        <ViewUploadSidebar v-model="panelMode" />
        <div class="panel-content">
          <template v-if="panelMode === 'upload'">
            <div class="world-map-uploads">
              <div class="world-map-upload-col">
                <h3>New World</h3>
                <UploadDropzone
                  accept="*/*"
                  :uploading="saveUploading.has('')"
                  title="Drop a world save .zip here"
                  hint="Zip the world folder (the one containing level.dat): you'll be asked to name it"
                  @files-selected="onNewWorldSelected"
                  @drop-error="onDropError"
                />
              </div>

              <div class="world-map-upload-col">
                <h3>Modpack</h3>
                <UploadDropzone
                  accept="*/*"
                  :uploading="uploadingFiles"
                  title="Drop your modpack .zip here"
                  hint="Optional: kept alongside for reference, not tied to a specific world"
                  @files-selected="onGameFilesSelected($event, 'modpack')"
                  @drop-error="onDropError"
                />
                <ul v-if="modpackFiles.length" class="file-list">
                  <li
                    v-for="file in modpackFiles"
                    :key="file.filename"
                    class="file-row"
                  >
                    <a
                      :href="file.url"
                      class="file-name"
                      target="_blank"
                      rel="noopener noreferrer"
                      >{{ displayFileName(file.filename) }}</a
                    >
                    <span class="file-size">{{
                      formatFileSize(file.size)
                    }}</span>
                    <button
                      type="button"
                      class="tile-remove-inline"
                      title="Delete"
                      @click="removeGameFile('modpack', file)"
                    >
                      ✕
                    </button>
                  </li>
                </ul>
                <div v-if="modpackTrash.length" class="trash-section">
                  <button
                    type="button"
                    class="trash-toggle"
                    @click="showModpackTrash = !showModpackTrash"
                  >
                    {{ showModpackTrash ? "▾" : "▸" }} Recently deleted ({{
                      modpackTrash.length
                    }})
                  </button>
                  <ul v-if="showModpackTrash" class="trash-list">
                    <li
                      v-for="file in modpackTrash"
                      :key="file.filename"
                      class="trash-row"
                    >
                      <span class="trash-name">{{
                        displayFileName(file.filename)
                      }}</span>
                      <span class="trash-meta"
                        >purges in {{ daysUntil(file.purge_at) }}d</span
                      >
                      <button
                        type="button"
                        class="secondary-button small"
                        @click="restoreFileItem('modpack', file)"
                      >
                        Restore
                      </button>
                    </li>
                  </ul>
                </div>
              </div>
            </div>
            <div v-if="filesError" class="form-error">{{ filesError }}</div>
          </template>

          <template v-else>
            <div v-if="worldMaps.length" class="world-map-grid">
              <div
                v-for="world in worldMaps"
                :key="world.id"
                class="world-map-card"
                :class="{ rendering: world.status === 'rendering' }"
              >
                <div
                  class="world-map-thumb"
                  @click="
                    world.has_thumbnail ? viewWorldMap(world.id) : undefined
                  "
                >
                  <img
                    v-if="world.has_thumbnail"
                    :src="worldMapThumbnailUrl(game.id, world.id)"
                    alt=""
                  />
                  <div v-else class="world-map-thumb-placeholder">
                    <svg
                      viewBox="0 0 24 24"
                      width="28"
                      height="28"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z" />
                      <path d="M9 3v15M15 6v15" />
                    </svg>
                  </div>
                  <div
                    v-if="world.status === 'rendering'"
                    class="world-map-progress"
                  >
                    <div class="world-map-progress-fill"></div>
                  </div>
                </div>
                <div class="world-map-card-body">
                  <div class="archive-card-header">
                    <span class="archive-name">{{ world.name }}</span>
                    <div class="archive-card-actions">
                      <button
                        type="button"
                        class="icon-button"
                        title="Rename"
                        @click="onRenameArchive(world, true)"
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        class="icon-button"
                        title="Delete"
                        @click="onDeleteArchive(world, true)"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                  <span class="world-map-status" :class="world.status">{{
                    world.detail || world.status
                  }}</span>
                  <div class="world-map-card-actions">
                    <button
                      type="button"
                      class="secondary-button small"
                      :disabled="
                        worldMapStarting.has(world.id) ||
                        world.status === 'rendering'
                      "
                      @click="startWorldMapRender(world.id)"
                    >
                      {{
                        world.status === "rendering"
                          ? "Rendering…"
                          : world.has_thumbnail
                            ? "Re-render"
                            : "Render Map"
                      }}
                    </button>
                    <button
                      v-if="world.has_thumbnail"
                      type="button"
                      class="primary-button small"
                      @click="viewWorldMap(world.id)"
                    >
                      View Map
                    </button>
                    <label class="secondary-button small upload-label">
                      {{
                        saveUploading.has(world.id)
                          ? "Uploading…"
                          : "New version"
                      }}
                      <input
                        type="file"
                        class="hidden-input"
                        :disabled="saveUploading.has(world.id)"
                        @change="
                          onAddWorldVersion(
                            world,
                            Array.from(
                              ($event.target as HTMLInputElement).files ?? [],
                            ),
                          )
                        "
                      />
                    </label>
                  </div>
                </div>
              </div>
            </div>
            <p v-else-if="worldMapsLoaded" class="empty-row">
              No worlds yet: switch to Upload to add a world save.
            </p>

            <div v-if="worldTrash.length" class="trash-section">
              <button
                type="button"
                class="trash-toggle"
                @click="showWorldTrash = !showWorldTrash"
              >
                {{ showWorldTrash ? "▾" : "▸" }} Recently deleted ({{
                  worldTrash.length
                }})
              </button>
              <ul v-if="showWorldTrash" class="trash-list">
                <li
                  v-for="world in worldTrash"
                  :key="world.id"
                  class="trash-row"
                >
                  <span class="trash-name">{{ world.name }}</span>
                  <span class="trash-meta"
                    >purges in {{ daysUntil(world.purge_at) }}d</span
                  >
                  <button
                    type="button"
                    class="secondary-button small"
                    @click="onRestoreArchive(world, true)"
                  >
                    Restore
                  </button>
                </li>
              </ul>
            </div>

            <iframe
              v-if="activeMapArchiveId"
              :src="worldMapViewUrl(game.id, activeMapArchiveId)"
              class="world-map-frame"
              title="World map"
            ></iframe>
          </template>
        </div>
      </div>
    </section>

    <section v-else-if="activeTab === 'Stats'" class="stats-panel">
      <h2>Stats</h2>
      <div class="stats-grid">
        <div class="stat-tile">
          <span class="stat-label">Total playtime</span>
          <span class="stat-value">{{ statsPlaytimeLabel }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Achievements</span>
          <span class="stat-value">
            {{
              game.achievementTotal
                ? `${unlockedAchievements.length} / ${game.achievementTotal}`
                : "N/A"
            }}
          </span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Completion</span>
          <span class="stat-value">{{
            game.achievementTotal ? `${game.achievementPercent}%` : "N/A"
          }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Rating</span>
          <span class="stat-value">{{
            tally ? `${tally.sum.toFixed(1)} / ${tally.max}` : "N/A"
          }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Status</span>
          <span class="stat-value">{{ game.status }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Source</span>
          <span class="stat-value">{{ game.source || "N/A" }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Date added</span>
          <span class="stat-value">{{ formatStatsDate(game.dateAdded) }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Last played</span>
          <span class="stat-value">{{
            formatStatsDate(game.lastPlayedAt)
          }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">First achievement</span>
          <span class="stat-value">{{ formatStatsDate(firstUnlockedAt) }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Latest achievement</span>
          <span class="stat-value">{{ formatStatsDate(lastUnlockedAt) }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">Purchase date</span>
          <span class="stat-value">{{
            formatStatsDate(game.ownership.purchaseDate)
          }}</span>
        </div>
        <div v-if="game.completionDate" class="stat-tile">
          <span class="stat-label">100% completed</span>
          <span class="stat-value">{{
            formatStatsDate(game.completionDate)
          }}</span>
        </div>
      </div>
    </section>

    <section v-else-if="activeTab === 'History'" class="history-panel">
      <h2>Metadata History</h2>
      <p v-if="fieldChangesLoading" class="empty-state">Loading…</p>
      <p v-else-if="fieldChangesError" class="empty-state">
        {{ fieldChangesError }}
      </p>
      <p v-else-if="!fieldChanges.length" class="empty-state">
        No metadata changes yet. Edits from the game form or a metadata refresh
        show up here.
      </p>
      <ul v-else class="history-list">
        <li
          v-for="change in fieldChanges"
          :key="change.id"
          class="history-entry"
        >
          <div class="history-entry-head">
            <span class="history-field">{{
              FIELD_CHANGE_LABELS[change.fieldName] || change.fieldName
            }}</span>
            <span class="history-date">{{
              formatFieldChangeDate(change.changedAt)
            }}</span>
          </div>
          <div class="history-values">
            <span class="history-old">{{ change.oldValue || "Empty" }}</span>
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M5 12h14" />
              <path d="M13 6l6 6-6 6" />
            </svg>
            <span class="history-new">{{ change.newValue || "Empty" }}</span>
          </div>
        </li>
      </ul>
    </section>

    <section v-else-if="activeTab === 'Collector Card'" class="card-tab-panel">
      <h2>Collector Card</h2>
      <p v-if="gameCardsLoading" class="empty-state">Loading…</p>
      <template v-else-if="gameCards.length">
        <p class="empty-state">
          {{ gameCards.length === 1 ? "1 card" : `${gameCards.length} cards` }}
          for {{ game.title }}.
        </p>
        <div class="card-links">
          <button
            v-for="c in gameCards"
            :key="c.id"
            type="button"
            class="card-open-btn"
            @click="router.push(`/cards/${c.id}`)"
          >
            View card #{{ String(c.archiveNumber ?? 0).padStart(3, "0") }}
          </button>
        </div>
      </template>
      <template v-else>
        <p class="empty-state">No card generated yet for {{ game.title }}.</p>
        <p v-if="cardTabError" class="empty-state error">{{ cardTabError }}</p>
        <button
          type="button"
          class="card-open-btn"
          :disabled="creatingCard"
          @click="createCardForGame"
        >
          {{ creatingCard ? "Creating…" : "Create card" }}
        </button>
      </template>
    </section>
  </main>

  <main v-else class="not-found">
    <p>Game not found.</p>
  </main>
</template>

<style scoped>
.detail {
  position: relative;
  font-family: system-ui, sans-serif;
  color: #fff;
  min-height: 100vh;
  background: #121212;
  overflow: hidden;
}
.detail-skeleton-body {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.detail-skeleton-pills,
.detail-skeleton-tabs {
  display: flex;
  gap: 10px;
}
.ambient-bg {
  position: fixed;
  inset: 0;
  background-size: cover;
  background-position: center;
  filter: blur(80px);
  opacity: 0.25;
  transform: scale(1.2);
  z-index: 0;
}
.hero,
.tabs,
.overview,
.achievements,
.notes-panel,
.accounts-panel,
.files-panel,
.media-panel,
.stats-panel,
.world-map-panel {
  position: relative;
  z-index: 1;
}
.hero {
  position: relative;
  background-size: cover;
  background-position: center;
  min-height: 360px;
  display: flex;
  align-items: flex-end;
}
.hero-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    rgba(18, 18, 18, 0) 40%,
    rgba(18, 18, 18, 0.85) 85%,
    #121212 100%
  );
}
.hero-inner {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 1600px;
  margin: 0 auto;
  /* clear of the floating menu/back buttons */
  padding: 72px 24px 28px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 18px;
}
.hero-inner h1 {
  margin: 0;
  font-size: 2.4rem;
  /* the inherited line height is a fixed 23px */
  line-height: 1.15;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.6);
}
@media (max-width: 600px) {
  .hero-inner h1 {
    font-size: 1.8rem;
  }
}
.parent-breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ccc;
  font-size: 0.9rem;
  text-decoration: none;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.6);
  margin-bottom: -8px;
}
.parent-breadcrumb:hover {
  color: #fff;
}
.relationship-tag {
  background: rgba(214, 138, 52, 0.22);
  color: #d68a34;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.variants-section,
.similar-games-section {
  margin-bottom: 24px;
}
.variants-heading {
  margin: 0 0 10px;
  font-size: 0.85rem;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.variants-row {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.variant-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  width: 110px;
  flex-shrink: 0;
  text-decoration: none;
  padding: 8px;
  border-radius: 10px;
  transition: background 0.15s ease;
}
.variant-card:hover {
  background: rgba(255, 255, 255, 0.06);
}
.variant-cover {
  width: 90px;
  height: 135px;
  object-fit: cover;
  border-radius: 6px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
}
.variant-title {
  color: #fff;
  font-size: 0.76rem;
  font-weight: 600;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.badge {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  padding: 4px 14px;
  font-size: 13px;
  text-transform: capitalize;
  color: #ddd;
}
.rating-badge {
  color: #d68a34;
}
.stale-badge {
  background: rgba(220, 38, 38, 0.18);
  color: #fca5a5;
  text-transform: none;
}
.achievement-progress-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  cursor: pointer;
  font: inherit;
  text-transform: none;
}
.achievement-progress-badge svg {
  flex-shrink: 0;
  opacity: 0.85;
}
.achievement-progress-badge:hover {
  background: rgba(214, 138, 52, 0.22);
  color: #d68a34;
}
.hero-actions {
  position: absolute;
  bottom: 20px;
  right: 24px;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 8px;
  opacity: 0;
  transition: opacity 0.2s ease;
}
.hero:hover .hero-actions {
  opacity: 1;
}
.hero-icon-button {
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: #fff;
  border-radius: 50%;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.hero-icon-button:hover {
  background: rgba(0, 0, 0, 0.7);
}
.hero-icon-button.active {
  color: #d68a34;
  border-color: rgba(214, 138, 52, 0.5);
}
.edit-button {
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: #fff;
  border-radius: 999px;
  padding: 8px 20px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}
.edit-button:hover {
  background: rgba(0, 0, 0, 0.7);
}
.meta {
  text-transform: capitalize;
  color: #ddd;
}
.tabs {
  display: flex;
  gap: 4px;
  width: 100%;
  max-width: 1600px;
  margin: 16px auto 0;
  padding: 8px 16px;
  box-sizing: border-box;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  /* a screen too narrow for every tab scrolls the bar instead of silently
     clipping the later ones, this was previously invisible rather than
     reachable at all below ~840px wide */
  overflow-x: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
  overflow-x: auto;
}
.tabs::-webkit-scrollbar {
  display: none;
}
.tab {
  background: rgba(255, 255, 255, 0.06);
  border: none;
  color: #ccc;
  padding: 8px 18px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.tab:hover {
  background: #3a3a3a;
  color: #fff;
}
.tab.active {
  background: #d68a34;
  color: #121212;
}
.overview {
  width: 100%;
  max-width: 1600px;
  margin: 0 auto;
  padding: 24px;
  box-sizing: border-box;
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 24px;
  align-items: start;
}
@media (max-width: 860px) {
  /* the details sidebar has real, sometimes long content (platforms,
     ownership, links), stacking it below the description keeps it
     reachable instead of squeezed into a column with no room */
  .overview {
    grid-template-columns: 1fr;
    padding: 16px;
  }
  .details-panel {
    margin-right: 0;
  }
  /* grid items default to min-width:auto (their content's natural size),
     without overriding it, a single wide descendant anywhere inside these
     two (a media row, a long link, a table) forces the "1fr" track back
     out to that descendant's width instead of actually shrinking to fit */
  .overview-main,
  .details-panel {
    min-width: 0;
  }
}
.text-button {
  background: none;
  border: none;
  color: #d68a34;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  /* larger tap target without moving the text */
  padding: 6px 4px;
  margin: -6px -4px;
}
.text-button:hover {
  text-decoration: underline;
}
.text-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.form-error-inline {
  color: #fca5a5;
  font-size: 12.5px;
  margin: 6px 0;
}
.log-playtime-button {
  display: block;
  margin-top: 4px;
}
.related-bounties {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 720px;
  margin-bottom: 18px;
}
.related-bounty-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(214, 138, 52, 0.08);
  border: 1px solid rgba(214, 138, 52, 0.3);
  border-radius: 10px;
  padding: 12px 16px;
  text-decoration: none;
  transition: background 0.15s ease;
}
.related-bounty-card:hover {
  background: rgba(214, 138, 52, 0.15);
}
.related-bounty-icon {
  font-size: 18px;
  flex-shrink: 0;
}
.related-bounty-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.related-bounty-title {
  color: #fff;
  font-weight: 600;
  font-size: 14px;
}
.related-bounty-meta {
  color: #d6a878;
  font-size: 12px;
  text-transform: capitalize;
}
.resume-note-card {
  max-width: 720px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 20px;
}
.resume-note-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.resume-note-header h3 {
  margin: 0;
  font-size: 14px;
  color: #fff;
}
.resume-note-text {
  color: #ddd;
  font-size: 13.5px;
  line-height: 1.6;
  margin: 0;
  white-space: pre-wrap;
}
.resume-note-empty {
  color: #777;
  font-size: 13px;
  margin: 0;
}
.resume-note-textarea {
  width: 100%;
  box-sizing: border-box;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #f5f5f5;
  padding: 10px 12px;
  font: inherit;
  font-size: 13.5px;
  resize: vertical;
}
.resume-note-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
}
.description-wrap {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 720px;
  padding-left: 16px;
  border-left: 3px solid #d68a34;
}
.description-html {
  color: #ddd;
  font-size: 16px;
  line-height: 1.7;
}
.description-html :deep(img),
.description-html :deep(video) {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
  margin: 10px 0;
  display: block;
}
.description-html :deep(h1),
.description-html :deep(h2),
.description-html :deep(h3) {
  margin: 18px 0 6px;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
}
.description-html :deep(p) {
  margin: 0 0 12px;
}
.description-html :deep(a) {
  color: #d68a34;
}
.description-html :deep(ul) {
  padding-left: 20px;
  margin: 0 0 12px;
}
.rating-breakdown {
  display: flex;
  gap: 12px;
  margin-top: 24px;
  flex-wrap: wrap;
}
.rating-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid #232323;
  border-radius: 10px;
  padding: 12px 18px;
  min-width: 90px;
}
.rating-label {
  color: #999;
  font-size: 13px;
}
.rating-score {
  color: #d68a34;
  font-size: 18px;
  font-weight: 600;
}
.details-panel {
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 6px 18px 16px;
  background: rgba(0, 0, 0, 0.3);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  margin-right: -24px;
}
.panel-title {
  margin: 14px 0 6px;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #777;
  font-weight: 700;
}
.detail-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 0;
  font-size: 14px;
  border-bottom: 1px solid #202020;
}
.detail-row:last-child {
  border-bottom: none;
}
.detail-label {
  color: #999;
}
.detail-value {
  color: #fff;
}
.feature-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.feature-pill {
  background: #2a2a2a;
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 11px;
  color: #ccc;
}
.platforms {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.platform-row {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.platform-line {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  font-size: 14px;
}
.platform-name {
  color: #fff;
  font-weight: 600;
}
.platform-meta {
  color: #999;
  white-space: nowrap;
}
.platform-last-played {
  color: #666;
  font-size: 12px;
}
.links-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.links-list a {
  color: #d68a34;
  font-size: 14px;
  text-decoration: none;
}
.links-list a:hover {
  text-decoration: underline;
}
.ownership-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: #ddd;
  font-size: 14px;
}
.ownership-format {
  text-transform: capitalize;
  color: #fff;
  font-weight: 600;
}
.trophy-summary {
  display: flex;
  gap: 20px;
  margin: 16px 0 24px;
}
.trophy-count {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ccc;
  font-size: 14px;
  font-weight: 600;
}
.trophy-badge {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: inline-block;
}
.trophy-badge-bronze {
  background: #b06a35;
  border: 2px solid #7a4a25;
}
.trophy-badge-silver {
  background: #b8b8b8;
  border: 2px solid #7a7a7a;
}
.trophy-badge-gold {
  background: #d4af37;
  border: 2px solid #9a7a1a;
}
.trophy-badge-platinum {
  background: #a8b8c8;
  border: 2px solid #6a7a8a;
}
.trophy-badge.dim {
  background: #2a2a2a;
  border-color: #3a3a3a;
}
.achievement-list {
  list-style: none;
  padding: 0;
  margin-top: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.achievement-row {
  display: flex;
  gap: 14px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid #232323;
  border-radius: 10px;
  align-items: center;
  text-decoration: none;
  color: inherit;
}
.achievement-icon {
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 10px;
  background-size: cover;
  background-position: center;
  background-color: #1a1a1a;
  flex-shrink: 0;
}
.achievement-row:not(.unlocked) .achievement-icon {
  filter: grayscale(100%) brightness(0.5);
}
.achievement-badge {
  position: absolute;
  bottom: -6px;
  right: -6px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #1a1a1a;
  border: 2px solid #121212;
}
.badge-bronze {
  background: #b06a35;
}
.badge-silver {
  background: #b8b8b8;
}
.badge-gold {
  background: #d4af37;
}
.badge-locked {
  background: #3a3a3a;
  color: #888;
}
.achievement-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.achievement-name {
  color: #fff;
  font-weight: 600;
  font-size: 15px;
}
.achievement-row:not(.unlocked) .achievement-name {
  color: #999;
}
.achievement-description {
  color: #999;
  font-size: 13px;
}
.achievement-unlocked-at {
  color: #d68a34;
  font-size: 12px;
  margin-top: 4px;
}
.achievement-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.progress-bar {
  flex: 1;
  max-width: 160px;
  height: 6px;
  background: #2a2a2a;
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: #d68a34;
}
.progress-label {
  color: #999;
  font-size: 12px;
  white-space: nowrap;
}
.achievements-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.percent {
  color: #d68a34;
}
.notes-panel {
  width: 100%;
  max-width: 1600px;
  margin: 0 auto;
  padding: 24px;
  box-sizing: border-box;
}
.notes-list-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.notes-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.notes-header-row h2 {
  margin: 0;
  font-size: 1.1rem;
}
.notes-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.notes-list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 12px 16px;
  cursor: pointer;
  transition:
    background 0.15s ease,
    border-color 0.15s ease;
}
.notes-list-row:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: #3a3a3a;
}
.note-name {
  color: #fff;
  font-weight: 600;
}
.notes-list-actions {
  display: flex;
  gap: 8px;
}
.account-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.account-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid #3a3a3a;
  border-radius: 999px;
  color: #ccc;
  padding: 6px 12px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}
.account-chip:hover {
  border-color: #d68a34;
}
.account-chip.active {
  background: rgba(214, 138, 52, 0.18);
  border-color: #d68a34;
  color: #d68a34;
}
.account-add {
  display: flex;
  gap: 6px;
}
.account-add input {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 999px;
  color: #fff;
  padding: 6px 12px;
  font-size: 0.8rem;
  min-width: 200px;
}
.checklist-card {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.checklist-card h3 {
  margin: 0;
  font-size: 0.95rem;
  color: #fff;
}
.checklist-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.checklist-progress-label {
  font-size: 0.8rem;
  color: #999;
  font-weight: 600;
}
.checklist-progress-bar {
  height: 5px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}
.checklist-progress-fill {
  height: 100%;
  background: #d68a34;
  transition: width 0.2s ease;
}
.checklist-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.checklist-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 0;
  border-bottom: 1px solid #2a2a2a;
}
.checklist-section-caret {
  color: #777;
  font-size: 0.7rem;
  width: 10px;
}
.checklist-section-title {
  flex: 1;
  color: #fff;
  font-weight: 700;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.checklist-section-count {
  color: #777;
  font-size: 0.75rem;
  font-weight: 600;
}
.checklist-items {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.checklist-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.checklist-move-buttons {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.checklist-move {
  background: none;
  border: none;
  color: #555;
  cursor: pointer;
  font-size: 0.55rem;
  line-height: 1;
  padding: 1px 2px;
}
.checklist-move:hover {
  color: #d68a34;
}
.checklist-label {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  color: #ddd;
  cursor: pointer;
}
.checklist-label span.done {
  color: #777;
  text-decoration: line-through;
}
.checklist-edit-input {
  flex: 1;
  background: #111;
  border: 1px solid #d68a34;
  border-radius: 6px;
  color: #fff;
  padding: 4px 8px;
  font-size: 0.9rem;
}
.checklist-remove {
  background: none;
  border: none;
  color: #777;
  cursor: pointer;
  font-weight: 700;
  padding: 0 4px;
}
.checklist-remove:hover {
  color: #fca5a5;
}
.checklist-add-row {
  display: flex;
  gap: 8px;
}
.checklist-add {
  display: flex;
  gap: 8px;
  flex: 1;
}
.checklist-add input {
  flex: 1;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 8px 10px;
}
.accounts-panel {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px;
  box-sizing: border-box;
}
.accounts-layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 20px;
  align-items: start;
}
.accounts-sidebar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 10px;
  position: sticky;
  top: 24px;
}
.account-list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: none;
  border: none;
  border-radius: 6px;
  color: #ccc;
  padding: 9px 10px;
  font-size: 0.85rem;
  text-align: left;
  cursor: pointer;
}
.account-list-item:hover {
  background: rgba(255, 255, 255, 0.05);
}
.account-list-item.active {
  background: rgba(214, 138, 52, 0.16);
  color: #d68a34;
  font-weight: 600;
}
.account-list-meta {
  color: #888;
  font-size: 0.72rem;
}
.accounts-sidebar .account-add {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding-top: 10px;
  border-top: 1px solid #2a2a2a;
}
.accounts-sidebar .account-add input {
  flex: 1;
  min-width: 0;
  background: none;
  border: none;
  border-radius: 6px;
  color: #fff;
  padding: 7px 8px;
  font-size: 0.85rem;
}
.accounts-sidebar .account-add input:focus {
  outline: none;
  background: rgba(255, 255, 255, 0.05);
}
.accounts-sidebar .account-add button {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1px solid #3a3a3a;
  background: none;
  color: #ccc;
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
}
.accounts-sidebar .account-add button:hover:not(:disabled) {
  border-color: #d68a34;
  color: #d68a34;
}
.accounts-sidebar .account-add button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.accounts-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.accounts-detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.accounts-detail-header h2 {
  margin: 0;
  font-size: 1.2rem;
}
.accounts-detail-actions {
  display: flex;
  gap: 8px;
}
.account-note-card,
.account-stats-card,
.account-gallery-card {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.account-note-card h3,
.account-stats-card h3,
.account-gallery-card h3 {
  margin: 0;
  font-size: 0.95rem;
  color: #fff;
}
.account-note-card textarea {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 10px;
  font: inherit;
  resize: vertical;
}
.account-stats-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: 8px;
  margin-bottom: 4px;
}
.stat-grid.headline {
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  margin-bottom: 14px;
}
.stat-group-heading {
  margin: 4px 0 8px;
  color: #999;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.account-stat-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 8px 6px;
  text-align: center;
}
.account-stat-tile.headline {
  padding: 14px 6px;
  background: rgba(214, 138, 52, 0.1);
  border-color: rgba(214, 138, 52, 0.35);
}
.account-stat-tile.headline .stat-tile-value {
  color: #d68a34;
  font-size: 1.3rem;
}
.stat-tile-label {
  color: #999;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.stat-tile-value {
  color: #fff;
  font-weight: 700;
  font-size: 0.95rem;
}
.stat-tile-icon {
  width: 20px;
  height: 20px;
  object-fit: contain;
  image-rendering: pixelated;
}
.account-stat-tile.headline .stat-tile-icon {
  width: 26px;
  height: 26px;
}
.stat-tile-boss-icon {
  color: #999;
}
.account-history-card {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.account-history-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: none;
  border: none;
  color: #fff;
  font-size: 0.95rem;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}
.account-history-caret {
  color: #777;
  font-size: 0.75rem;
}
.wom-sync-row {
  display: flex;
  gap: 8px;
}
.wom-sync-row input {
  flex: 1;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 8px 10px;
}
.stat-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stat-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 6px;
  align-items: center;
}
.stat-row input {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  color: #fff;
  padding: 6px 8px;
  font-size: 0.85rem;
}
.stat-actions {
  display: flex;
  gap: 8px;
}
.empty-state.small {
  font-size: 0.78rem;
  margin: 0;
}
.stat-history-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 260px;
  overflow-y: auto;
}
.stat-history-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-history-date {
  color: #999;
  font-size: 0.75rem;
  font-weight: 600;
}
.stat-history-values {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.stat-history-chip {
  background: rgba(255, 255, 255, 0.06);
  color: #ccc;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.68rem;
}
.stat-history-chip.gain {
  background: rgba(74, 222, 128, 0.14);
  color: #86efac;
  font-weight: 600;
}
.account-gallery-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.account-gallery-kinds {
  display: flex;
  gap: 6px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #ddd;
  font-size: 0.85rem;
}
.field input {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 10px 12px;
}
.field input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.primary-button,
.small-button,
.danger-button {
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  transition: opacity 0.15s ease;
}
.primary-button {
  background: #d68a34;
  color: #111;
  padding: 10px 12px;
}
.small-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  padding: 7px 10px;
  font-size: 0.8rem;
}
.danger-button {
  background: rgba(220, 38, 38, 0.18);
  color: #fca5a5;
  padding: 8px 10px;
}
.primary-button:disabled,
.danger-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.notes-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 100%;
}
.notes-editor-card {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.notes-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px solid #2a2a2a;
}
.selected-note {
  color: #fff;
  font-weight: 600;
  font-size: 1.05rem;
}
.field input:focus,
.notes-editor textarea:focus {
  outline: none;
  border-color: #d68a34;
}
.notes-editor textarea {
  width: 100%;
  min-height: 420px;
  box-sizing: border-box;
  border: 1px solid #3a3a3a;
  border-radius: 10px;
  background: #111;
  color: #f5f5f5;
  resize: vertical;
  padding: 14px;
  font: inherit;
}
.notes-editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.note-error {
  color: #fca5a5;
}
.empty-state {
  color: #777;
  margin: 0;
}
.empty-state.error {
  color: #fca5a5;
}

.card-tab-panel {
  width: 100%;
  max-width: 1600px;
  margin: 0 auto;
  padding: 24px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
}
.card-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.card-open-btn {
  background: #d68a34;
  color: #121212;
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-weight: 700;
  font-size: 0.9rem;
  cursor: pointer;
}
.card-open-btn:hover {
  opacity: 0.9;
}

/* Screenshots / Clips / Saves / Docs / Stats / History */
.media-panel,
.files-panel,
.world-map-panel,
.stats-panel,
.history-panel {
  width: 100%;
  max-width: 1600px;
  margin: 0 auto;
  padding: 24px;
  box-sizing: border-box;
  position: relative;
  z-index: 1;
}
.panel-body {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}
.panel-content {
  flex: 1;
  min-width: 0;
}
.stats-panel h2,
.history-panel h2 {
  margin: 0;
  font-size: 1.1rem;
}
.stats-panel h2,
.history-panel h2 {
  margin-bottom: 16px;
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.history-entry {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 12px 16px;
}
.history-entry-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.history-field {
  font-weight: 600;
  color: #ccc;
}
.history-date {
  color: #777;
  font-size: 0.8rem;
}
.history-values {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9rem;
}
.history-values svg {
  flex-shrink: 0;
  color: #666;
}
.history-old {
  color: #999;
  text-decoration: line-through;
  text-decoration-color: #444;
}
.history-new {
  color: #d68a34;
}
.upload-label {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}
.hidden-input {
  display: none;
}
.section-hint {
  color: #999;
  font-size: 0.85rem;
  margin: 0 0 16px;
}
.empty-row {
  color: #777;
  font-size: 14px;
}
.form-error {
  color: #fca5a5;
  font-size: 13px;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 14px;
}
.media-panel h2,
.files-panel h2 {
  margin: 0 0 16px;
  font-size: 1.1rem;
}
.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
  margin-top: 16px;
}
.lightbox-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 40px;
  box-sizing: border-box;
}
.lightbox-image {
  max-width: 100%;
  max-height: 100%;
  border-radius: 8px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}
.file-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.file-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 12px 16px;
  color: #999;
}
.file-name {
  color: #fff;
  font-size: 0.9rem;
  text-decoration: none;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-name:hover {
  text-decoration: underline;
}
.world-map-panel h2 {
  margin: 0 0 4px;
  color: #fff;
}
.world-map-uploads {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin: 16px 0;
}
.world-map-upload-col h3 {
  margin: 0 0 8px;
  font-size: 0.85rem;
  color: #ccc;
}
/* Saves: named, versioned archives ---------------------------------------- */
.archive-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.archive-card {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 14px;
}
.archive-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.archive-name {
  color: #fff;
  font-weight: 600;
  font-size: 0.92rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.archive-card-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.icon-button {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: none;
  background: rgba(255, 255, 255, 0.06);
  color: #999;
  cursor: pointer;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon-button:hover {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
}
.archive-meta {
  color: #777;
  font-size: 0.76rem;
  margin: 4px 0 12px;
}
.archive-actions-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.archive-history {
  list-style: none;
  margin: 12px 0 0;
  padding: 10px 0 0;
  border-top: 1px solid #232323;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.archive-history-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
}
.secondary-button.small,
.primary-button.small {
  padding: 6px 10px;
  font-size: 0.76rem;
}

/* Trash: recoverable-for-7-days list, shared by Saves and World Map -------- */
.trash-section {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid #2a2a2a;
}
.trash-toggle {
  background: none;
  border: none;
  color: #999;
  font-size: 0.82rem;
  cursor: pointer;
  padding: 0;
}
.trash-toggle:hover {
  color: #ccc;
}
.trash-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.trash-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  font-size: 0.82rem;
}
.trash-name {
  flex: 1;
  color: #ccc;
}
.trash-meta {
  color: #777;
  font-size: 0.76rem;
}

/* World Map: card grid with thumbnails ------------------------------------- */
.world-map-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}
.world-map-card {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  overflow: hidden;
}
.world-map-thumb {
  position: relative;
  aspect-ratio: 4 / 3;
  background: #0c0f14;
  cursor: default;
}
.world-map-card:has(.world-map-status.done) .world-map-thumb {
  cursor: pointer;
}
.world-map-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  image-rendering: pixelated;
}
.world-map-thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #3a3a3a;
}
.world-map-card-body {
  padding: 12px 14px;
}
.world-map-status {
  display: block;
  font-size: 0.78rem;
  color: #999;
  margin: 4px 0 10px;
}
.world-map-status.error {
  color: #fca5a5;
}
.world-map-status.done {
  color: #86efac;
}
.world-map-status.rendering {
  color: #d68a34;
}
.world-map-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.world-map-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 4px;
  border-radius: 0;
  background: rgba(0, 0, 0, 0.4);
  overflow: hidden;
}
.world-map-progress-fill {
  width: 30%;
  height: 100%;
  border-radius: 999px;
  background: #d68a34;
  animation: world-map-scan 1.2s ease-in-out infinite;
}
@keyframes world-map-scan {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(333%);
  }
}
.world-map-frame {
  width: 100%;
  height: 70vh;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  margin-top: 16px;
  background: #000;
}
.file-size {
  color: #777;
  font-size: 0.78rem;
  flex-shrink: 0;
}
.tile-remove-inline {
  background: none;
  border: none;
  color: #777;
  cursor: pointer;
  font-size: 13px;
  padding: 2px 4px;
  flex-shrink: 0;
}
.tile-remove-inline:hover {
  color: #fca5a5;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 14px;
}
.stat-tile {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stat-label {
  color: #999;
  font-size: 0.76rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.stat-value {
  color: #fff;
  font-size: 1.3rem;
  font-weight: 700;
  text-transform: capitalize;
}
.not-found {
  padding: 24px;
  color: #fff;
}
.note-rendered {
  color: #ddd;
  line-height: 1.6;
  font-size: 14px;
}
.note-rendered :deep(h1),
.note-rendered :deep(h2),
.note-rendered :deep(h3) {
  color: #fff;
  margin: 16px 0 8px;
}
.note-rendered :deep(p) {
  margin: 0 0 10px;
}
.note-rendered :deep(a) {
  color: #d68a34;
}
.note-rendered :deep(code) {
  background: #111;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
.note-rendered :deep(pre) {
  background: #111;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
}
.note-rendered :deep(ul),
.note-rendered :deep(ol) {
  padding-left: 20px;
  margin: 0 0 10px;
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
.confirm-actions .secondary-button,
.confirm-actions .danger-button {
  padding: 10px 18px;
}
.secondary-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
</style>
