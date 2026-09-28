<script setup lang="ts">
import { useRoute } from "vue-router";
import SidebarNav from "./components/SidebarNav.vue";
import TaskProgressToast from "./components/TaskProgressToast.vue";
import ShortcutsHelp from "./components/ShortcutsHelp.vue";
import CommandPalette from "./components/CommandPalette.vue";
import AppDialog from "./components/AppDialog.vue";
import { authChecked, currentUser } from "./state/auth";
import { loadSharedPreferences } from "./state/preferences";
import { watch } from "vue";
import { startupError, startupState } from "./state/startup";
import { useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
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
  <main v-else-if="startupState === 'unavailable'" class="app-loading">
    <section class="startup-error">
      <h1>Backend unavailable</h1>
      <p>
        The frontend cannot reach the backend yet. It may still be starting
        or may be temporarily unavailable.
      </p>
      <p v-if="startupError" class="startup-detail">{{ startupError }}</p>
      <button type="button" @click="router.go(0)">Retry</button>
    </section>
  </main>
  <main v-else class="app-loading">
    <p>Loading…</p>
  </main>
</template>

<style scoped>
.startup-error {
  max-width: 520px;
  padding: 32px;
  text-align: center;
  border: 1px solid #2a2a2a;
  border-radius: 14px;
  background: #1a1a1a;
}
.startup-error h1 { color: #fff; margin: 0 0 12px; }
.startup-error p { line-height: 1.5; }
.startup-detail { color: #fca5a5; font-size: 12px; word-break: break-word; }
.startup-error button {
  margin-top: 8px;
  border: 0;
  border-radius: 8px;
  padding: 10px 16px;
  background: #d68a34;
  color: #111;
  font-weight: 700;
  cursor: pointer;
}
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
