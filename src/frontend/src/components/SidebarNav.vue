<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { logout } from "../services/auth";
import { currentUser } from "../state/auth";
import { inboxCount, refreshInboxCount } from "../state/inbox";
import { mediaUnread, refreshMediaNotifications } from "../state/notifications";
import {
  sidebarMode,
  sidebarWidth,
  setSidebarWidth,
  resetSidebarWidth,
  sidebarResizing,
} from "../state/sidebarMode";
import ProfileMenu from "./ProfileMenu.vue";

onMounted(refreshInboxCount);
// Asking the server for notifications is also what makes it create the
// newly due ones, so this poll is the whole "delivery" mechanism: cheap,
// every 5 minutes while the app is open, nothing running when it is not.
// The sidebar keeps this timer even though it no longer shows the list
// itself (that moved to the topbar bell) because nothing else in the app
// polls — NotificationBell.vue only refreshes once on mount.
let notificationTimer: number | undefined;
onMounted(() => {
  refreshMediaNotifications();
  notificationTimer = window.setInterval(
    refreshMediaNotifications,
    5 * 60 * 1000,
  );
});
onUnmounted(() => window.clearInterval(notificationTimer));
onUnmounted(() => {
  document.removeEventListener("mousemove", onResizeMove);
  document.removeEventListener("mouseup", stopResize);
});

const route = useRoute();
const open = ref(false);

function isActive(path: string) {
  return route.path === path || route.path.startsWith(`${path}/`);
}

const gamesExpanded = ref(isActive("/games") || isActive("/collections"));
const cardsExpanded = ref(isActive("/cards") || isActive("/sets"));
const mediaExpanded = ref(
  isActive("/movies") ||
    isActive("/tv") ||
    isActive("/anime") ||
    isActive("/lists"),
);

const isMockData = import.meta.env.VITE_USE_MOCK_DATA === "true";

// Pinned and rail modes are always on screen, so "open" only governs the
// overlay's own show/hide and the backdrop/menu button that go with it.
const sidebarVisible = computed(
  () => sidebarMode.value !== "overlay" || open.value,
);

function close() {
  open.value = false;
}
const router = useRouter();

// Drag-resize: the handle sits on the sidebar's right edge, so the new
// width is just the pointer's distance from the (fixed, left: 0) edge.
// Rail mode skips this — its collapsed width is fixed on purpose, and
// resizing mid-hover would fight the hover-expand transition.
function startResize(e: MouseEvent) {
  if (sidebarMode.value === "rail") return;
  sidebarResizing.value = true;
  e.preventDefault();
  document.addEventListener("mousemove", onResizeMove);
  document.addEventListener("mouseup", stopResize);
}
function onResizeMove(e: MouseEvent) {
  setSidebarWidth(e.clientX);
}
function stopResize() {
  sidebarResizing.value = false;
  document.removeEventListener("mousemove", onResizeMove);
  document.removeEventListener("mouseup", stopResize);
}

// Rail mode also expands on keyboard focus (:focus-within), so tabbing in
// works without a mouse. But that means clicking a link leaves it focused,
// and a plain :hover/:focus-within CSS rule then keeps the rail pinned
// open after the mouse has already left — it takes a click somewhere else
// to move focus away before it can collapse. Blurring on mouse-leave
// closes the gap: focus no longer outlives the hover once you've moved on.
const asideRef = ref<HTMLElement | null>(null);
function onRailMouseLeave() {
  if (sidebarMode.value !== "rail") return;
  const active = document.activeElement as HTMLElement | null;
  if (active && asideRef.value?.contains(active)) active.blur();
}

async function handleLogout() {
  await logout();
  currentUser.value = null;
  close();
  router.push("/login");
}
</script>

