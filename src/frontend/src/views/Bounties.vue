<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import { fetchGames, fetchGameAchievements } from "../services/games";
import { listGameScreenshots } from "../services/media";
import type { Game, Achievement } from "../types/game";
import type { MediaItem } from "../services/media";
import {
  fetchBounties,
  createBounty,
  updateBounty,
  completeBounty,
  pauseBounty,
  resumeBounty,
  abandonBounty,
  deleteBounty,
  fetchPointsTotal,
  fetchPointsHistory,
  createObjective,
  updateObjective,
  deleteObjective,
  createEvidence,
  deleteEvidence,
  createJournalEntry,
  deleteJournalEntry,
  fetchRandomBountyProposal,
} from "../services/bounties";
import type {
  Bounty,
  BountyType,
  BountyDifficulty,
  PointTransaction,
  ObjectiveKind,
  EvidenceKind,
  BountyProposal,
} from "../services/bounties";

const TYPE_LABELS: Record<BountyType, string> = {
  completion: "Completion",
  mastery: "Mastery",
  achievement: "Achievement",
  collection: "Collection",
  challenge: "Challenge",
  watch: "Watch",
  custom: "Custom",
};
const DIFFICULTY_LABELS: Record<BountyDifficulty, string> = {
  easy: "Easy",
  normal: "Normal",
  hard: "Hard",
  extreme: "Extreme",
};
const AUTOMATIC_TYPES: BountyType[] = [
  "completion",
  "mastery",
  "achievement",
  "collection",
];
// there's no real scoring engine here, points are freeform per bounty,
// this is purely a suggested scale so difficulty picks translate to
// *something* consistent instead of a blank "just guess a number" field
const SUGGESTED_POINTS: Record<BountyDifficulty, number> = {
  easy: 50,
  normal: 100,
  hard: 200,
  extreme: 400,
};
const OBJECTIVE_KIND_LABELS: Record<ObjectiveKind, string> = {
  checkbox: "Checkbox",
  numeric: "Numeric",
  achievement: "Achievement",
};
const EVIDENCE_KIND_LABELS: Record<EvidenceKind, string> = {
  screenshot: "📸 Screenshot",
  clip: "🎬 Clip",
  document: "📄 Document",
  note: "📝 Note",
  link: "🔗 Link",
};

const bounties = ref<Bounty[]>([]);
const games = ref<Game[]>([]);
const loading = ref(true);
const actionPending = ref<string | null>(null);

const statusFilter = ref<"active" | "completed" | "paused" | "abandoned">(
  "active",
);
const typeFilter = ref<BountyType | "">("");
const difficultyFilter = ref<BountyDifficulty | "">("");
const gameFilter = ref("");
const searchQuery = ref("");

async function loadAll() {
  loading.value = true;
  try {
    const [b, g] = await Promise.all([fetchBounties(), fetchGames()]);
    bounties.value = b;
    games.value = g.slice().sort((a, c) => a.title.localeCompare(c.title));
  } finally {
    loading.value = false;
  }
}
onMounted(loadAll);
onMounted(loadRandomProposal);

const filteredBounties = computed(() =>
  bounties.value.filter((b) => {
    if (b.status !== statusFilter.value) return false;
    if (typeFilter.value && b.type !== typeFilter.value) return false;
    if (difficultyFilter.value && b.difficulty !== difficultyFilter.value)
      return false;
    if (gameFilter.value && b.game_id !== gameFilter.value) return false;
    if (
      searchQuery.value.trim() &&
      !b.title.toLowerCase().includes(searchQuery.value.trim().toLowerCase())
    )
      return false;
    return true;
  }),
);
const activeCount = computed(
  () => bounties.value.filter((b) => b.status === "active").length,
);
const gamesWithBounties = computed(() => {
  const ids = new Set(
    bounties.value.map((b) => b.game_id).filter((id): id is string => !!id),
  );
  return games.value.filter((g) => ids.has(g.id));
});

function progressPercent(b: Bounty): number {
  if (b.progress_mode === "binary") return b.progress_value >= 100 ? 100 : 0;
  if (!b.progress_target || b.progress_target <= 0) return 0;
  return Math.min(
    100,
    Math.round((b.progress_value / b.progress_target) * 100),
  );
}
function progressLabel(b: Bounty): string {
  if (b.progress_mode === "binary")
    return b.status === "completed" ? "Complete" : "Not complete";
  if (b.progress_mode === "percentage")
    return `${Math.round(b.progress_value)}%`;
  return `${b.progress_value} / ${b.progress_target ?? "?"}`;
}
function formatDate(epochSeconds: number) {
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
function deadlineLabel(b: Bounty): string | null {
  if (!b.target_date) return null;
  const daysLeft = Math.ceil((b.target_date - Date.now() / 1000) / 86400);
  if (daysLeft < 0) return `Overdue, was due ${formatDate(b.target_date)}`;
  if (daysLeft === 0) return "Due today";
  return `${daysLeft} day${daysLeft === 1 ? "" : "s"} remaining`;
}

// --- streak: consecutive weeks (Mon-Sun) with at least one bounty
// completed, counting back from the current week ------------------------
function weekStart(unixSeconds: number): number {
  const d = new Date(unixSeconds * 1000);
  const isoDay = (d.getDay() + 6) % 7; // Monday = 0
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - isoDay);
  return d.getTime();
}
const bountyStreakWeeks = computed(() => {
  const weeks = new Set(
    bounties.value
      .filter((b) => b.completed_at !== null)
      .map((b) => weekStart(b.completed_at as number)),
  );
  if (!weeks.size) return 0;
  const oneWeek = 7 * 86_400_000;
  let cursor = weekStart(Math.floor(Date.now() / 1000));
  let streak = 0;
  while (weeks.has(cursor)) {
    streak++;
    cursor -= oneWeek;
  }
  return streak;
});

