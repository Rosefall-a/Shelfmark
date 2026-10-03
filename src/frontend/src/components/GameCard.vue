<script setup lang="ts">
import { useRouter } from "vue-router";
import type { Game, GameStatus } from "../types/game";
import { setFavorite, setStatus } from "../services/games";
import { ref, computed, nextTick, onUnmounted } from "vue";
import { computeScore } from "../utils/scoring";
import { appearanceSettings } from "../state/appearance";

const props = defineProps<{
  game: Game;
  selectMode?: boolean;
  selected?: boolean;
  keyboardFocused?: boolean;
}>();

const emit = defineEmits<{
  edit: [game: Game];
  "add-to-collection": [game: Game];
  "toggle-select": [game: Game, shiftKey: boolean];
}>();

const router = useRouter();

const score = computed(() => computeScore(props.game));

// completion-badge appearance, customized in Settings > Appearance,
// shared across every card via state/appearance.ts rather than fetched
// per-card
const localStatus = ref(props.game.status);
const isMastered = computed(() => localStatus.value === "mastered");
const badgeStyle = computed(
  () => appearanceSettings.value?.completion_badge_style ?? "none",
);
const badgeColor = computed(
  () => appearanceSettings.value?.completion_badge_color ?? "#e5e4e2",
);
const badgePlacement = computed(
  () => appearanceSettings.value?.completion_badge_placement ?? "top-right",
);
const badgeImageUrl = computed(
  () => appearanceSettings.value?.completion_badge_image_url ?? null,
);
const showBadge = computed(
  () => isMastered.value && badgeStyle.value !== "none",
);
const badgeCardStyle = computed(() => {
  if (
    !showBadge.value ||
    (badgeStyle.value !== "glow" && badgeStyle.value !== "border")
  )
    return {};
  return { "--badge-color": badgeColor.value };
});

const menuOpen = ref(false);
const statusSubmenuOpen = ref(false);
const localFavorite = ref(props.game.favorite);
const favoriteSaving = ref(false);

const menuTriggerRef = ref<HTMLElement | null>(null);
const menuPosition = ref({ top: 0, left: 0 });

function onWindowScroll() {
  closeMenu();
}

async function toggleMenu() {
  menuOpen.value = !menuOpen.value;
  if (menuOpen.value && menuTriggerRef.value) {
    await nextTick();
    const rect = menuTriggerRef.value.getBoundingClientRect();
    menuPosition.value = { top: rect.bottom + 6, left: rect.right - 190 };
    window.addEventListener("scroll", onWindowScroll, true);
  } else {
    window.removeEventListener("scroll", onWindowScroll, true);
  }
}

function closeMenu() {
  menuOpen.value = false;
  statusSubmenuOpen.value = false;
  window.removeEventListener("scroll", onWindowScroll, true);
}

// the grid this card lives in is virtualized, a card can be destroyed
// while its menu is still open, which would otherwise leak this listener
// on window forever (one per off-screen unmount)
onUnmounted(() => {
  window.removeEventListener("scroll", onWindowScroll, true);
});

const statuses: GameStatus[] = [
  "playing",
  "beaten",
  "mastered",
  "played",
  "on hold",
  "dropped",
  "backlog",
  "wishlist",
];

function openGame(e?: MouseEvent) {
  if (props.selectMode) {
    emit("toggle-select", props.game, e?.shiftKey ?? false);
    return;
  }
  router.push(`/games/${props.game.id}`);
}

async function toggleFavorite() {
  const next = !localFavorite.value;
  localFavorite.value = next;
  favoriteSaving.value = true;
  try {
    await setFavorite(props.game.id, next);
  } catch {
    localFavorite.value = !next;
  } finally {
    favoriteSaving.value = false;
  }
}

async function chooseStatus(status: GameStatus) {
  try {
    await setStatus(props.game.id, status);
    localStatus.value = status;
  } catch {
    // silently ignore, card just keeps showing the old status
  }
  closeMenu();
}