<template>
  <button
    v-if="sidebarMode === 'overlay'"
    type="button"
    class="menu-toggle"
    @click="open = true"
  >
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
    <span v-if="mediaUnread" class="menu-toggle-dot"></span>
  </button>

  <Transition name="sidebar-backdrop">
    <div
      v-if="open && sidebarMode === 'overlay'"
      class="sidebar-backdrop"
      @click="close"
    ></div>
  </Transition>

  <Transition name="sidebar-slide">
    <aside
      v-if="sidebarVisible"
      ref="asideRef"
      class="sidebar"
      :class="{
        'pinned-mode': sidebarMode === 'pinned',
        'rail-mode': sidebarMode === 'rail',
        resizing: sidebarResizing,
      }"
      :style="{ '--sidebar-w': `${sidebarWidth}px` }"
      @mouseleave="onRailMouseLeave"
    >
      <div
        v-if="sidebarMode !== 'rail'"
        class="sidebar-resize-handle"
        title="Drag to resize, double-click to reset"
        @mousedown="startResize"
        @dblclick="resetSidebarWidth"
      ></div>
      <div class="sidebar-brand">
        <div class="brand-icon">🎮</div>
        <span class="brand-name">Archive</span>
        <span
          v-if="isMockData"
          class="mock-badge"
          title="Showing local sample data, not your real library"
        >
          Mock Data
        </span>
      </div>

      <ProfileMenu
        v-if="currentUser"
        class="sidebar-profile"
        :initials="currentUser.username.slice(0, 2).toUpperCase()"
      >
        <span class="sidebar-profile-name">{{ currentUser.username }}</span>
      </ProfileMenu>

      <div class="sidebar-divider"></div>

      <router-link
        to="/"
        class="sidebar-item"
        :class="{ active: isActive('/') }"
        @click="close"
      >
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M4 11l8-7 8 7" />
          <path d="M6 10v9a1 1 0 0 0 1 1h3v-5h4v5h3a1 1 0 0 0 1-1v-9" />
        </svg>
        <span>Home</span>
      </router-link>

      <div class="sidebar-group-label">
        <span class="sidebar-group-label-text">Library</span>
        <span class="sidebar-group-label-rule"></span>
      </div>

      <div
        class="sidebar-parent-row"
        :class="{ active: isActive('/games') || isActive('/collections') }"
      >
        <button
          type="button"
          class="sidebar-item sidebar-parent-link"
          @click="gamesExpanded = !gamesExpanded"
        >
          <svg
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
              d="M6 6h12a3 3 0 0 1 3 3v1l1.3 7a2.2 2.2 0 0 1-4 1.7L17 16H7l-1.3 2.7a2.2 2.2 0 0 1-4-1.7L3 10v-1a3 3 0 0 1 3-3z"
            />
            <path d="M7.3 9.3v4M5.3 11.3h4" />
            <circle cx="16" cy="9.5" r="0.9" fill="currentColor" />
            <circle cx="18" cy="11.5" r="0.9" fill="currentColor" />
            <circle cx="16" cy="13.5" r="0.9" fill="currentColor" />
            <circle cx="14" cy="11.5" r="0.9" fill="currentColor" />
          </svg>
          <span>Games</span>
        </button>
        <button
          type="button"
          class="sidebar-expand-toggle"
          :class="{ expanded: gamesExpanded }"
          :title="gamesExpanded ? 'Collapse' : 'Expand'"
          @click="gamesExpanded = !gamesExpanded"
        >
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
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>
      </div>

      <div v-if="gamesExpanded" class="sidebar-subitems">
        <router-link
          to="/games"
          class="sidebar-item sidebar-subitem"
          :class="{ active: isActive('/games') }"
          @click="close"
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
              d="M6 6h12a3 3 0 0 1 3 3v1l1.3 7a2.2 2.2 0 0 1-4 1.7L17 16H7l-1.3 2.7a2.2 2.2 0 0 1-4-1.7L3 10v-1a3 3 0 0 1 3-3z"
            />
            <path d="M7.3 9.3v4M5.3 11.3h4" />
            <circle cx="16" cy="9.5" r="0.9" fill="currentColor" />
            <circle cx="18" cy="11.5" r="0.9" fill="currentColor" />
            <circle cx="16" cy="13.5" r="0.9" fill="currentColor" />
            <circle cx="14" cy="11.5" r="0.9" fill="currentColor" />
          </svg>
          <span>Games</span>
        </router-link>
        <router-link
          to="/collections"
          class="sidebar-item sidebar-subitem"
          :class="{ active: isActive('/collections') }"
          @click="close"
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
            <path d="M4 7l8-4 8 4-8 4-8-4z" />
            <path d="M4 12l8 4 8-4M4 17l8 4 8-4" />
          </svg>
          <span>Collections</span>
        </router-link>
      </div>

      <div
        class="sidebar-parent-row"
        :class="{ active: isActive('/cards') || isActive('/sets') }"
      >
        <button
          type="button"
          class="sidebar-item sidebar-parent-link"
          @click="cardsExpanded = !cardsExpanded"
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M3 10h18" />
            <circle cx="8" cy="7" r="1" fill="currentColor" stroke="none" />
          </svg>
          <span>Cards</span>
        </button>
        <button
          type="button"
          class="sidebar-expand-toggle"
          :class="{ expanded: cardsExpanded }"
          :title="cardsExpanded ? 'Collapse' : 'Expand'"
          @click="cardsExpanded = !cardsExpanded"
        >
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
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>
      </div>

      <div v-if="cardsExpanded" class="sidebar-subitems">
        <router-link
          to="/cards"
          class="sidebar-item sidebar-subitem"
          :class="{ active: isActive('/cards') }"
          @click="close"
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
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M3 10h18" />
          </svg>
          <span>All Cards</span>
        </router-link>
        <router-link
          to="/sets"
          class="sidebar-item sidebar-subitem"
          :class="{ active: isActive('/sets') }"
          @click="close"
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
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
            <rect x="14" y="14" width="7" height="7" rx="1" />
          </svg>
          <span>Sets</span>
        </router-link>
      </div>

      <div
        class="sidebar-parent-row"
        :class="{
          active:
            isActive('/movies') ||
            isActive('/tv') ||
            isActive('/anime') ||
            isActive('/lists'),
        }"
      >
        <button
          type="button"
          class="sidebar-item sidebar-parent-link"
          @click="mediaExpanded = !mediaExpanded"
        >
          <svg
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
            <path d="M10 8.5l6 3.5-6 3.5z" />
          </svg>
          <span>Media</span>
        </button>
        <button
          type="button"
          class="sidebar-expand-toggle"
          :class="{ expanded: mediaExpanded }"
          :title="mediaExpanded ? 'Collapse' : 'Expand'"
          @click="mediaExpanded = !mediaExpanded"
        >
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
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>
      </div>

      <div v-if="mediaExpanded" class="sidebar-subitems">
        <router-link
          to="/movies"
          class="sidebar-item sidebar-subitem"
          :class="{ active: isActive('/movies') }"
          @click="close"
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
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <line x1="3" y1="8" x2="21" y2="8" />
            <rect
              x="5.5"
              y="4.5"
              width="1.6"
              height="1.6"
              fill="currentColor"
              stroke="none"
            />
            <rect
              x="9.8"
              y="4.5"
              width="1.6"
              height="1.6"
              fill="currentColor"
              stroke="none"
            />
            <rect
              x="14.1"
              y="4.5"
              width="1.6"
              height="1.6"
              fill="currentColor"
              stroke="none"
            />
            <rect
              x="18.4"
              y="4.5"
              width="1.6"
              height="1.6"
              fill="currentColor"
              stroke="none"
            />
          </svg>
          <span>Movies</span>
        </router-link>
        <router-link
          to="/tv"
          class="sidebar-item sidebar-subitem"
          :class="{ active: isActive('/tv') }"
          @click="close"
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
            <rect x="2" y="5" width="20" height="13" rx="2" />
            <path d="M8 21h8M12 18v3" />
          </svg>
          <span>TV</span>
        </router-link>
        <router-link
          to="/anime"
          class="sidebar-item sidebar-subitem"
          :class="{ active: isActive('/anime') }"
          @click="close"
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
              d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"
            />
            <path d="M19 15l0.7 2 2 0.7-2 0.7-0.7 2-0.7-2-2-0.7 2-0.7z" />
          </svg>
          <span>Anime</span>
        </router-link>
        <router-link
          to="/lists"
          class="sidebar-item sidebar-subitem"
          :class="{ active: isActive('/lists') }"
          @click="close"
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
            <line x1="8" y1="6" x2="21" y2="6" />
            <line x1="8" y1="12" x2="21" y2="12" />
            <line x1="8" y1="18" x2="21" y2="18" />
            <line x1="3" y1="6" x2="3.01" y2="6" />
            <line x1="3" y1="12" x2="3.01" y2="12" />
            <line x1="3" y1="18" x2="3.01" y2="18" />
          </svg>
          <span>Lists</span>
        </router-link>
      </div>

      <div class="sidebar-group-label">
        <span class="sidebar-group-label-text">Tools</span>
        <span class="sidebar-group-label-rule"></span>
      </div>

      <router-link
        to="/bounties"
        class="sidebar-item"
        :class="{ active: isActive('/bounties') }"
        @click="close"
      >
        <svg
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
          <circle cx="12" cy="12" r="5" />
          <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
        </svg>
        <span>Bounties</span>
      </router-link>
      <router-link
        to="/calendar"
        class="sidebar-item"
        :class="{ active: isActive('/calendar') }"
        @click="close"
      >
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect x="3" y="5" width="18" height="16" rx="2" />
          <path d="M3 10h18M8 3v4M16 3v4" />
          <circle cx="8" cy="14" r="1" fill="currentColor" />
          <circle cx="12" cy="14" r="1" fill="currentColor" />
        </svg>
        <span>Calendar</span>
      </router-link>
      <router-link
        to="/statistics"
        class="sidebar-item"
        :class="{ active: isActive('/statistics') }"
        @click="close"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
          <rect x="4" y="13" width="4" height="7" rx="1" />
          <rect x="10" y="9" width="4" height="11" rx="1" />
          <rect x="16" y="4" width="4" height="16" rx="1" />
        </svg>
        <span>Statistics</span>
      </router-link>
      <router-link
        to="/settings?section=upload"
        class="sidebar-item"
        :class="{
          active: isActive('/settings') && route.query.section === 'upload',
        }"
        @click="close"
      >
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M12 16V4M8 8l4-4 4 4" />
          <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
        </svg>
        <span>Upload</span>
        <span v-if="inboxCount" class="inbox-badge">{{ inboxCount }}</span>
      </router-link>

      <div class="sidebar-spacer"></div>

      <div class="sidebar-bottom">
        <router-link
          to="/settings"
          class="sidebar-item"
          :class="{ active: isActive('/settings') }"
          @click="close"
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="12" r="3" />
            <path
              d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1z"
            />
          </svg>
          <span>Settings</span>
        </router-link>
        <button
          type="button"
          class="sidebar-item logout-item"
          @click="handleLogout"
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
          <span>Log Out</span>
        </button>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.menu-toggle {
  position: fixed;
  top: 16px;
  left: 16px;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(20, 20, 20, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 100;
  transition: background 0.15s ease;
}
.menu-toggle:hover {
  background: rgba(40, 40, 40, 0.85);
}
.menu-toggle-dot {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #d68a34;
  border: 2px solid #121212;
}
.sidebar-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 105;
}
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: var(--sidebar-w, 270px);
  background: #161616;
  border-right: 1px solid #2a2a2a;
  z-index: 110;
  display: flex;
  flex-direction: column;
  padding: 20px 14px;
  font-family: system-ui, sans-serif;
  box-shadow: 12px 0 40px rgba(0, 0, 0, 0.4);
  /* On a short window the nav list can be taller than the screen — without
     this it just ran off the bottom edge with no way to reach Settings/Log
     Out. auto only shows a scrollbar when content actually overflows. */
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
  scrollbar-color: #3a3a3a transparent;
}
.sidebar::-webkit-scrollbar {
  width: 8px;
}
.sidebar::-webkit-scrollbar-track {
  background: transparent;
}
.sidebar::-webkit-scrollbar-thumb {
  background: #3a3a3a;
  border-radius: 999px;
}
.sidebar::-webkit-scrollbar-thumb:hover {
  background: #4a4a4a;
}
.sidebar.pinned-mode {
  box-shadow: none;
}
.sidebar.resizing {
  transition: none;
  user-select: none;
}
.sidebar-resize-handle {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
  z-index: 1;
}
.sidebar-resize-handle:hover,
.sidebar.resizing .sidebar-resize-handle {
  background: rgba(214, 138, 52, 0.4);
}
.sidebar.rail-mode {
  width: 56px;
  padding-left: 8px;
  padding-right: 8px;
  transition:
    width 0.18s ease,
    padding 0.18s ease;
}
.sidebar.rail-mode:hover,
.sidebar.rail-mode:focus-within {
  width: var(--sidebar-w, 270px);
  padding-left: 14px;
  padding-right: 14px;
}
/* Collapsed rail shows icons only, with no expand chevrons or sub-items.
   Hovering (or tabbing in) widens the rail back to the full layout, at
   which point all of this reverts to the normal sidebar look.

   The icon's own padding is a FIXED value in rail mode, the same whether
   collapsed or expanded — chosen so it exactly centres the icon inside
   the 56px collapsed rail (56 - 18px icon = 38, 19px either side). It
   never toggles, so there's nothing to snap: hovering only grows the
   rail itself and reveals more room to the icon's right for the label to
   fade into. Two earlier versions got this wrong in opposite directions:
   toggling justify-content snapped instantly (not animatable), and
   toggling padding down to near-zero while centred pulled the icon off
   to the left instead of keeping it centred. */