// --- shareable completion card: a hand-drawn canvas image, downloaded
// straight from the browser, no server round-trip, no image library ------
function shareBountyCard(b: Bounty) {
  const canvas = document.createElement("canvas");
  canvas.width = 1000;
  canvas.height = 560;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const bg = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  bg.addColorStop(0, "#1a1408");
  bg.addColorStop(1, "#121212");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.strokeStyle = "#d68a34";
  ctx.lineWidth = 3;
  ctx.strokeRect(24, 24, canvas.width - 48, canvas.height - 48);

  ctx.fillStyle = "#d68a34";
  ctx.font = "700 22px system-ui, sans-serif";
  ctx.fillText("BOUNTY COMPLETE", 64, 110);

  ctx.fillStyle = "#ffffff";
  ctx.font = "700 52px system-ui, sans-serif";
  wrapText(ctx, b.title, 64, 200, canvas.width - 128, 60);

  const metaY = 360;
  ctx.fillStyle = "#d68a34";
  ctx.font = "600 26px system-ui, sans-serif";
  const metaParts = [TYPE_LABELS[b.type]];
  if (b.difficulty) metaParts.push(DIFFICULTY_LABELS[b.difficulty]);
  if (b.game_title) metaParts.push(b.game_title);
  ctx.fillText(metaParts.join("   ·   "), 64, metaY);

  if (b.points_reward) {
    ctx.fillStyle = "#ffffff";
    ctx.font = "700 26px system-ui, sans-serif";
    ctx.fillText(`+${b.points_reward} pts`, 64, metaY + 50);
  }

  ctx.fillStyle = "#999999";
  ctx.font = "400 18px system-ui, sans-serif";
  const completedLabel = b.completed_at
    ? formatDate(b.completed_at)
    : formatDate(b.created_at);
  ctx.fillText(`Completed ${completedLabel}`, 64, canvas.height - 60);

  const link = document.createElement("a");
  link.download = `${b.title.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-bounty.png`;
  link.href = canvas.toDataURL("image/png");
  link.click();
}
function wrapText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
) {
  const words = text.split(" ");
  let line = "";
  let curY = y;
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      ctx.fillText(line, x, curY);
      line = word;
      curY += lineHeight;
    } else {
      line = test;
    }
  }
  ctx.fillText(line, x, curY);
}

// --- random bounty --------------------------------------------------
const randomProposal = ref<BountyProposal | null>(null);
const randomLoading = ref(false);
const randomAccepting = ref(false);

// a couple of alternative suggestions alongside the main pick, the
// backend only has a single-proposal endpoint, so this calls it a few
// extra times and keeps whatever comes back distinct from the main one,
// rather than only ever offering accept-this-or-reroll
function proposalKey(p: BountyProposal): string {
  return `${p.type}:${p.game_id}:${p.title}`;
}
const suggestionAlternatives = ref<BountyProposal[]>([]);
async function loadSuggestionAlternatives() {
  const seen = new Set(
    randomProposal.value ? [proposalKey(randomProposal.value)] : [],
  );
  const results: BountyProposal[] = [];
  for (let i = 0; i < 5 && results.length < 2; i++) {
    const p = await fetchRandomBountyProposal();
    if (!p) break;
    const key = proposalKey(p);
    if (!seen.has(key)) {
      seen.add(key);
      results.push(p);
    }
  }
  suggestionAlternatives.value = results;
}

async function loadRandomProposal() {
  randomLoading.value = true;
  try {
    randomProposal.value = await fetchRandomBountyProposal();
  } catch {
    randomProposal.value = null;
  } finally {
    randomLoading.value = false;
  }
  void loadSuggestionAlternatives();
}

async function acceptAlternative(proposal: BountyProposal) {
  randomAccepting.value = true;
  try {
    const created = await createBounty({
      title: proposal.title,
      type: proposal.type,
      game_id: proposal.game_id,
      points_reward: proposal.points_reward,
    });
    bounties.value = [created, ...bounties.value];
    suggestionAlternatives.value = suggestionAlternatives.value.filter(
      (p) => proposalKey(p) !== proposalKey(proposal),
    );
    statusFilter.value = "active";
  } finally {
    randomAccepting.value = false;
  }
}

async function acceptRandomProposal() {
  if (!randomProposal.value) return;
  randomAccepting.value = true;
  try {
    const created = await createBounty({
      title: randomProposal.value.title,
      type: randomProposal.value.type,
      game_id: randomProposal.value.game_id,
      points_reward: randomProposal.value.points_reward,
    });
    bounties.value = [created, ...bounties.value];
    randomProposal.value = null;
    statusFilter.value = "active";
    await loadRandomProposal();
  } finally {
    randomAccepting.value = false;
  }
}

// --- create form --------------------------------------------------------
const showAddForm = ref(false);
const newType = ref<BountyType>("custom");
const newTitle = ref("");
const newDescription = ref("");
const newDifficulty = ref<BountyDifficulty | "">("");
const newGameId = ref("");
const newAchievementId = ref("");
const newCollectionName = ref("");
const newProgressTarget = ref<number | null>(null);
const newPoints = ref(0);
const newDeadline = ref("");
const saving = ref(false);
const formError = ref("");

const gameAchievements = ref<Achievement[]>([]);
const loadingAchievements = ref(false);

watch([newType, newGameId], async ([type, gameId]) => {
  if (type !== "achievement" || !gameId) {
    gameAchievements.value = [];
    return;
  }
  loadingAchievements.value = true;
  try {
    gameAchievements.value = await fetchGameAchievements(gameId);
  } finally {
    loadingAchievements.value = false;
  }
});

const knownCollections = computed(() => {
  const names = new Set<string>();
  for (const g of games.value) {
    for (const c of g.collections ?? []) names.add(c);
  }
  return [...names].sort();
});

const needsGame = computed(() =>
  ["completion", "mastery", "achievement"].includes(newType.value),
);
const isAutomatic = computed(() => AUTOMATIC_TYPES.includes(newType.value));

function openAddForm() {
  newType.value = "custom";
  newTitle.value = "";
  newDescription.value = "";
  newDifficulty.value = "";
  newGameId.value = "";
  newAchievementId.value = "";
  newCollectionName.value = "";
  newProgressTarget.value = null;
  newPoints.value = 0;
  newDeadline.value = "";
  formError.value = "";
  showAddForm.value = true;
}

