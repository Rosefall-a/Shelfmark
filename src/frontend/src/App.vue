<script setup lang="ts">
import { useRoute } from "vue-router";
import SidebarNav from "./components/SidebarNav.vue";
import TaskProgressToast from "./components/TaskProgressToast.vue";
import ShortcutsHelp from "./components/ShortcutsHelp.vue";
import CommandPalette from "./components/CommandPalette.vue";
import AppDialog from "./components/AppDialog.vue";
import { authChecked, currentUser } from "./state/auth";
import { mediaUnread } from "./state/notifications";
import { formatDocumentTitle, pageTitleOverride } from "./state/pageTitle";
import { loadSharedPreferences } from "./state/preferences";
import {
  sidebarMode,
  sidebarWidth,
  sidebarResizing,
} from "./state/sidebarMode";
import { computed, watch, watchEffect } from "vue";

const route = useRoute();
// "(2) Hades | Archive": the page (or what it shows) and unread notifications
watchEffect(() => {
  document.title = formatDocumentTitle(
    pageTitleOverride() ?? route.meta.title,
    currentUser.value ? mediaUnread.value : 0,
  );
});
// preferences are per user, so load them once someone is signed in
watch(
  () => currentUser.value?.id,
  (id) => {
    if (id) loadSharedPreferences();
  },
  { immediate: true },
);
const sidebarShown = computed(
  () =>
    route.path !== "/login" &&
    route.path !== "/setup" &&
    route.path !== "/login/oidcstart",
);
// Pinned and rail modes sit in the page's own layout, so content needs to
// make room for them. Overlay floats above everything and reserves nothing.
// Pinned's reserved width tracks the sidebar's own (resizable) width;
// rail's collapsed width is fixed, since that's the "just icons" point.
const contentStyle = computed(() => {
  if (!sidebarShown.value) return {};
  if (sidebarMode.value === "pinned")
    return { marginLeft: `${sidebarWidth.value}px` };
  if (sidebarMode.value === "rail") return { marginLeft: "56px" };
  return {};
});
const KEPT_ALIVE = [
  "MovieLibrary",
  "TVShowLibrary",
  "AnimeLibrary",
  "Calendar",
  "MediaLists",
  "Statistics",
  "Notifications",
];
</script>

<template>
  <!-- First-run setup and the direct OIDC entrypoint deliberately bypass
       normal authentication, so both must render while authChecked is false. -->
  <template
    v-if="
      authChecked ||
      route.path === '/setup' ||
      route.path === '/login/oidcstart'
    "
  >
    <SidebarNav v-if="sidebarShown" />
    <!-- Library, calendar and list pages stay mounted when you leave them, so
         switching tabs is instant instead of reloading from empty. Detail
         pages are deliberately not kept: they must reload per title. -->
    <div
      class="app-content"
      :class="{ resizing: sidebarResizing }"
      :style="contentStyle"
    >
      <router-view v-slot="{ Component }">
        <KeepAlive :include="KEPT_ALIVE" :max="8">
          <component :is="Component" />
        </KeepAlive>
      </router-view>
    </div>
    <TaskProgressToast
      v-if="route.path !== '/setup' && route.path !== '/login/oidcstart'"
    />
    <AppDialog />
    <ShortcutsHelp
      v-if="
        route.path !== '/login' &&
        route.path !== '/setup' &&
        route.path !== '/login/oidcstart'
      "
    />
    <CommandPalette
      v-if="
        route.path !== '/login' &&
        route.path !== '/setup' &&
        route.path !== '/login/oidcstart'
      "
    />
  </template>
  <main v-else class="app-loading">
    <p>Loading…</p>
  </main>
</template>

<style scoped>
.app-loading {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0d0d0d;
  color: #999;
  font-family: system-ui, sans-serif;
}
.app-content {
  transition: margin-left 0.18s ease;
}
.app-content.resizing {
  transition: none;
}
</style>