.sidebar.rail-mode:not(:hover):not(:focus-within) .sidebar-subitems {
  display: none;
}
/* Unlike sub-items (a block of extra rows, legitimately tied to whether
   Games/Media is expanded), these three are small inline badges that
   used to display: none inside a row that otherwise stays the same
   height — but a badge can still be taller than the icon next to it
   (the mock-data pill was, by 8px), so hiding it outright shrank its
   row, and revealing it grew that row back, nudging every row below it
   down. Fading them in place keeps each row's own height constant too. */
.mock-badge,
.inbox-badge,
.sidebar-expand-toggle {
  opacity: 1;
  transition: opacity 0.14s ease 0.05s;
}
.sidebar.rail-mode:not(:hover):not(:focus-within) .mock-badge,
.sidebar.rail-mode:not(:hover):not(:focus-within) .inbox-badge,
.sidebar.rail-mode:not(:hover):not(:focus-within) .sidebar-expand-toggle {
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.08s ease;
}
/* Group labels ("Library", "Tools") used to display: none in the
   collapsed rail like everything above, which freed their row's height
   entirely — so every icon below a hidden label jumped up to fill the
   gap, then jumped back down the moment you hovered and the label
   reappeared. The row itself (and its height) stays put in both states
   now; only the text inside cross-fades with a thin divider line, so
   expanding the rail moves things sideways, not vertically. */
