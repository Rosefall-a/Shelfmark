<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from "vue";
import {
  RouterLink,
  useRoute,
  useRouter,
  type RouteLocationRaw,
} from "vue-router";
import { logout } from "../services/auth";
import {
  pluginNavigation,
  refreshPluginExtensions,
} from "../state/pluginExtensions";
import { currentUser } from "../state/auth";
import {
  approvePluginAction,
  dispatchPluginAction,
} from "../services/pluginUi";
import { inboxCount, refreshInboxCount } from "../state/inbox";
import {
  notifications,
  notificationsLoaded,
  refreshNotifications,
  mediaNotifications,
  mediaUnread,
  refreshMediaNotifications,
  readMediaNotification,
  readAllMediaNotifications,
  mediaNotificationRoute,
} from "../state/notifications";

onMounted(refreshInboxCount);
onMounted(refreshNotifications);
onMounted(() => void refreshPluginExtensions());
// Asking the server for notifications is also what makes it create the
// newly due ones, so this poll is the whole "delivery" mechanism: cheap,
// every 5 minutes while the app is open, nothing running when it is not.
let notificationTimer: number | undefined;
onMounted(() => {
  refreshMediaNotifications();
  notificationTimer = window.setInterval(
    refreshMediaNotifications,
    5 * 60 * 1000,
  );
});
onUnmounted(() => window.clearInterval(notificationTimer));
function timeAgo(unix: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - unix));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
const notificationsExpanded = ref(false);

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

function close() {
  open.value = false;
}
const router = useRouter();
const mainPluginNavigation = computed(() =>
  pluginNavigation.value.filter(
    (item) =>
      (item.location === "main.sidebar" ||
        (item.location === "administration" && currentUser.value?.is_admin)) &&
      (!item.adminOnly || currentUser.value?.is_admin),
  ),
);

function pluginNavigationTarget(
  item: (typeof mainPluginNavigation.value)[number],
): RouteLocationRaw {
  if (item.settingsSectionId)
    return { path: "/settings", query: { section: item.settingsSectionId } };
  if (item.routePath)
    return {
      name: "plugin-route",
      params: { pluginId: item.pluginId, pluginPath: item.routePath },
    };
  return {
    name: "plugin-route",
    params: { pluginId: item.pluginId, pluginPath: item.pageId },
  };
}

async function activatePluginNavigation(
  item: (typeof mainPluginNavigation.value)[number],
) {
  if (!item.action) return;
  if (!approvePluginAction(item.action, window.confirm)) return;
  await dispatchPluginAction(item.pluginId, item.action.id);
  close();
}

async function handleLogout() {
  await logout();
  currentUser.value = null;
  close();
  router.push("/login");
}
</script>