async function submitNewBounty() {
  if (!newTitle.value.trim()) {
    formError.value = "Give the goal a title.";
    return;
  }
  if (needsGame.value && !newGameId.value) {
    formError.value = "Pick a target game.";
    return;
  }
  if (newType.value === "achievement" && !newAchievementId.value) {
    formError.value = "Pick a target achievement.";
    return;
  }
  if (newType.value === "collection" && !newCollectionName.value.trim()) {
    formError.value = "Name the target collection.";
    return;
  }
  saving.value = true;
  formError.value = "";
  try {
    const created = await createBounty({
      title: newTitle.value.trim(),
      description: newDescription.value.trim() || null,
      type: newType.value,
      difficulty: newDifficulty.value || null,
      game_id: newType.value === "collection" ? null : newGameId.value || null,
      target_achievement_id:
        newType.value === "achievement" ? newAchievementId.value : null,
      target_collection_name:
        newType.value === "collection" ? newCollectionName.value.trim() : null,
      progress_mode:
        newType.value === "challenge" ||
        newType.value === "watch" ||
        newType.value === "custom"
          ? "numeric"
          : undefined,
      progress_target: !isAutomatic.value ? newProgressTarget.value : null,
      points_reward: newPoints.value,
      target_date: newDeadline.value
        ? Math.floor(new Date(newDeadline.value).getTime() / 1000)
        : null,
    });
    bounties.value = [created, ...bounties.value];
    showAddForm.value = false;
    statusFilter.value =
      created.status === "completed" ? "completed" : "active";
  } catch (err) {
    formError.value =
      err instanceof Error ? err.message : "Failed to create bounty.";
  } finally {
    saving.value = false;
  }
}

async function doAction(
  bounty: Bounty,
  action: "complete" | "pause" | "resume" | "abandon" | "delete",
) {
  actionPending.value = bounty.id;
  try {
    if (action === "complete") await completeBounty(bounty.id);
    else if (action === "pause") await pauseBounty(bounty.id);
    else if (action === "resume") await resumeBounty(bounty.id);
    else if (action === "abandon") await abandonBounty(bounty.id);
    else if (action === "delete") {
      await deleteBounty(bounty.id);
      bounties.value = bounties.value.filter((b) => b.id !== bounty.id);
      return;
    }
    bounties.value = await fetchBounties();
  } finally {
    actionPending.value = null;
  }
}

// --- manual progress update (challenge/watch/custom) --------------------
const editingProgressId = ref<string | null>(null);
const progressDraft = ref(0);

function startEditProgress(b: Bounty) {
  editingProgressId.value = b.id;
  progressDraft.value = b.progress_value;
}
async function saveProgress(b: Bounty) {
  actionPending.value = b.id;
  try {
    const updated = await updateBounty(b.id, {
      progress_value: progressDraft.value,
    });
    const idx = bounties.value.findIndex((x) => x.id === b.id);
    if (idx !== -1) bounties.value[idx] = updated;
    editingProgressId.value = null;
  } finally {
    actionPending.value = null;
  }
}

// --- expand a card to show objectives + evidence -------------------------
const expandedId = ref<string | null>(null);

function toggleExpand(b: Bounty) {
  expandedId.value = expandedId.value === b.id ? null : b.id;
}

function replaceBounty(updated: Bounty) {
  const idx = bounties.value.findIndex((x) => x.id === updated.id);
  if (idx !== -1) bounties.value[idx] = updated;
}

// --- objectives -----------------------------------------------------
const showObjectiveForm = ref<string | null>(null);
const objTitle = ref("");
const objKind = ref<ObjectiveKind>("checkbox");
const objTarget = ref<number | null>(null);
const objAchievementId = ref("");
const objAchievements = ref<Achievement[]>([]);
const objSaving = ref(false);
const objError = ref("");

function openObjectiveForm(b: Bounty) {
  showObjectiveForm.value = b.id;
  objTitle.value = "";
  objKind.value = "checkbox";
  objTarget.value = null;
  objAchievementId.value = "";
  objError.value = "";
  // otherwise a bounty with no game (or a different game) keeps showing the
  // previously opened bounty's achievement list
  objAchievements.value = [];
  if (b.game_id)
    fetchGameAchievements(b.game_id).then((a) => (objAchievements.value = a));
}

async function submitObjective(b: Bounty) {
  if (!objTitle.value.trim()) {
    objError.value = "Give the objective a title.";
    return;
  }
  if (objKind.value === "achievement" && !objAchievementId.value) {
    objError.value = "Pick an achievement.";
    return;
  }
  objSaving.value = true;
  objError.value = "";
  try {
    const updated = await createObjective(b.id, {
      title: objTitle.value.trim(),
      kind: objKind.value,
      progress_target: objKind.value === "numeric" ? objTarget.value : null,
      target_achievement_id:
        objKind.value === "achievement" ? objAchievementId.value : null,
    });
    replaceBounty(updated);
    showObjectiveForm.value = null;
  } catch (err) {
    objError.value =
      err instanceof Error ? err.message : "Failed to add objective.";
  } finally {
    objSaving.value = false;
  }
}

async function toggleObjectiveDone(
  b: Bounty,
  objectiveId: string,
  done: boolean,
) {
  actionPending.value = objectiveId;
  try {
    const updated = await updateObjective(b.id, objectiveId, { done });
    replaceBounty(updated);
  } finally {
    actionPending.value = null;
  }
}

async function removeObjective(b: Bounty, objectiveId: string) {
  actionPending.value = objectiveId;
  try {
    await deleteObjective(b.id, objectiveId);
    const updated = await fetchBounties();
    const fresh = updated.find((x) => x.id === b.id);
    if (fresh) replaceBounty(fresh);
  } finally {
    actionPending.value = null;
  }
}

// --- evidence ---------------------------------------------------------
const showEvidenceForm = ref<string | null>(null);
const evKind = ref<EvidenceKind>("note");
const evText = ref("");
const evUrl = ref("");
const evMediaId = ref("");
const evMediaOptions = ref<MediaItem[]>([]);
const evSaving = ref(false);
const evError = ref("");

function openEvidenceForm(b: Bounty) {
  showEvidenceForm.value = b.id;
  evKind.value = "note";
  evText.value = "";
  evUrl.value = "";
  evMediaId.value = "";
  evError.value = "";
  // same as objAchievements above, avoid showing the previous bounty's media
  evMediaOptions.value = [];
  if (b.game_id)
    listGameScreenshots(b.game_id).then((m) => (evMediaOptions.value = m));
}

