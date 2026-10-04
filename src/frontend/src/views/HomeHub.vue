<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue";
import GameCard from "../components/GameCard.vue";
import GameFormModal from "../components/GameFormModal.vue";
import { fetchGames, deleteGame } from "../services/games";
import CollectionPickerModal from "../components/CollectionPickerModal.vue";
import RandomGamePicker from "../components/RandomGamePicker.vue";
import AccountChip from "../components/AccountChip.vue";
import { fetchBounties } from "../services/bounties";
import type { Bounty } from "../services/bounties";
import type { Game } from "../types/game";
import { currentUser } from "../state/auth";
import { fetchWeeklyDigest } from "../services/stats";
import type { WeeklyDigest } from "../services/stats";

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

// opens the filtered picker (#33) rather than jumping to any game at all,
// finished and wishlisted ones included
const showRandomPicker = ref(false);
function pickRandomGame() {
  if (!games.value.length) return;
  showRandomPicker.value = true;
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

onMounted(loadGames);

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
    weeklyDigest.value = null;
    weeklyBounties.value = [];
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
  <main class="home">
    <AccountChip fixed />

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
            <span v-if="bountiesCompletedThisWeek" class="weekly-recap-item"
              >{{ bountiesCompletedThisWeek }} bount{{
                bountiesCompletedThisWeek === 1 ? "y" : "ies"
              }}
              done</span
            >
            <span v-if="achievementsUnlockedThisWeek" class="weekly-recap-item"
              >{{ achievementsUnlockedThisWeek }} achievement{{
                achievementsUnlockedThisWeek === 1 ? "" : "s"
              }}
              unlocked</span
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

      <RandomGamePicker
        v-if="showRandomPicker"
        :games="games"
        @close="showRandomPicker = false"
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
</template>

<style scoped>
.home {
  position: relative;
  padding: 84px 24px 24px;
  font-family: system-ui, sans-serif;
  background: #0d0d0d;
  min-height: 100vh;
  color: #fff;
  overflow: hidden;
}
.home::before {
  content: "";
  position: fixed;
  top: -100px;
  left: -100px;
  width: 500px;
  height: 500px;
  background: radial-gradient(
    circle,
    rgba(214, 138, 52, 0.08) 0%,
    transparent 70%
  );
  z-index: 0;
  pointer-events: none;
}
.content {
  position: relative;
  z-index: 1;
}
.home-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 28px;
}
.home-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.weekly-recap {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid #232323;
  border-radius: 999px;
  padding: 8px 16px;
  font-size: 12.5px;
}
.weekly-recap-label {
  color: #777;
  text-transform: uppercase;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  font-weight: 700;
}
.weekly-recap-item {
  color: #d68a34;
  font-weight: 600;
}
.shelf-customizer-wrap {
  position: relative;
}
.customize-button {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid #2a2a2a;
  color: #ccc;
  border-radius: 8px;
  padding: 9px 14px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.customize-button:hover {
  border-color: #3a3a3a;
  color: #fff;
}
.shelf-customizer-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 220px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.shelf-choice {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #eee;
  font-size: 13px;
  padding: 5px 2px;
  cursor: pointer;
}
.shelf-choice input {
  accent-color: #d68a34;
}
.eyebrow {
  margin: 0 0 4px;
  color: #d68a34;
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.home-header h1 {
  margin: 0;
  font-size: 1.7rem;
  font-weight: 800;
  color: #fff;
}
.stats-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 24px;
}
.stat-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid #232323;
  border-radius: 10px;
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 80px;
  transition:
    transform 0.15s ease,
    border-color 0.15s ease;
}
.stat-card:hover {
  transform: translateY(-2px);
  border-color: #3a3a3a;
}
.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #d68a34;
}
.stat-label {
  font-size: 12px;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.widgets-row {
  display: flex;
  gap: 14px;
  margin-bottom: 32px;
}
.onboarding-checklist {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 20px;
  background: rgba(214, 138, 52, 0.06);
  border: 1px solid rgba(214, 138, 52, 0.25);
  border-radius: 12px;
  padding: 12px 18px;
  margin-bottom: 20px;
}
.onboarding-header {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #d68a34;
  font-size: 12.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  flex-basis: 100%;
}
.onboarding-dismiss {
  margin-left: auto;
  background: none;
  border: none;
  color: #a3703c;
  cursor: pointer;
  font-size: 12px;
  min-width: 28px;
  min-height: 28px;
  margin-top: -5px;
  margin-bottom: -5px;
  padding: 2px 4px;
}
.onboarding-dismiss:hover {
  color: #d68a34;
}
.onboarding-step {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: inherit;
  padding: 6px 0;
}
.onboarding-check {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid #555;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: #4ade80;
  flex-shrink: 0;
}
.onboarding-step.done .onboarding-check {
  border-color: #4ade80;
}
.onboarding-text {
  display: flex;
  flex-direction: column;
}
.onboarding-label {
  font-size: 13px;
  color: #eee;
}
.onboarding-step.done .onboarding-label {
  color: #888;
  text-decoration: line-through;
}
.onboarding-hint {
  font-size: 11px;
  color: #777;
}
.widget-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid #232323;
  border-radius: 12px;
  padding: 14px 18px;
  flex: 1;
  max-width: 280px;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    transform 0.15s ease;
}
.random-widget:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: #3a3a3a;
  transform: translateY(-2px);
}
.bounty-widget,
.goals-widget {
  max-width: 340px;
  text-decoration: none;
  color: inherit;
}
.bounty-widget:hover,
.goals-widget:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: #3a3a3a;
  transform: translateY(-2px);
}
.backlog-widget,
.on-this-day-widget {
  max-width: 340px;
  text-decoration: none;
  color: inherit;
}
.on-this-day-widget:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: #3a3a3a;
  transform: translateY(-2px);
}
.widget-icon {
  color: #d68a34;
  flex-shrink: 0;
}
.widget-title {
  display: block;
  color: #fff;
  font-weight: 600;
  font-size: 14px;
}
.widget-subtitle {
  display: block;
  color: #888;
  font-size: 12px;
  margin-top: 2px;
}
.row {
  margin-bottom: 32px;
}
.row-header {
  display: flex;
  align-items: center;
  margin-bottom: 14px;
}
.row-title {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-left: 12px;
  border-left: 3px solid #d68a34;
  text-decoration: none;
  cursor: pointer;
}
.row-title:hover h2 {
  color: #d68a34;
}
.row-title h2 {
  margin: 0;
  font-size: 1.1rem;
  color: #fff;
  transition: color 0.15s ease;
}
.row-icon {
  color: #d68a34;
  flex-shrink: 0;
}
.row-count {
  background: rgba(255, 255, 255, 0.06);
  color: #999;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}
.shelf-wrap {
  position: relative;
}
.shelf {
  display: flex;
  gap: 16px;
  overflow-x: auto;
  scroll-behavior: smooth;
  padding: 20px 16px 28px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.shelf::-webkit-scrollbar {
  display: none;
}
.shelf-arrow {
  position: absolute;
  top: 0;
  bottom: 28px;
  width: 40px;
  border: none;
  background: linear-gradient(to right, rgba(10, 10, 10, 0.85), transparent);
  color: #fff;
  font-size: 26px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s ease;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
}
.shelf-arrow.right {
  left: auto;
  right: 0;
  background: linear-gradient(to left, rgba(10, 10, 10, 0.85), transparent);
}
.shelf-arrow.left {
  left: 0;
}
.shelf-wrap:hover .shelf-arrow.can-scroll {
  opacity: 1;
  pointer-events: auto;
}
.shelf-arrow:hover {
  color: #d68a34;
}
.empty-row {
  color: #777;
  font-size: 14px;
  margin: 0;
}
.error {
  color: #f87171;
}
.tour-backdrop,
.confirm-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}
.tour-dialog {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 14px;
  padding: 28px;
  width: 100%;
  max-width: 460px;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
  box-sizing: border-box;
}
.tour-dialog h2 {
  margin: 0 0 4px;
  color: #fff;
  font-size: 1.3rem;
}
.tour-intro {
  color: #999;
  font-size: 13px;
  margin: 0 0 20px;
}
.tour-steps {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 22px;
}
.tour-step h3 {
  margin: 0 0 3px;
  color: #d68a34;
  font-size: 13.5px;
}
.tour-step p {
  margin: 0;
  color: #ccc;
  font-size: 13px;
  line-height: 1.5;
}
.tour-dismiss {
  width: 100%;
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 8px;
  padding: 12px;
  font-weight: 700;
  cursor: pointer;
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
.secondary-button,
.danger-button {
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-weight: 600;
  cursor: pointer;
}
.secondary-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.danger-button {
  background: #dc2626;
  color: #fff;
}
.danger-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.bounty-widget {
  max-width: 340px;
  text-decoration: none;
  color: inherit;
}
.bounty-widget:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: #3a3a3a;
  transform: translateY(-2px);
}
.bounty-body {
  flex: 1;
  min-width: 0;
}
.bounty-body .widget-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