<template>
  <button type="button" class="menu-toggle" @click="open = true">
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
    <span
      v-if="notifications.length + mediaUnread"
      class="menu-toggle-dot"
    ></span>
  </button>

  <Transition name="sidebar-backdrop">
    <div v-if="open" class="sidebar-backdrop" @click="close"></div>
  </Transition>

  <Transition name="sidebar-slide">
    <aside v-if="open" class="sidebar">
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

      <router-link to="/settings" class="sidebar-item" @click="close">
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
          <circle cx="12" cy="8" r="4" />
          <path d="M4 20c0-4.4 3.6-7 8-7s8 2.6 8 7" />
        </svg>
        <span>{{ currentUser?.username || "Profile" }}</span>
      </router-link>

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
          <path d="M3 11l9-8 9 8" />
          <path d="M5 10v10h14V10" />
        </svg>
        <span>Home</span>
      </router-link>

      <div
        class="sidebar-parent-row"
        :class="{ active: isActive('/games') && !isActive('/collections') }"
      >
        <router-link
          to="/games"
          class="sidebar-item sidebar-parent-link"
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
            <rect x="2" y="7" width="20" height="10" rx="4" />
            <line x1="7" y1="12" x2="9" y2="12" />
            <line x1="8" y1="11" x2="8" y2="13" />
            <circle cx="16" cy="11" r="0.8" fill="currentColor" />
            <circle cx="18" cy="13" r="0.8" fill="currentColor" />
          </svg>
          <span>Games</span>
        </router-link>
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
            <path
              d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
            />
          </svg>
          <span>Collections</span>
        </router-link>
      </div>

      <div
        class="sidebar-parent-row"
        :class="{ active: isActive('/cards') && !isActive('/sets') }"
      >
        <router-link
          to="/cards"
          class="sidebar-item sidebar-parent-link"
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
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M3 10h18" />
            <circle cx="8" cy="7" r="1" fill="currentColor" stroke="none" />
          </svg>
          <span>Cards</span>
        </router-link>
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

      <div class="sidebar-parent-row">
        <button
          type="button"
          class="sidebar-item sidebar-parent-link notification-toggle"
          @click="notificationsExpanded = !notificationsExpanded"
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
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.7 21a2 2 0 0 1-3.4 0" />
          </svg>
          <span>Notifications</span>
          <span v-if="notifications.length + mediaUnread" class="inbox-badge">{{
            notifications.length + mediaUnread
          }}</span>
        </button>
        <button
          type="button"
          class="sidebar-expand-toggle"
          :class="{ expanded: notificationsExpanded }"
          :title="notificationsExpanded ? 'Collapse' : 'Expand'"
          @click="notificationsExpanded = !notificationsExpanded"
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
      <div v-if="notificationsExpanded" class="sidebar-subitems">
        <p v-if="!notificationsLoaded" class="notification-empty">Loading…</p>
        <p
          v-else-if="!notifications.length && !mediaNotifications.length"
          class="notification-empty"
        >
          Nothing to flag right now.
        </p>
        <router-link
          to="/notifications"
          class="notification-see-all"
          @click="close"
        >
          See All Notifications
        </router-link>
        <div v-if="mediaNotifications.length" class="notification-group-head">
          <span>Episodes and releases</span>
          <button
            v-if="mediaUnread"
            type="button"
            @click="readAllMediaNotifications"
          >
            Mark All Read
          </button>
        </div>
        <router-link
          v-for="n in mediaNotifications.slice(0, 15)"
          :key="n.id"
          :to="mediaNotificationRoute(n)"
          class="notification-row"
          :class="{ read: n.read }"
          @click="
            readMediaNotification(n.id);
            close();
          "
        >
          <span
            v-if="n.posterUrl"
            class="notification-poster"
            :style="{ backgroundImage: `url(${n.posterUrl})` }"
          ></span>
          <span
            v-else
            class="notification-dot"
            :class="{ unread: !n.read }"
          ></span>
          <span class="notification-text">
            <span class="notification-title">{{ n.title }}</span>
            <span class="notification-detail"
              >{{ n.body }} · {{ timeAgo(n.eventAt) }}</span
            >
          </span>
          <span v-if="!n.read" class="notification-unread-dot"></span>
        </router-link>
        <div v-if="notifications.length" class="notification-group-head">
          <span>Bounties</span>
        </div>
        <router-link
          v-for="n in notifications"
          :key="n.id"
          :to="n.to"
          class="notification-row"
          @click="close"
        >
          <span class="notification-dot" :class="n.kind"></span>
          <span class="notification-text">
            <span class="notification-title">{{ n.title }}</span>
            <span class="notification-detail">{{ n.detail }}</span>
          </span>
        </router-link>
      </div>

      <router-link
        to="/inbox"
        class="sidebar-item"
        :class="{ active: isActive('/inbox') }"
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
          <path d="M22 12h-6l-2 3h-4l-2-3H2" />
          <path
            d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"
          />
        </svg>
        <span>Inbox</span>
        <span v-if="inboxCount" class="inbox-badge">{{ inboxCount }}</span>
      </router-link>

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
        <router-link
          to="/movies"
          class="sidebar-item sidebar-parent-link"
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
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <line x1="3" y1="9" x2="21" y2="9" />
          </svg>
          <span>Media</span>
        </router-link>
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
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <line x1="3" y1="9" x2="21" y2="9" />
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
            <rect x="2" y="5" width="20" height="14" rx="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="19" x2="12" y2="21" />
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
            <circle cx="12" cy="12" r="9" />
            <path
              d="M8 9c.5-1.5 2-2 4-2s3.5.5 4 2M9 13c.7.8 1.8 1.3 3 1.3s2.3-.5 3-1.3"
            />
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
          <rect x="3" y="4" width="18" height="18" rx="2" />
          <line x1="3" y1="10" x2="21" y2="10" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="16" y1="2" x2="16" y2="6" />
        </svg>
        <span>Calendar</span>
      </router-link>
      <router-link
        to="/statistics"
        class="sidebar-item"
        :class="{ active: isActive('/statistics') }"
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
          <line x1="4" y1="20" x2="20" y2="20" />
          <rect x="6" y="12" width="3" height="8" rx="0.5" />
          <rect x="12" y="7" width="3" height="13" rx="0.5" />
          <rect x="18" y="3" width="3" height="17" rx="0.5" />
        </svg>
        <span>Statistics</span>
      </router-link>

      <component
        :is="item.action ? 'button' : RouterLink"
        v-for="item in mainPluginNavigation"
        :key="`${item.pluginId}:${item.contributionId}`"
        :to="item.action ? undefined : pluginNavigationTarget(item)"
        :type="item.action ? 'button' : undefined"
        class="sidebar-item plugin-sidebar-item"
        :class="{ active: isActive(`/plugins/${item.pluginId}`) }"
        @click="item.action ? activatePluginNavigation(item) : close()"
      >
        <span
          v-if="item.icon"
          class="plugin-navigation-icon"
          aria-hidden="true"
        >
          {{ item.icon }}
        </span>
        <svg
          v-else
          viewBox="0 0 24 24"
          width="18"
          height="18"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path
            d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3m13 5h3a2 2 0 0 0 2-2v-3"
          />
          <rect x="8" y="8" width="8" height="8" rx="2" />
        </svg>
        <span>{{ item.label }}</span>
      </component>

      <div class="sidebar-spacer"></div>

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
  width: 270px;
  background: #161616;
  border-right: 1px solid #2a2a2a;
  z-index: 110;
  display: flex;
  flex-direction: column;
  padding: 20px 14px;
  font-family: system-ui, sans-serif;
  box-shadow: 12px 0 40px rgba(0, 0, 0, 0.4);
}
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px 18px;
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
.sidebar-divider {
  height: 1px;
  background: #2a2a2a;
  margin: 8px 10px 12px;
}
.sidebar-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  color: #ccc;
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.sidebar-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}
.sidebar-item.active {
  background: rgba(214, 138, 52, 0.14);
  color: #d68a34;
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
  background: rgba(214, 138, 52, 0.14);
  color: #d68a34;
}
.sidebar-parent-row.active .sidebar-parent-link {
  color: #d68a34;
}
.sidebar-parent-link {
  flex: 1;
  min-width: 0;
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
.notification-toggle {
  background: none;
  border: none;
  width: 100%;
  font: inherit;
  text-align: left;
}
.notification-empty {
  color: #666;
  font-size: 12.5px;
  padding: 6px 8px;
  margin: 0;
}
.notification-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 8px;
  border-radius: 6px;
  text-decoration: none;
  color: inherit;
  font-size: 13px;
}
.notification-row:hover {
  background: rgba(255, 255, 255, 0.06);
}
.notification-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
}
.notification-dot.deadline {
  background: #f87171;
}
.notification-dot.suggested {
  background: #d68a34;
}
.notification-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.notification-title {
  color: #eee;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.notification-detail {
  color: #888;
  font-size: 11.5px;
}
.notification-see-all {
  display: block;
  padding: 6px 8px 2px;
  font-size: 12px;
  font-weight: 700;
  color: #d68a34;
  text-decoration: none;
}
.notification-see-all:hover {
  text-decoration: underline;
}
.notification-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 8px 2px;
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #666;
}
.notification-group-head button {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  font-size: 11px;
  text-transform: none;
  letter-spacing: 0;
  color: #d68a34;
  cursor: pointer;
}
.notification-row.read {
  opacity: 0.55;
}
.notification-poster {
  width: 26px;
  height: 38px;
  border-radius: 4px;
  flex-shrink: 0;
  background: #222 center / cover;
}
.notification-dot.unread {
  background: #6fbf73;
}
.notification-unread-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #d68a34;
  flex-shrink: 0;
  margin: 5px 0 0 auto;
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
.logout-item {
  margin-top: 8px;
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