async function submitEvidence(b: Bounty) {
  if (evKind.value === "note" && !evText.value.trim()) {
    evError.value = "Write a note.";
    return;
  }
  if (evKind.value === "link" && !evUrl.value.trim()) {
    evError.value = "Enter a URL.";
    return;
  }
  if (
    (evKind.value === "screenshot" ||
      evKind.value === "clip" ||
      evKind.value === "document") &&
    !evMediaId.value
  ) {
    evError.value = "Pick a file from the game gallery.";
    return;
  }
  evSaving.value = true;
  evError.value = "";
  try {
    await createEvidence(b.id, {
      kind: evKind.value,
      text: evKind.value === "note" ? evText.value.trim() : null,
      url: evKind.value === "link" ? evUrl.value.trim() : null,
      media_item_id: ["screenshot", "clip", "document"].includes(evKind.value)
        ? evMediaId.value
        : null,
    });
    const fresh = await fetchBounties();
    const updatedBounty = fresh.find((x) => x.id === b.id);
    if (updatedBounty) replaceBounty(updatedBounty);
    showEvidenceForm.value = null;
  } catch (err) {
    evError.value =
      err instanceof Error ? err.message : "Failed to add evidence.";
  } finally {
    evSaving.value = false;
  }
}

async function removeEvidence(b: Bounty, evidenceId: string) {
  actionPending.value = evidenceId;
  try {
    await deleteEvidence(b.id, evidenceId);
    const fresh = await fetchBounties();
    const updatedBounty = fresh.find((x) => x.id === b.id);
    if (updatedBounty) replaceBounty(updatedBounty);
  } finally {
    actionPending.value = null;
  }
}

// --- journal ----------------------------------------------------------
const journalDraft = ref<Record<string, string>>({});

async function addJournalEntry(b: Bounty) {
  const text = (journalDraft.value[b.id] ?? "").trim();
  if (!text) return;
  actionPending.value = `journal-${b.id}`;
  try {
    await createJournalEntry(b.id, text);
    journalDraft.value[b.id] = "";
    const fresh = await fetchBounties();
    const updatedBounty = fresh.find((x) => x.id === b.id);
    if (updatedBounty) replaceBounty(updatedBounty);
  } finally {
    actionPending.value = null;
  }
}

async function removeJournalEntry(b: Bounty, entryId: string) {
  actionPending.value = entryId;
  try {
    await deleteJournalEntry(b.id, entryId);
    const fresh = await fetchBounties();
    const updatedBounty = fresh.find((x) => x.id === b.id);
    if (updatedBounty) replaceBounty(updatedBounty);
  } finally {
    actionPending.value = null;
  }
}

// --- points history -------------------------------------------------
const showPoints = ref(false);
const pointsTotal = ref(0);
const pointsHistory = ref<PointTransaction[]>([]);
const pointsLoaded = ref(false);

async function togglePoints() {
  showPoints.value = !showPoints.value;
  if (showPoints.value && !pointsLoaded.value) {
    const [total, history] = await Promise.all([
      fetchPointsTotal(),
      fetchPointsHistory(),
    ]);
    pointsTotal.value = total;
    pointsHistory.value = history;
    pointsLoaded.value = true;
  }
}
</script>

