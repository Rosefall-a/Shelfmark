<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";
import SidebarNav from "./components/SidebarNav.vue";
import TaskProgressToast from "./components/TaskProgressToast.vue";
import ShortcutsHelp from "./components/ShortcutsHelp.vue";
import CommandPalette from "./components/CommandPalette.vue";
import AppDialog from "./components/AppDialog.vue";
import { authChecked, currentUser } from "./state/auth";
import { loadSharedPreferences } from "./state/preferences";
import { onUnmounted, watch } from "vue";
import {
  clearPluginExtensions,
  refreshPluginExtensions,
} from "./state/pluginExtensions";
import PluginExtensionSlot from "./components/plugins/PluginExtensionSlot.vue";
import PluginOverlayHost from "./components/plugins/PluginOverlayHost.vue";
import { fetchCurrentUser } from "./services/auth";
import PwaStatus from "./components/PwaStatus.vue";

const route = useRoute();
const router = useRouter();
let pluginRefreshTimer: ReturnType<typeof setInterval> | undefined;
watch(
  () => currentUser.value?.id,
  (id) => {
    clearInterval(pluginRefreshTimer);
    clearPluginExtensions();
    if (id) {
      void refreshPluginExtensions();
      pluginRefreshTimer = setInterval(async () => {
        try {
          const user = await fetchCurrentUser();
          if (!user) {
            currentUser.value = null;
            await router.replace("/login");
            return;
          }
          await refreshPluginExtensions();
        } catch {
          // Preserve the current screen during transient connectivity failures.
        }
      }, 5000);
    }
  },
  { immediate: true },
);
onUnmounted(() => {
  clearInterval(pluginRefreshTimer);
  clearPluginExtensions();
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
  <PwaStatus />
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
    <PluginExtensionSlot
      v-if="currentUser"
      slot-id="app.global"
      :context="{ host_page: route.path }"
    />
    <PluginOverlayHost v-if="currentUser" />
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