.sidebar-group-label-text {
  min-width: 0;
  flex-shrink: 1;
  opacity: 1;
  white-space: nowrap;
  overflow: hidden;
  transition: opacity 0.14s ease 0.05s;
}
.sidebar-group-label-rule {
  flex: 1;
  min-width: 0;
  height: 1px;
  background: #2a2a2a;
  opacity: 0;
  transition: opacity 0.08s ease;
}
.sidebar.rail-mode:not(:hover):not(:focus-within) .sidebar-group-label-text {
  opacity: 0;
  transition: opacity 0.08s ease;
}
.sidebar.rail-mode:not(:hover):not(:focus-within) .sidebar-group-label-rule {
  opacity: 1;
  transition: opacity 0.14s ease 0.05s;
}
/* The label's invisible-but-still-in-the-flex-row width (opacity: 0, not
   display: none — see below) means flex-shrink's default of 1 would
   squeeze every child in the row to fit once the rail is narrower than
   icon + label combined, icon included. flex-shrink: 0 excludes the
   icon and the brand emoji from that, so they always render full size
   regardless of how little room the invisible label actually has. */
.sidebar-item svg,
.sidebar-parent-link svg,
.brand-icon {
  flex-shrink: 0;
}
/* These four ride along the icon row (or sit right next to the avatar).
   They fade with a plain opacity transition — no width/max-width
   animation on the text itself, which looked like the label was being
   squeezed or stretched instead of just appearing. The rail's own
   overflow: hidden (set above) clips whatever the fading text doesn't
   have room for; the text never needs to know its own size. */
