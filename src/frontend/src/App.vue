<script setup lang="ts">
import { useRoute } from "vue-router";
import SidebarNav from "./components/SidebarNav.vue";
import TaskProgressToast from "./components/TaskProgressToast.vue";
import ShortcutsHelp from "./components/ShortcutsHelp.vue";
import CommandPalette from "./components/CommandPalette.vue";
import AppDialog from "./components/AppDialog.vue";
import { authChecked, currentUser } from "./state/auth";
import { loadSharedPreferences } from "./state/preferences";
import { onBeforeUnmount, onMounted, watch } from "vue";
import { fetchCurrentUser } from "./services/auth";
import router from "./router";

const route = useRoute();
let authPoll: number | undefined;

onMounted(() => {
  authPoll = window.setInterval(async () => {
    if (!currentUser.value || route.path === "/login" || route.path === "/setup") return;
    try {
      const user = await fetchCurrentUser();
      if (!user && route.path !== "/login") {
        currentUser.value = null;
        await router.replace("/login");
      } else if (user) {
        currentUser.value = user;
      }
    } catch {
      // Keep the existing page during transient connectivity failures.
    }
  }, 5000);
});

onBeforeUnmount(() => {
  if (authPoll !== undefined) window.clearInterval(authPoll);
});
// preferences are per user, so load them once someone is signed in
watch(
  () => currentUser.value?.id,
  (id) => {
    if (id) loadSharedPreferences();
  },
  { immediate: true },
);
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
    <SidebarNav
      v-if="
        route.path !== '/login' &&
        route.path !== '/setup' &&
        route.path !== '/login/oidcstart'
      "
    />
    <!-- Library, calendar and list pages stay mounted when you leave them, so
         switching tabs is instant instead of reloading from empty. Detail
         pages are deliberately not kept: they must reload per title. -->
    <router-view v-slot="{ Component }">
      <KeepAlive :include="KEPT_ALIVE" :max="8">
        <component :is="Component" />
      </KeepAlive>
    </router-view>
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
  background: #121212;
  color: #999;
  font-family: system-ui, sans-serif;
}
</style>