// a quick at-a-glance read on a card without opening it: never launched at
// all, vs. picked up again recently, anything in between just stays quiet
const totalPlaytimeMinutes = computed(() =>
  props.game.platforms.reduce((sum, p) => sum + p.playtimeMinutes, 0),
);
const activityDot = computed<"never" | "recent" | null>(() => {
  if (totalPlaytimeMinutes.value === 0) return "never";
  if (props.game.lastPlayedAt) {
    const daysSince =
      (Date.now() - new Date(props.game.lastPlayedAt).getTime()) / 86_400_000;
    if (daysSince <= 14) return "recent";
  }
  return null;
});

// short plain-text synopsis for the hover preview, game.description can be
// rich HTML (Steam's "About This Game"), so strip tags rather than render
// markup inside a small overlay
const previewSynopsis = computed(() => {
  const raw =
    props.game.description
      ?.replace(/<[^>]*>/g, " ")
      .replace(/\s+/g, " ")
      .trim() ?? "";
  if (!raw) return "";
  return raw.length > 140 ? raw.slice(0, 140).trimEnd() + "…" : raw;
});
const lastPlayedLabel = computed(() => {
  if (!props.game.lastPlayedAt) return "Not played yet";
  return `Last played ${new Date(props.game.lastPlayedAt).toLocaleDateString()}`;
});
function formatPlaytime(minutes: number): string {
  if (minutes === 0) return "No playtime logged";
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return hours > 0
    ? `${hours}h${mins > 0 ? ` ${mins}m` : ""} played`
    : `${mins}m played`;
}

// swipe gestures, a touch-only mirror of the desktop hover actions, which
// obviously never appear on a device with no cursor to hover with
const touchStartX = ref(0);
const touchStartY = ref(0);
const swiping = ref(false);
const SWIPE_THRESHOLD = 60;
function onTouchStart(e: TouchEvent) {
  if (props.selectMode) return;
  touchStartX.value = e.touches[0].clientX;
  touchStartY.value = e.touches[0].clientY;
  swiping.value = false;
}
function onTouchMove(e: TouchEvent) {
  if (props.selectMode) return;
  const dx = e.touches[0].clientX - touchStartX.value;
  const dy = e.touches[0].clientY - touchStartY.value;
  // only claim the gesture once it's clearly more horizontal than
  // vertical, otherwise a normal vertical scroll gets hijacked
  if (
    !swiping.value &&
    Math.abs(dx) > 16 &&
    Math.abs(dx) > Math.abs(dy) * 1.5
  ) {
    swiping.value = true;
  }
  if (swiping.value) e.preventDefault();
}
function onTouchEnd(e: TouchEvent) {
  if (!swiping.value) return;
  swiping.value = false;
  const dx = e.changedTouches[0].clientX - touchStartX.value;
  if (Math.abs(dx) < SWIPE_THRESHOLD) return;
  if (dx > 0) {
    void toggleFavorite();
  } else if (menuTriggerRef.value) {
    toggleMenu();
  }
}

function copyFolderPath() {
  if (props.game.folderLocation) {
    navigator.clipboard.writeText(props.game.folderLocation);
  }
  closeMenu();
}
</script>