.sidebar-item span,
.sidebar-parent-link span,
.sidebar-profile-name,
.brand-name {
  min-width: 0;
  opacity: 1;
  white-space: nowrap;
  transition: opacity 0.14s ease 0.05s;
}
.sidebar.rail-mode:not(:hover):not(:focus-within) .sidebar-item span,
.sidebar.rail-mode:not(:hover):not(:focus-within) .sidebar-parent-link span,
.sidebar.rail-mode:not(:hover):not(:focus-within) .sidebar-profile-name,
.sidebar.rail-mode:not(:hover):not(:focus-within) .brand-name {
  opacity: 0;
  transition: opacity 0.08s ease;
}
.sidebar.rail-mode .sidebar-item,
.sidebar.rail-mode .sidebar-parent-link {
  padding-left: 19px;
  padding-right: 19px;
}
.sidebar.rail-mode .sidebar-brand {
  padding-left: 16px;
  padding-right: 16px;
}
.sidebar.rail-mode .sidebar-profile {
  padding-left: 12px;
  padding-right: 12px;
}
/* ProfileMenu's own trigger (inside ProfileMenu.vue's scoped styles,
   unreachable here without :deep()) keeps a fixed 10px gap between the
   name slot and the avatar even once the name has shrunk away to
   nothing, which pushed the avatar 10px right of centre. Dropping it to
   0 only while collapsed removes exactly that offset; it isn't the
   justify-content toggle that caused the icon-jump bug elsewhere, just a
   small gap disappearing in step with the name it was spacing. */