<template>
  <div class="bounties-page">
    <div class="page-header">
      <div>
        <h1>Bounties</h1>
        <p class="subtitle">
          Personal goals and challenges, no points required, but they're there
          if you want them.
        </p>
      </div>
      <div class="header-actions">
        <span
          v-if="bountyStreakWeeks > 0"
          class="streak-pill"
          :title="`${bountyStreakWeeks} consecutive week${bountyStreakWeeks === 1 ? '' : 's'} with a bounty completed`"
        >
          🔥 {{ bountyStreakWeeks }} week{{
            bountyStreakWeeks === 1 ? "" : "s"
          }}
        </span>
        <button type="button" class="points-toggle" @click="togglePoints">
          🏅 {{ showPoints ? "Hide" : "Points" }}
        </button>
        <button type="button" class="add-button" @click="openAddForm">
          + New Bounty
        </button>
      </div>
    </div>

    <div v-if="showPoints" class="points-panel">
      <div class="points-total">
        Total <strong>{{ pointsTotal }}</strong>
      </div>
      <div v-if="pointsHistory.length === 0" class="empty-state">
        No points earned yet.
      </div>
      <div v-else class="points-list">
        <div v-for="t in pointsHistory" :key="t.id" class="points-row">
          <span class="points-amount">+{{ t.amount }}</span>
          <span class="points-reason">{{ t.reason }}</span>
          <span class="points-date">{{ formatDate(t.created_at) }}</span>
        </div>
      </div>
    </div>

    <div v-if="randomProposal" class="random-bounty-card">
      <div class="random-bounty-main">
        <div class="random-bounty-label">🎲 RANDOM BOUNTY</div>
        <div class="random-bounty-body">
          <span class="random-bounty-title">{{ randomProposal.title }}</span>
          <span class="random-bounty-sub"
            >{{ TYPE_LABELS[randomProposal.type] }} ·
            {{ randomProposal.game_title }} · +{{
              randomProposal.points_reward
            }}
            pts</span
          >
        </div>
        <div class="random-bounty-actions">
          <button
            type="button"
            class="save-btn"
            :disabled="randomAccepting"
            @click="acceptRandomProposal"
          >
            Accept
          </button>
          <button
            type="button"
            class="cancel-btn"
            :disabled="randomLoading"
            @click="loadRandomProposal"
          >
            Reroll
          </button>
        </div>
      </div>
      <div v-if="suggestionAlternatives.length" class="random-bounty-alts">
        <span class="random-bounty-alts-label">Or:</span>
        <button
          v-for="alt in suggestionAlternatives"
          :key="proposalKey(alt)"
          type="button"
          class="random-bounty-alt"
          :disabled="randomAccepting"
          @click="acceptAlternative(alt)"
        >
          {{ alt.title }}
          <span class="random-bounty-alt-pts">+{{ alt.points_reward }}</span>
        </button>
      </div>
    </div>

    <div class="filter-row">
      <input
        v-model="searchQuery"
        type="text"
        class="field-input search-input"
        placeholder="Search bounties…"
      />
      <select v-model="typeFilter" class="field-input">
        <option value="">All types</option>
        <option v-for="(label, key) in TYPE_LABELS" :key="key" :value="key">
          {{ label }}
        </option>
      </select>
      <select v-model="difficultyFilter" class="field-input">
        <option value="">All difficulties</option>
        <option
          v-for="(label, key) in DIFFICULTY_LABELS"
          :key="key"
          :value="key"
        >
          {{ label }}
        </option>
      </select>
      <select v-model="gameFilter" class="field-input">
        <option value="">All games</option>
        <option v-for="g in gamesWithBounties" :key="g.id" :value="g.id">
          {{ g.title }}
        </option>
      </select>
    </div>

    <div class="status-tabs">
      <button
        v-for="s in ['active', 'completed', 'paused', 'abandoned'] as const"
        :key="s"
        type="button"
        class="status-tab"
        :class="{ active: statusFilter === s }"
        @click="statusFilter = s"
      >
        {{
          s === "active"
            ? `Active (${activeCount})`
            : s.charAt(0).toUpperCase() + s.slice(1)
        }}
      </button>
    </div>

    <div v-if="loading" class="empty-state">Loading…</div>
    <div v-else-if="filteredBounties.length === 0" class="empty-state">
      {{
        statusFilter === "active"
          ? "No active bounties yet. Set a goal for one of your games."
          : `No ${statusFilter} bounties.`
      }}
    </div>
    <div v-else class="bounty-list">
      <div
        v-for="b in filteredBounties"
        :key="b.id"
        class="bounty-card-wrapper"
      >
        <div class="bounty-card" :class="{ muted: b.status !== 'active' }">
          <div class="bounty-main">
            <div class="bounty-meta-row">
              <router-link
                v-if="b.game_id"
                :to="`/games/${b.game_id}`"
                class="bounty-game-link"
                >{{ b.game_title }}</router-link
              >
              <span class="bounty-type-pill">{{ TYPE_LABELS[b.type] }}</span>
              <span
                v-if="b.difficulty"
                class="bounty-difficulty-pill"
                :class="b.difficulty"
                >{{ DIFFICULTY_LABELS[b.difficulty] }}</span
              >
              <span
                v-if="b.auto_generated"
                class="bounty-auto-pill"
                title="Proposed automatically"
                >🤖 Suggested</span
              >
            </div>
            <span class="bounty-title">{{ b.title }}</span>
            <p v-if="b.description" class="bounty-description">
              {{ b.description }}
            </p>
            <p
              v-if="b.type === 'achievement' && b.target_achievement_name"
              class="bounty-target-note"
            >
              Achievement: {{ b.target_achievement_name }}
            </p>
            <p
              v-if="b.type === 'collection' && b.target_collection_name"
              class="bounty-target-note"
            >
              Collection: {{ b.target_collection_name }}
            </p>
            <p
              v-if="b.required_evidence_kinds.length"
              class="bounty-target-note"
            >
              Suggested evidence:
              {{
                b.required_evidence_kinds
                  .map((k) => EVIDENCE_KIND_LABELS[k])
                  .join(", ")
              }}
            </p>

            <div class="progress-row">
              <div class="progress-track">
                <div
                  class="progress-fill"
                  :style="{ width: progressPercent(b) + '%' }"
                ></div>
              </div>
              <span class="progress-label">{{ progressLabel(b) }}</span>
            </div>

            <div
              v-if="
                b.status === 'active' &&
                b.objectives.length === 0 &&
                !AUTOMATIC_TYPES.includes(b.type)
              "
              class="manual-progress"
            >
              <template v-if="editingProgressId === b.id">
                <input
                  v-model.number="progressDraft"
                  type="number"
                  min="0"
                  class="progress-input"
                />
                <button
                  type="button"
                  class="mini-btn"
                  :disabled="actionPending === b.id"
                  @click="saveProgress(b)"
                >
                  Save
                </button>
                <button
                  type="button"
                  class="mini-btn"
                  @click="editingProgressId = null"
                >
                  Cancel
                </button>
              </template>
              <button
                v-else
                type="button"
                class="mini-btn"
                @click="startEditProgress(b)"
              >
                Update progress
              </button>
            </div>

            <div class="bounty-footer-row">
              <span v-if="b.points_reward" class="bounty-points"
                >+{{ b.points_reward }} pts</span
              >
              <span v-if="deadlineLabel(b)" class="bounty-deadline">{{
                deadlineLabel(b)
              }}</span>
              <span class="bounty-date"
                >Set {{ formatDate(b.created_at) }}</span
              >
              <button type="button" class="mini-btn" @click="toggleExpand(b)">
                {{ expandedId === b.id ? "Hide" : "Objectives & Evidence" }} ({{
                  b.objectives.length + b.evidence.length
                }})
              </button>
            </div>
          </div>

          <div class="bounty-actions">
            <template v-if="b.status === 'active'">
              <button
                type="button"
                class="action-btn complete"
                :disabled="actionPending === b.id"
                title="Mark complete"
                @click="doAction(b, 'complete')"
              >
                ✓
              </button>
              <button
                type="button"
                class="action-btn pause"
                :disabled="actionPending === b.id"
                title="Pause"
                @click="doAction(b, 'pause')"
              >
                ⏸
              </button>
              <button
                type="button"
                class="action-btn abandon"
                :disabled="actionPending === b.id"
                title="Abandon"
                @click="doAction(b, 'abandon')"
              >
                ✕
              </button>
            </template>
            <template v-else-if="b.status === 'paused'">
              <button
                type="button"
                class="action-btn resume"
                :disabled="actionPending === b.id"
                title="Resume"
                @click="doAction(b, 'resume')"
              >
                ▶
              </button>
              <button
                type="button"
                class="action-btn abandon"
                :disabled="actionPending === b.id"
                title="Abandon"
                @click="doAction(b, 'abandon')"
              >
                ✕
              </button>
            </template>
            <button
              v-if="b.status === 'completed'"
              type="button"
              class="action-btn share"
              title="Save a shareable image"
              @click="shareBountyCard(b)"
            >
              ⇩
            </button>
            <button
              v-if="b.status !== 'completed'"
              type="button"
              class="action-btn delete"
              :disabled="actionPending === b.id"
              title="Delete"
              @click="doAction(b, 'delete')"
            >
              🗑
            </button>
          </div>
        </div>

        <div v-if="expandedId === b.id" class="bounty-details">
          <div class="details-section">
            <div class="details-header">
              <h4>Objectives</h4>
              <button
                v-if="b.status === 'active'"
                type="button"
                class="mini-btn"
                @click="openObjectiveForm(b)"
              >
                + Add
              </button>
            </div>
            <div v-if="b.objectives.length === 0" class="empty-state small">
              No objectives, this is a simple goal.
            </div>
            <div v-else class="objective-list">
              <div v-for="o in b.objectives" :key="o.id" class="objective-row">
                <input
                  v-if="o.kind === 'checkbox'"
                  type="checkbox"
                  :checked="o.done"
                  :disabled="b.status !== 'active' || actionPending === o.id"
                  @change="
                    toggleObjectiveDone(
                      b,
                      o.id,
                      ($event.target as HTMLInputElement).checked,
                    )
                  "
                />
                <span
                  v-else
                  class="objective-status"
                  :class="{ done: o.done }"
                  >{{ o.done ? "✓" : "○" }}</span
                >
                <span class="objective-title" :class="{ done: o.done }">{{
                  o.title
                }}</span>
                <span v-if="o.kind === 'numeric'" class="objective-progress"
                  >{{ o.progress_value }} / {{ o.progress_target ?? "?" }}</span
                >
                <span v-if="o.kind === 'achievement'" class="objective-progress"
                  >achievement</span
                >
                <button
                  v-if="b.status === 'active'"
                  type="button"
                  class="mini-btn danger"
                  :disabled="actionPending === o.id"
                  @click="removeObjective(b, o.id)"
                >
                  ✕
                </button>
              </div>
            </div>

            <div v-if="showObjectiveForm === b.id" class="inline-form">
              <input
                v-model="objTitle"
                class="field-input"
                type="text"
                placeholder="Earn 3 badges"
                maxlength="200"
              />
              <select v-model="objKind" class="field-input">
                <option
                  v-for="(label, key) in OBJECTIVE_KIND_LABELS"
                  :key="key"
                  :value="key"
                >
                  {{ label }}
                </option>
              </select>
              <input
                v-if="objKind === 'numeric'"
                v-model.number="objTarget"
                class="field-input"
                type="number"
                min="1"
                placeholder="Target (e.g. 10)"
              />
              <select
                v-if="objKind === 'achievement'"
                v-model="objAchievementId"
                class="field-input"
                :disabled="!b.game_id"
              >
                <option value="">Select an achievement…</option>
                <option v-for="a in objAchievements" :key="a.id" :value="a.id">
                  {{ a.name }}
                </option>
              </select>
              <p v-if="objError" class="form-error small">{{ objError }}</p>
              <div class="inline-form-actions">
                <button
                  type="button"
                  class="mini-btn"
                  @click="showObjectiveForm = null"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  class="mini-btn primary"
                  :disabled="objSaving"
                  @click="submitObjective(b)"
                >
                  {{ objSaving ? "Saving…" : "Add" }}
                </button>
              </div>
            </div>
          </div>

          <div class="details-section">
            <div class="details-header">
              <h4>Evidence</h4>
              <button
                v-if="b.status === 'active'"
                type="button"
                class="mini-btn"
                @click="openEvidenceForm(b)"
              >
                + Add
              </button>
            </div>
            <div v-if="b.evidence.length === 0" class="empty-state small">
              No evidence attached.
            </div>
            <div v-else class="evidence-list">
              <div v-for="e in b.evidence" :key="e.id" class="evidence-row">
                <span class="evidence-kind">{{
                  EVIDENCE_KIND_LABELS[e.kind]
                }}</span>
                <a
                  v-if="e.media_url"
                  :href="e.media_url"
                  target="_blank"
                  rel="noopener"
                  class="evidence-link"
                  >{{ e.media_filename }}</a
                >
                <a
                  v-else-if="e.url"
                  :href="e.url"
                  target="_blank"
                  rel="noopener"
                  class="evidence-link"
                  >{{ e.url }}</a
                >
                <span v-else-if="e.text" class="evidence-text">{{
                  e.text
                }}</span>
                <button
                  type="button"
                  class="mini-btn danger"
                  :disabled="actionPending === e.id"
                  @click="removeEvidence(b, e.id)"
                >
                  ✕
                </button>
              </div>
            </div>

            <div v-if="showEvidenceForm === b.id" class="inline-form">
              <select v-model="evKind" class="field-input">
                <option
                  v-for="(label, key) in EVIDENCE_KIND_LABELS"
                  :key="key"
                  :value="key"
                >
                  {{ label }}
                </option>
              </select>
              <textarea
                v-if="evKind === 'note'"
                v-model="evText"
                class="field-input"
                rows="2"
                placeholder="Write a note"
              ></textarea>
              <input
                v-if="evKind === 'link'"
                v-model="evUrl"
                class="field-input"
                type="text"
                placeholder="https://…"
              />
              <select
                v-if="['screenshot', 'clip', 'document'].includes(evKind)"
                v-model="evMediaId"
                class="field-input"
                :disabled="!b.game_id || evMediaOptions.length === 0"
              >
                <option value="">
                  {{
                    evMediaOptions.length === 0
                      ? "No media in this game's gallery yet"
                      : "Select a file…"
                  }}
                </option>
                <option v-for="m in evMediaOptions" :key="m.id" :value="m.id">
                  {{ m.filename }}
                </option>
              </select>
              <p v-if="evError" class="form-error small">{{ evError }}</p>
              <div class="inline-form-actions">
                <button
                  type="button"
                  class="mini-btn"
                  @click="showEvidenceForm = null"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  class="mini-btn primary"
                  :disabled="evSaving"
                  @click="submitEvidence(b)"
                >
                  {{ evSaving ? "Saving…" : "Add" }}
                </button>
              </div>
            </div>
          </div>

          <div class="details-section">
            <div class="details-header">
              <h4>Journal</h4>
            </div>
            <div v-if="b.journal.length === 0" class="empty-state small">
              No journal entries yet.
            </div>
            <div v-else class="journal-list">
              <div v-for="j in b.journal" :key="j.id" class="journal-entry">
                <span class="journal-date">{{ formatDate(j.created_at) }}</span>
                <span class="journal-text">{{ j.text }}</span>
                <button
                  type="button"
                  class="mini-btn danger"
                  :disabled="actionPending === j.id"
                  @click="removeJournalEntry(b, j.id)"
                >
                  ✕
                </button>
              </div>
            </div>
            <div v-if="b.status === 'active'" class="inline-form">
              <textarea
                v-model="journalDraft[b.id]"
                class="field-input"
                rows="2"
                placeholder="What happened today?"
              ></textarea>
              <div class="inline-form-actions">
                <button
                  type="button"
                  class="mini-btn primary"
                  :disabled="actionPending === `journal-${b.id}`"
                  @click="addJournalEntry(b)"
                >
                  Add entry
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="showAddForm"
      class="confirm-backdrop"
      @click.self="showAddForm = false"
    >
      <div class="confirm-dialog add-form">
        <h3>New Bounty</h3>

        <label class="field-label"
          >Title
          <input
            v-model="newTitle"
            class="field-input"
            type="text"
            placeholder="Finish Elden Ring"
            maxlength="200"
          />
        </label>

        <label class="field-label"
          >Type
          <select v-model="newType" class="field-input">
            <option v-for="(label, key) in TYPE_LABELS" :key="key" :value="key">
              {{ label }}
            </option>
          </select>
        </label>

        <label
          v-if="needsGame || newType === 'challenge' || newType === 'watch'"
          class="field-label"
        >
          Target Game{{ needsGame ? "" : " (optional)" }}
          <select v-model="newGameId" class="field-input">
            <option value="">None</option>
            <option v-for="g in games" :key="g.id" :value="g.id">
              {{ g.title }}
            </option>
          </select>
        </label>

        <label v-if="newType === 'achievement'" class="field-label"
          >Target Achievement
          <select
            v-model="newAchievementId"
            class="field-input"
            :disabled="loadingAchievements || gameAchievements.length === 0"
          >
            <option value="">
              {{ loadingAchievements ? "Loading…" : "Select one…" }}
            </option>
            <option v-for="a in gameAchievements" :key="a.id" :value="a.id">
              {{ a.name }}{{ a.unlockedAt ? " (already unlocked)" : "" }}
            </option>
          </select>
        </label>

        <label v-if="newType === 'collection'" class="field-label"
          >Target Collection
          <input
            v-model="newCollectionName"
            class="field-input"
            type="text"
            list="collection-names"
            placeholder="Souls series"
          />
          <datalist id="collection-names">
            <option v-for="c in knownCollections" :key="c" :value="c" />
          </datalist>
        </label>

        <label v-if="!isAutomatic" class="field-label"
          >Progress Target (optional, numeric goals like "10 games")
          <input
            v-model.number="newProgressTarget"
            class="field-input"
            type="number"
            min="1"
            placeholder="e.g. 10"
          />
        </label>

        <label class="field-label"
          >Difficulty (optional)
          <select v-model="newDifficulty" class="field-input">
            <option value="">None</option>
            <option
              v-for="(label, key) in DIFFICULTY_LABELS"
              :key="key"
              :value="key"
            >
              {{ label }}
            </option>
          </select>
        </label>

        <label class="field-label"
          >Points Reward
          <input
            v-model.number="newPoints"
            class="field-input"
            type="number"
            min="0"
          />
          <span class="field-hint">
            Points are entirely up to you, a rough scale to stay consistent:
            <button
              v-for="(pts, key) in SUGGESTED_POINTS"
              :key="key"
              type="button"
              class="points-suggestion"
              @click="newPoints = pts"
            >
              {{ DIFFICULTY_LABELS[key] }} {{ pts }}
            </button>
          </span>
        </label>

        <label class="field-label"
          >Deadline (optional)
          <input v-model="newDeadline" class="field-input" type="date" />
        </label>

        <label class="field-label"
          >Description (optional)
          <textarea
            v-model="newDescription"
            class="field-input"
            rows="2"
            placeholder="Any extra detail"
          ></textarea>
        </label>

        <p v-if="formError" class="form-error">{{ formError }}</p>
        <div class="dialog-actions">
          <button type="button" class="cancel-btn" @click="showAddForm = false">
            Cancel
          </button>
          <button
            type="button"
            class="save-btn"
            :disabled="saving"
            @click="submitNewBounty"
          >
            {{ saving ? "Saving…" : "Create" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bounties-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 32px 20px 60px;
  color: #ccc;
  font-family: system-ui, sans-serif;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
h1 {
  color: #fff;
  font-size: 24px;
  margin: 0 0 4px;
}
.subtitle {
  color: #999;
  font-size: 13px;
  margin: 0;
}
.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.add-button,
.points-toggle {
  border: none;
  font-weight: 700;
  font-size: 13px;
  padding: 10px 16px;
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
}
.add-button {
  background: #d68a34;
  color: #111;
}
.add-button:hover {
  background: #e6994a;
}
.points-toggle {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  color: #ccc;
}
.points-toggle:hover {
  border-color: #3a3a3a;
  color: #fff;
}
.points-panel {
  background: #161616;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.points-total {
  color: #999;
  font-size: 13px;
  margin-bottom: 10px;
}
.points-total strong {
  color: #d68a34;
  font-size: 18px;
}
.points-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.points-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.points-amount {
  color: #4caf50;
  font-weight: 700;
  width: 50px;
}
.points-reason {
  flex: 1;
  color: #ccc;
}
.points-date {
  color: #666;
  font-size: 11px;
}
.random-bounty-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: linear-gradient(135deg, rgba(214, 138, 52, 0.14), #161616);
  border: 1px solid #d68a34;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.random-bounty-main {
  display: flex;
  align-items: center;
  gap: 14px;
}
.random-bounty-alts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid rgba(214, 138, 52, 0.25);
}
.random-bounty-alts-label {
  color: #999;
  font-size: 12px;
}
.random-bounty-alt {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid #2a2a2a;
  color: #eee;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}
.random-bounty-alt:hover:not(:disabled) {
  border-color: #d68a34;
  color: #d68a34;
}
.random-bounty-alt:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.random-bounty-alt-pts {
  color: #d68a34;
  font-weight: 700;
}
.streak-pill {
  display: flex;
  align-items: center;
  background: rgba(214, 138, 52, 0.14);
  border: 1px solid rgba(214, 138, 52, 0.35);
  color: #d68a34;
  border-radius: 999px;
  padding: 9px 14px;
  font-size: 12.5px;
  font-weight: 700;
  white-space: nowrap;
}
.random-bounty-label {
  color: #d68a34;
  font-weight: 700;
  font-size: 11px;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.random-bounty-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.random-bounty-title {
  color: #fff;
  font-weight: 600;
  font-size: 14px;
}
.random-bounty-sub {
  color: #999;
  font-size: 12px;
}
.random-bounty-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.filter-row {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.filter-row .field-input {
  width: auto;
  min-width: 120px;
}
.search-input {
  flex: 1;
  min-width: 160px;
}
.bounty-auto-pill {
  font-size: 10px;
  color: #d68a34;
  background: rgba(214, 138, 52, 0.14);
  padding: 2px 7px;
  border-radius: 999px;
  white-space: nowrap;
}
.journal-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}
.journal-entry {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 13px;
}
.journal-date {
  color: #666;
  font-size: 11px;
  white-space: nowrap;
}
.journal-text {
  flex: 1;
  color: #ccc;
}
.status-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 18px;
  border-bottom: 1px solid #2a2a2a;
}
.status-tab {
  background: none;
  border: none;
  color: #999;
  font-size: 13px;
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}
.status-tab:hover {
  color: #ccc;
}
.status-tab.active {
  color: #d68a34;
  border-bottom-color: #d68a34;
}
.empty-state {
  color: #777;
  font-size: 13px;
  padding: 16px;
  background: #161616;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
}
.bounty-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bounty-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 14px 16px;
}
.bounty-card.muted {
  opacity: 0.7;
}
.bounty-card-wrapper {
  display: flex;
  flex-direction: column;
}
.bounty-details {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: #161616;
  border: 1px solid #2a2a2a;
  border-top: none;
  border-radius: 0 0 10px 10px;
  padding: 14px 16px;
  margin-top: -1px;
}
.details-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.details-header h4 {
  color: #ccc;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin: 0;
}
.empty-state.small {
  padding: 8px;
  font-size: 12px;
}
.objective-list,
.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.objective-row,
.evidence-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #ccc;
}
.objective-status {
  width: 16px;
  text-align: center;
  color: #999;
}
.objective-status.done {
  color: #4caf50;
}
.objective-title {
  flex: 1;
}
.objective-title.done {
  color: #777;
  text-decoration: line-through;
}
.objective-progress {
  color: #999;
  font-size: 11px;
}
.evidence-kind {
  color: #999;
  font-size: 11px;
  white-space: nowrap;
}
.evidence-link {
  color: #d68a34;
  text-decoration: none;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.evidence-link:hover {
  text-decoration: underline;
}
.evidence-text {
  flex: 1;
  color: #ccc;
}
.inline-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding: 10px;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
}
.inline-form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
.mini-btn.primary {
  background: #d68a34;
  border-color: #d68a34;
  color: #111;
  font-weight: 700;
}
.mini-btn.primary:disabled {
  opacity: 0.6;
}
.mini-btn.danger:hover {
  border-color: #e05252;
  color: #e05252;
}
.form-error.small {
  font-size: 11px;
  margin: 0;
}
.bounty-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}
.bounty-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.bounty-game-link {
  color: #d68a34;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.bounty-game-link:hover {
  text-decoration: underline;
}
.bounty-type-pill {
  font-size: 10px;
  color: #999;
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 7px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.bounty-difficulty-pill {
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #999;
  background: rgba(255, 255, 255, 0.06);
}
.bounty-difficulty-pill.hard,
.bounty-difficulty-pill.extreme {
  color: #e05252;
  background: rgba(224, 82, 82, 0.12);
}
.bounty-title {
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
.bounty-description {
  color: #999;
  font-size: 13px;
  margin: 2px 0 0;
}
.bounty-target-note {
  color: #777;
  font-size: 12px;
  margin: 0;
}
.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
}
.progress-track {
  flex: 1;
  height: 6px;
  background: #111;
  border-radius: 999px;
  overflow: hidden;
  max-width: 220px;
}
.progress-fill {
  height: 100%;
  background: #d68a34;
  border-radius: 999px;
  transition: width 0.2s ease;
}
.progress-label {
  color: #999;
  font-size: 12px;
  white-space: nowrap;
}
.manual-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.progress-input {
  width: 70px;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #fff;
  padding: 4px 6px;
  font-size: 12px;
}
.mini-btn {
  background: #111;
  border: 1px solid #2a2a2a;
  color: #ccc;
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
}
.mini-btn:hover {
  border-color: #d68a34;
  color: #d68a34;
}
.bounty-footer-row {
  display: flex;
  gap: 12px;
  margin-top: 4px;
}
.bounty-points {
  color: #d68a34;
  font-size: 11px;
  font-weight: 700;
}
.bounty-deadline {
  color: #999;
  font-size: 11px;
}
.bounty-date {
  color: #666;
  font-size: 11px;
}
.bounty-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.action-btn {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid #2a2a2a;
  background: #111;
  color: #ccc;
  cursor: pointer;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.action-btn.complete:hover:not(:disabled),
.action-btn.resume:hover:not(:disabled) {
  border-color: #4caf50;
  color: #4caf50;
}
.action-btn.pause:hover:not(:disabled),
.action-btn.abandon:hover:not(:disabled),
.action-btn.delete:hover:not(:disabled) {
  border-color: #d68a34;
  color: #d68a34;
}
.action-btn.share:hover:not(:disabled) {
  border-color: #d68a34;
  color: #d68a34;
}
.confirm-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 20px;
  overflow-y: auto;
}
.confirm-dialog {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 20px;
  width: 100%;
  max-width: 420px;
  max-height: 90vh;
  overflow-y: auto;
}
.confirm-dialog h3 {
  color: #fff;
  margin: 0 0 14px;
  font-size: 16px;
}
.field-label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: #999;
  font-size: 12px;
  margin-bottom: 12px;
}
.field-input {
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #fff;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
}
.field-hint {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: #777;
  font-size: 11px;
  margin-top: 2px;
}
.points-suggestion {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid #2a2a2a;
  color: #ccc;
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 10.5px;
  cursor: pointer;
}
.points-suggestion:hover {
  border-color: #d68a34;
  color: #d68a34;
}
.form-error {
  color: #e05252;
  font-size: 12px;
  margin: 0 0 10px;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.cancel-btn {
  background: none;
  border: 1px solid #2a2a2a;
  color: #ccc;
  padding: 8px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.save-btn {
  background: #d68a34;
  border: none;
  color: #111;
  font-weight: 700;
  padding: 8px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.save-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