<template>
  <div class="game-card-wrap">
    <div
      class="game-card"
      :class="{
        'menu-open': menuOpen,
        'select-mode': selectMode,
        [`badge-${badgeStyle}`]: showBadge,
        'keyboard-focused': keyboardFocused,
      }"
      :style="badgeCardStyle"
    >
      <div
        class="cover"
        @click="openGame($event)"
        @touchstart="onTouchStart"
        @touchmove="onTouchMove"
        @touchend="onTouchEnd"
      >
        <img class="cover-image" :src="game.coverImageUrl" alt="" />
        <div
          v-if="selectMode"
          class="select-checkbox"
          :class="{ checked: selected }"
        >
          <svg
            v-if="selected"
            viewBox="0 0 24 24"
            width="14"
            height="14"
            fill="none"
            stroke="currentColor"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </div>

        <div
          v-if="game.staleSince && !selectMode"
          class="stale-indicator"
          :title="`No longer seen in your ${game.source ?? 'account'} library as of the last sync.`"
        >
          <svg
            viewBox="0 0 24 24"
            width="12"
            height="12"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path
              d="M12 9v4M12 17h.01M10.3 3.9L2.5 17a1.6 1.6 0 0 0 1.4 2.4h16.2a1.6 1.6 0 0 0 1.4-2.4L13.7 3.9a1.6 1.6 0 0 0-2.8 0z"
            />
          </svg>
        </div>

        <div
          v-if="
            showBadge &&
            (badgeStyle === 'ribbon' || badgeStyle === 'corner_badge')
          "
          class="completion-badge"
          :class="[badgeStyle, badgePlacement]"
          :style="{ '--badge-color': badgeColor }"
        >
          <img
            v-if="badgeImageUrl"
            :src="badgeImageUrl"
            alt=""
            class="completion-badge-image"
          />
          <svg
            v-else
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="currentColor"
          >
            <path
              d="M12 2l2.4 6.6L21 9l-5 4.6L17.4 21 12 17.3 6.6 21 8 13.6 3 9l6.6-.4z"
            />
          </svg>
        </div>

        <div
          v-if="activityDot && !selectMode"
          class="activity-dot"
          :class="activityDot"
          :title="
            activityDot === 'never'
              ? 'Never launched'
              : 'Played in the last 2 weeks'
          "
        ></div>

        <div v-if="!selectMode && previewSynopsis" class="hover-preview">
          <p class="hover-preview-synopsis">{{ previewSynopsis }}</p>
          <p class="hover-preview-meta">
            {{ formatPlaytime(totalPlaytimeMinutes) }} · {{ lastPlayedLabel }}
          </p>
        </div>

        <div v-if="!selectMode" class="cover-actions">
          <button
            type="button"
            class="collection-button"
            @click.stop="emit('add-to-collection', game)"
          >
            <svg
              viewBox="0 0 24 24"
              width="15"
              height="15"
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
            type="button"
            class="favorite-button"
            :class="{ active: localFavorite }"
            :disabled="favoriteSaving"
            @click.stop="toggleFavorite"
          >
            <svg
              viewBox="0 0 24 24"
              width="15"
              height="15"
              :fill="localFavorite ? 'currentColor' : 'none'"
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

          <button
            type="button"
            class="menu-trigger"
            ref="menuTriggerRef"
            @click.stop="toggleMenu"
          >
            <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
              <circle cx="5" cy="12" r="2" />
              <circle cx="12" cy="12" r="2" />
              <circle cx="19" cy="12" r="2" />
            </svg>
          </button>
        </div>
      </div>

      <Teleport to="body">
        <div v-if="menuOpen" class="menu-backdrop" @click="closeMenu"></div>
        <Transition name="menu-pop">
          <div
            v-if="menuOpen"
            class="card-menu"
            :style="{
              top: menuPosition.top + 'px',
              left: menuPosition.left + 'px',
            }"
            @click.stop
          >
            <template v-if="!statusSubmenuOpen">
              <button type="button" class="menu-item" @click="openGame">
                Open
              </button>
              <div class="menu-divider"></div>
              <button
                type="button"
                class="menu-item"
                @click="
                  emit('edit', game);
                  closeMenu();
                "
              >
                Edit
              </button>
              <button
                type="button"
                class="menu-item"
                @click="statusSubmenuOpen = true"
              >
                Change Status
              </button>
              <button type="button" class="menu-item disabled" disabled>
                Refresh Metadata
              </button>
              <div class="menu-divider"></div>
              <button type="button" class="menu-item disabled" disabled>
                Add Screenshot
              </button>
              <button type="button" class="menu-item disabled" disabled>
                Add Clip
              </button>
              <div class="menu-divider"></div>
              <button type="button" class="menu-item" @click="copyFolderPath">
                Copy Folder Path
              </button>
            </template>
            <template v-else>
              <button
                type="button"
                class="menu-item back"
                @click="statusSubmenuOpen = false"
              >
                ← Back
              </button>
              <div class="menu-divider"></div>
              <button
                v-for="s in statuses"
                :key="s"
                type="button"
                class="menu-item"
                :class="{ active: s === localStatus }"
                @click="chooseStatus(s)"
              >
                {{ s }}
              </button>
            </template>
          </div>
        </Transition>
      </Teleport>
    </div>

    <div class="card-info">
      <h3 class="title">{{ game.title }}</h3>
      <div class="meta-row">
        <span class="status">{{ localStatus }}</span>
        <span v-if="score" class="rating">★ {{ score.sum.toFixed(1) }}</span>
        <span v-if="game.achievementPercent > 0" class="achievements">
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
          {{ game.achievementPercent }}%
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.game-card-wrap {
  width: 200px;
  flex-shrink: 0;
  min-width: 0;
}
.game-card {
  position: relative;
  width: 100%;
  border-radius: 10px;
  transition:
    transform 0.32s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.32s cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform;
  z-index: 1;
}
.game-card:hover,
.game-card.menu-open {
  transform: scale(1.07) translateY(-4px);
  box-shadow: 0 24px 56px rgba(0, 0, 0, 0.5);
  z-index: 10;
}
.game-card.keyboard-focused .cover {
  outline: 3px solid #d68a34;
  outline-offset: 3px;
}