.sidebar.rail-mode:not(:hover):not(:focus-within)
  .sidebar-profile
  :deep(.profile-menu-trigger) {
  gap: 0;
}
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px 18px;
  margin-bottom: 6px;
  border-bottom: 1px solid #232323;
  transition: padding 0.18s ease;
}
.brand-icon {
  font-size: 22px;
}
.brand-name {
  color: #fff;
  font-weight: 700;
  font-size: 16px;
}
.mock-badge {
  margin-left: auto;
  font-size: 10px;
  font-weight: 700;
  color: #d68a34;
  background: rgba(214, 138, 52, 0.14);
  border: 1px solid rgba(214, 138, 52, 0.35);
  padding: 3px 8px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  white-space: nowrap;
}
.sidebar-profile {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 11px;
  border-radius: 10px;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.035);
  border: 1px solid rgba(255, 255, 255, 0.06);
  transition: padding 0.18s ease;
}
.sidebar-profile:hover {
  background: rgba(255, 255, 255, 0.07);
}
.sidebar-profile-name {
  flex-grow: 1;
  min-width: 0;
  color: #eee;
  font-size: 13.5px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-divider {
  height: 1px;
  background: #2a2a2a;
  margin: 8px 10px 12px;
}
.sidebar-group-label {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 12px 6px;
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #7d7d7d;
}
.sidebar-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 12px;
  border-radius: 8px;
  color: #ccc;
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease,
    padding 0.18s ease,
    gap 0.18s ease;
}
.sidebar-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}
.sidebar-item.active {
  background: rgba(214, 138, 52, 0.12);
  color: #e9a94f;
  font-weight: 600;
  box-shadow: inset 3px 0 0 #d68a34;
}
/* The global focus-visible ring is the same orange as the active-page
   highlight, so a button that simply held keyboard/click focus (Log
   Out, most often) looked permanently "selected" even though it was
   never the active page. A neutral ring keeps it visible for keyboard
   users without reading as a selected/current item. */
.sidebar-item:focus-visible,
.sidebar-parent-link:focus-visible {
  outline: 2px solid rgba(255, 255, 255, 0.4);
  outline-offset: -2px;
}
.sidebar-parent-row {
  display: flex;
  align-items: center;
  gap: 2px;
  border-radius: 8px;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.sidebar-parent-row.active {
  background: rgba(214, 138, 52, 0.12);
  color: #e9a94f;
  box-shadow: inset 3px 0 0 #d68a34;
}
.sidebar-parent-row.active .sidebar-parent-link {
  color: #e9a94f;
  font-weight: 600;
}
.sidebar-parent-row.active .sidebar-expand-toggle {
  color: #e9a94f;
}
.sidebar-parent-link {
  flex: 1;
  min-width: 0;
  background: none;
  border: none;
  width: 100%;
  font: inherit;
  text-align: left;
}
.sidebar-expand-toggle {
  background: none;
  border: none;
  color: #999;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    transform 0.2s ease,
    background 0.15s ease,
    color 0.15s ease;
}
.sidebar-expand-toggle:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.sidebar-expand-toggle.expanded {
  transform: rotate(90deg);
}
.sidebar-subitems {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-left: 18px;
  padding-left: 12px;
  border-left: 1px solid #2a2a2a;
}
.sidebar-subitem {
  font-size: 13px;
}
.inbox-badge {
  margin-left: auto;
  font-size: 11px;
  font-weight: 700;
  color: #111;
  background: #d68a34;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.sidebar-spacer {
  flex: 1;
}
/* Log Out is a <button>, so without these it fell back to the browser's
   default button face (grey fill, border, system font) — the "always
   highlighted" look. It now matches every other row, tinted red. */
.logout-item {
  width: 100%;
  background: none;
  border: none;
  font: inherit;
  font-size: 14px;
  text-align: left;
  color: #e08585;
}
.logout-item:hover {
  background: rgba(224, 133, 133, 0.12);
  color: #f0a0a0;
}
.sidebar-bottom {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid #232323;
}
.sidebar-slide-enter-active,
.sidebar-slide-leave-active {
  transition: transform 0.25s ease;
}
.sidebar-slide-enter-from,
.sidebar-slide-leave-to {
  transform: translateX(-100%);
}
.sidebar-backdrop-enter-active,
.sidebar-backdrop-leave-active {
  transition: opacity 0.25s ease;
}
.sidebar-backdrop-enter-from,
.sidebar-backdrop-leave-to {
  opacity: 0;
}
</style>
