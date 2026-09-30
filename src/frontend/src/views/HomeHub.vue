<script setup lang="ts">
import PluginExtensionSlot from "../components/plugins/PluginExtensionSlot.vue";
import { pluginSlots } from "../state/pluginExtensions";
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue";
import { useRouter } from "vue-router";
import GameCard from "../components/GameCard.vue";
import GameFormModal from "../components/GameFormModal.vue";
import { fetchGames, deleteGame } from "../services/games";
import CollectionPickerModal from "../components/CollectionPickerModal.vue";
import type { Game } from "../types/game";
import { currentUser } from "../state/auth";
import { fetchBounties } from "../services/bounties";
import type { Bounty } from "../services/bounties";
import { fetchWeeklyDigest } from "../services/stats";
import type { WeeklyDigest } from "../services/stats";

const router = useRouter();
const hasHomeOverride = computed(() => pluginSlots.value.some((item) => item.slot === "home.replace"));

const games = ref<Game[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const showFormModal = ref(false);
const editingGame = ref<Game | null>(null);

const deletingGame = ref<Game | null>(null);
const deleting = ref(false);
const deleteError = ref<string | null>(null);

const totalGames = computed(() => games.value.length);
const favoriteCount = computed(
  () => games.value.filter((g) => g.favorite).length,
);

const bgLayers = ref<{ url: string | null; visible: boolean }[]>([
  { url: null, visible: false },
  { url: null, visible: false },
]);
const activeLayer = ref(0);

// only crossfade once the cursor has settled on a card briefly, gliding
// across many cards shouldn't flicker the ambient background
let hoverDebounceTimer: ReturnType<typeof setTimeout> | null = null;

function setHoverImage(url: string | null) {
  if (hoverDebounceTimer) clearTimeout(hoverDebounceTimer);
  hoverDebounceTimer = setTimeout(() => {
    if (url === null) {
      bgLayers.value[activeLayer.value].visible = false;
      return;
    }
    const nextLayer = activeLayer.value === 0 ? 1 : 0;
    bgLayers.value[nextLayer] = { url, visible: true };
    bgLayers.value[activeLayer.value].visible = false;
    activeLayer.value = nextLayer;
  }, 400);
}

function pickRandomGame() {
  if (!games.value.length) return;
  const random = games.value[Math.floor(Math.random() * games.value.length)];
  router.push(`/games/${random.id}`);
}

// same overlapping-call guard as GameLibrary.vue's loadGames, this is
// re-triggered from many places (save, delete, collection changes) that
// can overlap, and a slower earlier call could otherwise overwrite a newer one
let loadGamesToken = 0;

async function loadGames() {
  const token = ++loadGamesToken;
  loading.value = true;
  try {
    const fetched = await fetchGames();
    if (token !== loadGamesToken) return;
    games.value = fetched;
  } catch (err) {
    if (token !== loadGamesToken) return;
    error.value = err instanceof Error ? err.message : "Failed to load games";
  } finally {
    if (token === loadGamesToken) {
      loading.value = false;
      await nextTick();
      updateAllShelfArrows();
    }
  }
}

// toggles each arrow's visibility based on whether its shelf can actually
// scroll further that direction, no point showing a left arrow at scrollLeft 0
function updateShelfArrows(shelf: HTMLElement) {
  const wrap = shelf.closest(".shelf-wrap");
  if (!wrap) return;
  const left = wrap.querySelector(".shelf-arrow.left");
  const right = wrap.querySelector(".shelf-arrow.right");
  const maxScroll = shelf.scrollWidth - shelf.clientWidth;
  left?.classList.toggle("can-scroll", shelf.scrollLeft > 4);
  right?.classList.toggle("can-scroll", shelf.scrollLeft < maxScroll - 4);
}

function updateAllShelfArrows() {
  document.querySelectorAll<HTMLElement>(".shelf").forEach(updateShelfArrows);
}

window.addEventListener("resize", updateAllShelfArrows);
onUnmounted(() => window.removeEventListener("resize", updateAllShelfArrows));

onMounted(loadGames);

// --- Bounties: self-set goals inside a game, full list lives at /bounties
const activeBounties = ref<Bounty[]>([]);
const bountiesLoading = ref(true);

async function loadBounties() {
  bountiesLoading.value = true;
  try {
    activeBounties.value = await fetchBounties({ status: "active" });
  } catch {
    // no points, no stakes, a failed fetch just means the widget shows
    // nothing today, not worth surfacing an error for
    activeBounties.value = [];
  } finally {
    bountiesLoading.value = false;
  }
}
onMounted(loadBounties);

function openEditModal(game: Game) {
  editingGame.value = game;
  showFormModal.value = true;
}

async function onGameSaved() {
  showFormModal.value = false;
  editingGame.value = null;
  await loadGames();
}

function requestDelete(game: Game) {
  deletingGame.value = game;
  deleteError.value = null;
}

function onDeleteFromModal(gameId: string) {
  const game = games.value.find((g) => g.id === gameId);
  showFormModal.value = false;
  editingGame.value = null;
  if (game) requestDelete(game);
}

async function confirmDelete() {
  if (!deletingGame.value) return;
  deleting.value = true;
  deleteError.value = null;
  try {
    await deleteGame(deletingGame.value.id);
    deletingGame.value = null;
    await loadGames();
  } catch (err) {
    deleteError.value =
      err instanceof Error ? err.message : "Failed to delete game";
  } finally {
    deleting.value = false;
  }
}

const collectionPickerGame = ref<Game | null>(null);

function handleAddToCollection(game: Game) {
  collectionPickerGame.value = game;
}

async function onCollectionAdded() {
  await loadGames();
}

const SHELF_CAP = 20;

// most-recently-played first, this is the shelf you land on, so it should
// lead with whatever you were actually just doing, not insertion order
const playingGames = computed(() =>
  [...games.value]
    .filter((g) => g.status === "playing")
    .sort((a, b) => (b.lastPlayedAt ?? "").localeCompare(a.lastPlayedAt ?? ""))
    .slice(0, SHELF_CAP),
);

const recentlyAdded = computed(() =>
  [...games.value]
    .filter((g) => g.dateAdded)
    .sort((a, b) => (b.dateAdded! > a.dateAdded! ? 1 : -1))
    .slice(0, SHELF_CAP),
);

const collectionGroups = computed(() => {
  const map = new Map<string, Game[]>();
  for (const g of games.value) {
    for (const c of g.collections) {
      if (!map.has(c)) map.set(c, []);
      map.get(c)!.push(g);
    }
  }
  return Array.from(map.entries()).map(([name, list]) => ({
    name,
    games: list.slice(0, SHELF_CAP),
  }));
});

const collectionsCount = computed(() => collectionGroups.value.length);

// which shelves show, and in what order, persisted per browser. Reordering
// isn't exposed (drag-and-drop has no precedent in this codebase, and
// re-doing it as up/down arrows for a handful of shelves felt like more
// chrome than it was worth); show/hide covers the actual complaint, which
// is a Home Hub cluttered with collection shelves nobody wants to see here
const HIDDEN_SHELVES_KEY = "homeHubHiddenShelves";
function loadHiddenShelves(): Set<string> {
  try {
    const raw = localStorage.getItem(HIDDEN_SHELVES_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}
const hiddenShelves = ref<Set<string>>(loadHiddenShelves());
function toggleShelfVisibility(id: string) {
  const next = new Set(hiddenShelves.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  hiddenShelves.value = next;
  try {
    localStorage.setItem(HIDDEN_SHELVES_KEY, JSON.stringify([...next]));
  } catch {
    // worst case the customization just doesn't persist, not worth failing over
  }
}
const showShelfCustomizer = ref(false);
const shelfChoices = computed(() => [
  { id: "continue-playing", label: "Continue Playing" },
  { id: "recently-added", label: "Recently Added" },
  ...collectionGroups.value.map((g) => ({
    id: "collection:" + g.name,
    label: g.name,
  })),
]);

// a small, dismissible nudge toward a few features that are easy to miss
// entirely on a fresh install, gone for good once dismissed, not
// re-shown just because every item happens to get checked off later
const CHECKLIST_DISMISSED_KEY = "homeHubChecklistDismissed";
const checklistDismissed = ref(
  localStorage.getItem(CHECKLIST_DISMISSED_KEY) === "true",
);
function dismissChecklist() {
  checklistDismissed.value = true;
  try {
    localStorage.setItem(CHECKLIST_DISMISSED_KEY, "true");
  } catch {
    // worst case it just shows again next visit, not worth failing over
  }
}
const onboardingSteps = computed(() => [
  {
    done: games.value.some((g) => g.source),
    label: "Connect a library",
    hint: "Steam, GOG, or PlayStation, Settings → Metadata/API",
    to: "/settings",
  },
  {
    done: games.value.some((g) => g.favorite),
    label: "Favorite a game",
    hint: "The heart icon on any card",
    to: "/games",
  },
  {
    done: activeBounties.value.length > 0,
    label: "Set a goal",
    hint: "A lightweight bounty for something you want to finish",
    to: "/bounties",
  },
]);
const showChecklist = computed(
  () => !checklistDismissed.value && onboardingSteps.value.some((s) => !s.done),
);

// one-time welcome tour, a plain feature summary rather than positioned
// coach-marks pointing at live elements (this app has no such overlay
// system, and building one just for a first-run pass felt disproportionate)
const WELCOME_TOUR_KEY = "seenWelcomeTour";
const showWelcomeTour = ref(localStorage.getItem(WELCOME_TOUR_KEY) !== "true");
function dismissWelcomeTour() {
  showWelcomeTour.value = false;
  try {
    localStorage.setItem(WELCOME_TOUR_KEY, "true");
  } catch {
    // worst case it shows again next visit, not worth failing over
  }
}
const TOUR_STEPS = [
  {
    title: "Find anything fast",
    body: "Press Ctrl/Cmd+K anywhere to jump straight to a game, collection, bounty, or Settings section.",
  },
  {
    title: "Filter and save combos",
    body: "Games has status, platform, genre, and advanced filters, save a combination as a preset to reuse it later.",
  },
  {
    title: "Collections",
    body: "Group games however you like, in any order, open a collection and hit Reorder to arrange it.",
  },
  {
    title: "Bounties",
    body: "Optional personal goals with points if you want the extra structure, set one, or let the random picker suggest something.",
  },
  {
    title: "Press ? anytime",
    body: "Shows every keyboard shortcut this app supports.",
  },
];

// --- "this week" recap: playtime data has no history (just a running
// total + lastPlayedAt), so "minutes logged this week" isn't derivable,
// this counts what actually is: games touched, bounties finished,
// achievements unlocked, and metadata edited/refreshed ------
const weeklyBounties = ref<Bounty[]>([]);
const weeklyDigestSetting = ref(
  localStorage.getItem("weeklyDigestEnabled") !== "false",
);
const weeklyDigest = ref<WeeklyDigest | null>(null);
onMounted(async () => {
  if (!weeklyDigestSetting.value) return;
  try {
    const [bounties, digest] = await Promise.all([
      fetchBounties({ status: "completed" }),
      fetchWeeklyDigest(),
    ]);
    weeklyBounties.value = bounties;
    weeklyDigest.value = digest;
  } catch {
    weeklyBounties.value = [];
    weeklyDigest.value = null;
  }
});
const gamesPlayedThisWeek = computed(() => {
  const weekAgo = Date.now() - 7 * 86_400_000;
  return games.value.filter(
    (g) => g.lastPlayedAt && new Date(g.lastPlayedAt).getTime() >= weekAgo,
  ).length;
});
const bountiesCompletedThisWeek = computed(() => {
  const weekAgo = Date.now() / 1000 - 7 * 86_400;
  return weeklyBounties.value.filter(
    (b) => b.completed_at !== null && b.completed_at >= weekAgo,
  ).length;
});
const achievementsUnlockedThisWeek = computed(
  () => weeklyDigest.value?.achievements_unlocked ?? 0,
);
const metadataChangesThisWeek = computed(
  () => weeklyDigest.value?.metadata_changes ?? 0,
);
const showWeeklyRecap = computed(
  () =>
    weeklyDigestSetting.value &&
    (gamesPlayedThisWeek.value > 0 ||
      bountiesCompletedThisWeek.value > 0 ||
      achievementsUnlockedThisWeek.value > 0 ||
      metadataChangesThisWeek.value > 0),
);

// backlog games sitting untouched a while, added 90+ days ago, never
// played, still marked backlog. No dedicated "revisit date" field exists,
// so this is a heuristic rather than something the user explicitly set.
const staleBacklogGames = computed(() => {
  const cutoff = Date.now() - 90 * 86_400_000;
  return games.value.filter(
    (g) =>
      g.status === "backlog" &&
      !g.lastPlayedAt &&
      g.dateAdded &&
      new Date(g.dateAdded).getTime() < cutoff,
  );
});

// "on this day", games added in a previous year, on today's month/day.
// Uses dateAdded (the one date every game reliably has) rather than
// lastPlayedAt, which is often null.
const onThisDayGames = computed(() => {
  const now = new Date();
  return games.value
    .filter((g) => {
      if (!g.dateAdded) return false;
      const d = new Date(g.dateAdded);
      return (
        d.getMonth() === now.getMonth() &&
        d.getDate() === now.getDate() &&
        d.getFullYear() < now.getFullYear()
      );
    })
    .map((g) => ({
      game: g,
      yearsAgo: now.getFullYear() - new Date(g.dateAdded!).getFullYear(),
    }));
});

function scrollShelf(e: MouseEvent, dir: 1 | -1) {
  const row = (e.currentTarget as HTMLElement).closest(".row");
  const shelf = row?.querySelector(".shelf") as HTMLElement | null;
  if (!shelf) return;
  shelf.scrollBy({ left: dir * shelf.clientWidth * 0.9, behavior: "smooth" });
}
</script>

<template>
  <PluginExtensionSlot v-if="hasHomeOverride" slot-id="home.replace" :context="{ host_page: 'home' }" />
    <main v-else class="home">
    <div
      v-for="(layer, i) in bgLayers"
      :key="i"
      class="ambient-bg"
      :class="{ visible: layer.visible }"
      :style="layer.url ? { backgroundImage: `url(${layer.url})` } : {}"
    ></div>

    <div v-if="currentUser" class="profile-chip">
      <span class="profile-name">{{ currentUser.username }}</span>
      <div class="profile-avatar">
        {{ currentUser.username.slice(0, 2).toUpperCase() }}
      </div>
    </div>

    <div
      v-if="showWelcomeTour"
      class="tour-backdrop"
      @click.self="dismissWelcomeTour"
    >
      <div class="tour-dialog">
        <h2>Welcome to your library</h2>
        <p class="tour-intro">
          A quick tour of what's here, this won't show again.
        </p>
        <div class="tour-steps">
          <div v-for="step in TOUR_STEPS" :key="step.title" class="tour-step">
            <h3>{{ step.title }}</h3>
            <p>{{ step.body }}</p>
          </div>
        </div>
        <button type="button" class="tour-dismiss" @click="dismissWelcomeTour">
          Let's go
        </button>
      </div>
    </div>

    <div class="content">
      <div class="home-header">
        <div>
          <p class="eyebrow">Welcome back, {{ currentUser?.username }}</p>
          <h1>Your Library</h1>
        </div>
        <div class="home-header-actions">
          <div v-if="showWeeklyRecap" class="weekly-recap">
            <span class="weekly-recap-label">This week</span>
            <span v-if="gamesPlayedThisWeek" class="weekly-recap-item"
              >{{ gamesPlayedThisWeek }} game{{
                gamesPlayedThisWeek === 1 ? "" : "s"
              }}
              played</span
            >
            <span v-if="achievementsUnlockedThisWeek" class="weekly-recap-item"
              >{{ achievementsUnlockedThisWeek }} achievement{{
                achievementsUnlockedThisWeek === 1 ? "" : "s"
              }}
              unlocked</span
            >
            <span v-if="bountiesCompletedThisWeek" class="weekly-recap-item"
              >{{ bountiesCompletedThisWeek }} bount{{
                bountiesCompletedThisWeek === 1 ? "y" : "ies"
              }}
              done</span
            >
            <span v-if="metadataChangesThisWeek" class="weekly-recap-item"
              >{{ metadataChangesThisWeek }} metadata change{{
                metadataChangesThisWeek === 1 ? "" : "s"
              }}</span
            >
          </div>
          <div class="shelf-customizer-wrap">
            <button
              type="button"
              class="customize-button"
              @click="showShelfCustomizer = !showShelfCustomizer"
            >
              Customize shelves
            </button>
            <div v-if="showShelfCustomizer" class="shelf-customizer-dropdown">
              <label
                v-for="choice in shelfChoices"
                :key="choice.id"
                class="shelf-choice"
              >
                <input
                  type="checkbox"
                  :checked="!hiddenShelves.has(choice.id)"
                  @change="toggleShelfVisibility(choice.id)"
                />
                <span>{{ choice.label }}</span>
              </label>
            </div>
          </div>
        </div>
      </div>

      <div class="stats-strip">
        <div class="stat-card">
          <span class="stat-value">{{ totalGames }}</span>
          <span class="stat-label">Games</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{{ favoriteCount }}</span>
          <span class="stat-label">Favorites</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{{ collectionsCount }}</span>
          <span class="stat-label">Collections</span>
        </div>
      </div>

      <div v-if="showChecklist" class="onboarding-checklist">
        <div class="onboarding-header">
          <span>Get the most out of your library</span>
          <button
            type="button"
            class="onboarding-dismiss"
            title="Dismiss"
            @click="dismissChecklist"
          >
            ✕
          </button>
        </div>
        <router-link
          v-for="step in onboardingSteps"
          :key="step.label"
          :to="step.to"
          class="onboarding-step"
          :class="{ done: step.done }"
        >
          <span class="onboarding-check">{{ step.done ? "✓" : "" }}</span>
          <span class="onboarding-text">
            <span class="onboarding-label">{{ step.label }}</span>
            <span class="onboarding-hint">{{ step.hint }}</span>
          </span>
        </router-link>
      </div>

      <section class="widgets-row">
        <button
          type="button"
          class="widget-card random-widget"
          @click="pickRandomGame"
        >
          <svg
            class="widget-icon"
            viewBox="0 0 24 24"
            width="22"
            height="22"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="3" y="3" width="18" height="18" rx="4" />
            <circle
              cx="8.5"
              cy="8.5"
              r="1.2"
              fill="currentColor"
              stroke="none"
            />
            <circle
              cx="15.5"
              cy="8.5"
              r="1.2"
              fill="currentColor"
              stroke="none"
            />
            <circle
              cx="8.5"
              cy="15.5"
              r="1.2"
              fill="currentColor"
              stroke="none"
            />
            <circle
              cx="15.5"
              cy="15.5"
              r="1.2"
              fill="currentColor"
              stroke="none"
            />
            <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
          </svg>
          <div>
            <span class="widget-title">Pick something random</span>
            <span class="widget-subtitle">Can't decide? Let us choose.</span>
          </div>
        </button>

        <router-link
          v-if="activeBounties.length"
          to="/bounties"
          class="widget-card bounty-widget"
        >
          <svg
            class="widget-icon"
            viewBox="0 0 24 24"
            width="22"
            height="22"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="5" />
            <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
          </svg>
          <div class="bounty-body">
            <span class="widget-title"
              >{{ activeBounties.length }} active
              {{ activeBounties.length === 1 ? "bounty" : "bounties" }}</span
            >
            <span
              class="widget-subtitle"
              v-for="b in activeBounties.slice(0, 2)"
              :key="b.id"
            >
              {{ b.title }}{{ b.game_title ? `, ${b.game_title}` : "" }}
            </span>
          </div>
        </router-link>
        <router-link
          v-else-if="!bountiesLoading"
          to="/bounties"
          class="widget-card goals-widget"
        >
          <svg
            class="widget-icon"
            viewBox="0 0 24 24"
            width="22"
            height="22"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="5" />
            <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
          </svg>
          <div>
            <span class="widget-title">Goals & bounties</span>
            <span class="widget-subtitle"
              >Set a goal for one of your games</span
            >
          </div>
        </router-link>

        <router-link
          v-if="staleBacklogGames.length"
          to="/games?status=backlog"
          class="widget-card backlog-widget"
        >
          <svg
            class="widget-icon"
            viewBox="0 0 24 24"
            width="22"
            height="22"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="4" y="4" width="16" height="16" rx="2" />
            <path d="M8 2v4M16 2v4" />
          </svg>
          <div>
            <span class="widget-title"
              >{{ staleBacklogGames.length }} backlog
              {{ staleBacklogGames.length === 1 ? "game" : "games" }} waiting a
              while</span
            >
            <span class="widget-subtitle"
              >Added 90+ days ago, never played, {{ staleBacklogGames[0].title
              }}{{
                staleBacklogGames.length > 1
                  ? ` +${staleBacklogGames.length - 1} more`
                  : ""
              }}</span
            >
          </div>
        </router-link>

        <router-link
          v-if="onThisDayGames.length"
          :to="`/games/${onThisDayGames[0].game.id}`"
          class="widget-card on-this-day-widget"
        >
          <svg
            class="widget-icon"
            viewBox="0 0 24 24"
            width="22"
            height="22"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="3" y="4" width="18" height="17" rx="2" />
            <line x1="3" y1="9" x2="21" y2="9" />
            <line x1="8" y1="2" x2="8" y2="6" />
            <line x1="16" y1="2" x2="16" y2="6" />
          </svg>
          <div>
            <span class="widget-title">On this day</span>
            <span
              class="widget-subtitle"
              v-for="entry in onThisDayGames.slice(0, 2)"
              :key="entry.game.id"
            >
              Added {{ entry.game.title }} {{ entry.yearsAgo }} year{{
                entry.yearsAgo === 1 ? "" : "s"
              }}
              ago
            </span>
          </div>
        </router-link>
      </section>

      <PluginExtensionSlot
        slot-id="home.after-widgets"
        :context="{ host_page: 'home' }"
      />

      <p v-if="loading">Loading…</p>
      <p v-else-if="error" class="error">{{ error }}</p>

      <template v-else>
        <section v-if="!hiddenShelves.has('continue-playing')" class="row">
          <div class="row-header">
            <router-link to="/games?status=playing" class="row-title">
              <svg
                class="row-icon"
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <rect x="2" y="6" width="20" height="12" rx="6" />
                <line x1="7" y1="12" x2="11" y2="12" />
                <line x1="9" y1="10" x2="9" y2="14" />
                <circle
                  cx="16"
                  cy="10.5"
                  r="1"
                  fill="currentColor"
                  stroke="none"
                />
                <circle
                  cx="18"
                  cy="13"
                  r="1"
                  fill="currentColor"
                  stroke="none"
                />
              </svg>
              <h2>Continue Playing</h2>
              <span class="row-count">{{ playingGames.length }}</span>
            </router-link>
          </div>
          <div v-if="playingGames.length" class="shelf-wrap">
            <button
              type="button"
              class="shelf-arrow left"
              @click="scrollShelf($event, -1)"
              aria-label="Scroll left"
            >
              ‹
            </button>
            <div
              class="shelf"
              @scroll="updateShelfArrows($event.target as HTMLElement)"
            >
              <GameCard
                v-for="game in playingGames"
                :key="game.id"
                :game="game"
                @hover="setHoverImage"
                @edit="openEditModal"
                @add-to-collection="handleAddToCollection"
              />
            </div>
            <button
              type="button"
              class="shelf-arrow right"
              @click="scrollShelf($event, 1)"
              aria-label="Scroll right"
            >
              ›
            </button>
          </div>
          <p v-else class="empty-row">Nothing in progress right now.</p>
        </section>

        <section v-if="!hiddenShelves.has('recently-added')" class="row">
          <div class="row-header">
            <router-link to="/games?sort=recent" class="row-title">
              <svg
                class="row-icon"
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <circle cx="12" cy="12" r="9" />
                <polyline points="12 7 12 12 15.5 14" />
              </svg>
              <h2>Recently Added</h2>
              <span class="row-count">{{ recentlyAdded.length }}</span>
            </router-link>
          </div>
          <div v-if="recentlyAdded.length" class="shelf-wrap">
            <button
              type="button"
              class="shelf-arrow left"
              @click="scrollShelf($event, -1)"
              aria-label="Scroll left"
            >
              ‹
            </button>
            <div
              class="shelf"
              @scroll="updateShelfArrows($event.target as HTMLElement)"
            >
              <GameCard
                v-for="game in recentlyAdded"
                :key="game.id"
                :game="game"
                @hover="setHoverImage"
                @edit="openEditModal"
                @add-to-collection="handleAddToCollection"
              />
            </div>
            <button
              type="button"
              class="shelf-arrow right"
              @click="scrollShelf($event, 1)"
              aria-label="Scroll right"
            >
              ›
            </button>
          </div>
          <p v-else class="empty-row">No games added yet.</p>
        </section>

        <section
          v-for="group in collectionGroups.filter(
            (g) => !hiddenShelves.has('collection:' + g.name),
          )"
          :key="group.name"
          class="row"
        >
          <div class="row-header">
            <router-link
              :to="`/collections/${encodeURIComponent(group.name)}`"
              class="row-title"
            >
              <svg
                class="row-icon"
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path
                  d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
                />
              </svg>
              <h2>{{ group.name }}</h2>
              <span class="row-count">{{ group.games.length }}</span>
            </router-link>
          </div>
          <div class="shelf-wrap">
            <button
              type="button"
              class="shelf-arrow left"
              @click="scrollShelf($event, -1)"
              aria-label="Scroll left"
            >
              ‹
            </button>
            <div
              class="shelf"
              @scroll="updateShelfArrows($event.target as HTMLElement)"
            >
              <GameCard
                v-for="game in group.games"
                :key="game.id"
                :game="game"
                @hover="setHoverImage"
                @edit="openEditModal"
                @add-to-collection="handleAddToCollection"
              />
            </div>
            <button
              type="button"
              class="shelf-arrow right"
              @click="scrollShelf($event, 1)"
              aria-label="Scroll right"
            >
              ›
            </button>
          </div>
        </section>
        <p v-if="!collectionGroups.length" class="empty-row">
          No collections yet: use a card's collection button to start one.
        </p>
      </template>

      <GameFormModal
        v-if="showFormModal"
        :game="editingGame"
        @close="showFormModal = false"
        @saved="onGameSaved"
        @delete="onDeleteFromModal"
      />

      <CollectionPickerModal
        v-if="collectionPickerGame"
        :game="collectionPickerGame"
        @close="collectionPickerGame = null"
        @added="onCollectionAdded"
      />

      <div
        v-if="deletingGame"
        class="confirm-backdrop"
        @click.self="deletingGame = null"
      >
        <div class="confirm-dialog">
          <h3>Delete {{ deletingGame.title }}?</h3>
          <p>This can't be undone.</p>
          <div v-if="deleteError" class="confirm-error">{{ deleteError }}</div>
          <div class="confirm-actions">
            <button
              type="button"
              class="secondary-button"
              @click="deletingGame = null"
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
    </div>
  </main>