/* completion badge, "glow"/"border" style the whole card (via --badge-color,
   set inline from Settings > Appearance); "ribbon"/"corner_badge" are
   positioned elements inside .cover instead, see .completion-badge below */
.game-card.badge-glow {
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--badge-color) 55%, transparent),
    0 0 22px 2px color-mix(in srgb, var(--badge-color) 45%, transparent);
}
.game-card.badge-glow:hover,
.game-card.badge-glow.menu-open {
  box-shadow:
    0 0 0 1px var(--badge-color),
    0 0 32px 6px color-mix(in srgb, var(--badge-color) 65%, transparent),
    0 24px 56px rgba(0, 0, 0, 0.5);
}
.game-card.badge-border {
  box-shadow: 0 0 0 2px var(--badge-color);
}
.game-card.badge-border:hover,
.game-card.badge-border.menu-open {
  box-shadow:
    0 0 0 2px var(--badge-color),
    0 24px 56px rgba(0, 0, 0, 0.5);
}
.completion-badge {
  position: absolute;
  z-index: 3;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--badge-color);
  pointer-events: none;
}
.completion-badge.top-left {
  top: 8px;
  left: 8px;
}
.completion-badge.top-right {
  top: 8px;
  right: 8px;
}
.completion-badge.bottom-left {
  bottom: 8px;
  left: 8px;
}
.completion-badge.bottom-right {
  bottom: 8px;
  right: 8px;
}
.completion-badge.corner_badge {
  background: rgba(20, 20, 20, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  border-radius: 50%;
  border: 1px solid color-mix(in srgb, var(--badge-color) 60%, transparent);
}
.completion-badge.ribbon {
  width: 46px;
  height: 46px;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.5));
}
.completion-badge-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.cover {
  position: relative;
  width: 100%;
  /* 2:3, matches SteamGridDB's Steam-vertical grid size (600x900) so
     cover art fills the box instead of getting cropped by object-fit */
  aspect-ratio: 2 / 3;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  background: #1a1a1a;
}
.cover-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.select-checkbox {
  position: absolute;
  top: 8px;
  left: 8px;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: 2px solid rgba(255, 255, 255, 0.6);
  background: rgba(20, 20, 20, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #111;
  z-index: 3;
  transition:
    background 0.15s ease,
    border-color 0.15s ease;
}
.select-checkbox.checked {
  background: #d68a34;
  border-color: #d68a34;
}
.hover-preview {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 26px 10px 10px;
  background: linear-gradient(
    to top,
    rgba(0, 0, 0, 0.92) 40%,
    rgba(0, 0, 0, 0.5) 75%,
    transparent
  );
  opacity: 0;
  transform: translateY(6px);
  transition:
    opacity 0.18s ease,
    transform 0.18s ease;
  transition-delay: 0.15s;
  pointer-events: none;
}
.game-card:hover .hover-preview {
  opacity: 1;
  transform: translateY(0);
}
.hover-preview-synopsis {
  margin: 0 0 6px;
  color: #eee;
  font-size: 11px;
  line-height: 1.45;
}
.hover-preview-meta {
  margin: 0;
  color: #d68a34;
  font-size: 10.5px;
  font-weight: 600;
}
.activity-dot {
  position: absolute;
  bottom: 8px;
  left: 8px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.55);
}
.activity-dot.never {
  background: #6a6a6a;
}
.activity-dot.recent {
  background: #4ade80;
}
.stale-indicator {
  position: absolute;
  top: 8px;
  left: 8px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(220, 38, 38, 0.85);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  z-index: 3;
}
.cover-actions {
  position: absolute;
  bottom: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  z-index: 3;
}
.favorite-button,
.collection-button,
.menu-trigger {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(20, 20, 20, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transform: translateY(4px);
  transition:
    opacity 0.2s ease,
    transform 0.2s ease,
    background 0.15s ease,
    color 0.15s ease,
    border-color 0.15s ease;
}
.game-card:hover .favorite-button,
.game-card:hover .collection-button,
.game-card:hover .menu-trigger,
.game-card.menu-open .favorite-button,
.game-card.menu-open .collection-button,
.game-card.menu-open .menu-trigger {
  opacity: 1;
  transform: translateY(0);
}
.favorite-button.active {
  color: #ff6f91;
  border-color: rgba(255, 111, 145, 0.4);
  background: rgba(224, 86, 122, 0.18);
}
.menu-trigger:hover,
.favorite-button:hover,
.collection-button:hover {
  background: rgba(40, 40, 40, 0.85);
  border-color: rgba(255, 255, 255, 0.3);
  transform: translateY(0) scale(1.1);
}
.menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;
}
.card-menu {
  position: fixed;
  width: 190px;
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 10px;
  padding: 6px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transform-origin: top right;
}
.menu-pop-enter-active,
.menu-pop-leave-active {
  transition:
    opacity 0.15s ease,
    transform 0.15s ease;
}
.menu-pop-enter-from,
.menu-pop-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.96);
}
.menu-item {
  text-align: left;
  background: none;
  border: none;
  color: #ddd;
  padding: 8px 10px;
  font-size: 13px;
  border-radius: 6px;
  cursor: pointer;
  text-transform: capitalize;
}
.menu-item:hover:not(.disabled) {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.menu-item.disabled {
  color: #555;
  cursor: not-allowed;
}
.menu-item.destructive {
  color: #f87171;
}
.menu-item.destructive:hover {
  background: rgba(220, 38, 38, 0.15);
}
.menu-item.active {
  color: #d68a34;
  font-weight: 600;
}
.menu-item.back {
  color: #999;
}
.menu-divider {
  height: 1px;
  background: #2a2a2a;
  margin: 4px 2px;
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
  color: #999;
}
.meta-row .status {
  text-transform: capitalize;
}
.meta-row .rating {
  color: #d68a34;
}
.meta-row .achievements {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.meta-row .achievements svg {
  flex-shrink: 0;
  opacity: 0.75;
}
</style>
