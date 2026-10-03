<script setup lang="ts">
import { computed } from "vue";
import { currentUser } from "../state/auth";
import { installPwa, pwaState, reloadPwa } from "../services/pwa";

const standalone =
  window.matchMedia("(display-mode: standalone)").matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true ||
  new URL(window.location.href).searchParams.get("pwa") === "1";
const ios =
  /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const visible = computed(
  () =>
    standalone ||
    (!!currentUser.value &&
      pwaState.enabled &&
      (pwaState.installable ||
        ios ||
        !!pwaState.message ||
        pwaState.updatePending)),
);
</script>

<template>
  <aside
    v-if="visible"
    class="pwa-status"
    aria-label="Installed application status"
    aria-live="polite"
  >
    <span v-if="!pwaState.online">Waiting for internet.</span>
    <span v-else-if="pwaState.available && !pwaState.enabled">
      PWA plugin is not enabled. This shortcut opens the ordinary website.
      <RouterLink to="/settings?section=plugins"
        >Open plugin settings</RouterLink
      >
    </span>
    <span v-else-if="pwaState.message">{{ pwaState.message }}</span>
    <span v-if="pwaState.updatePending">
      App updated. Reload after saving your changes.
      <button type="button" @click="reloadPwa">Reload</button>
    </span>
    <button
      v-if="pwaState.installable && !standalone"
      type="button"
      @click="installPwa"
    >
      Install Unnamed Tracking
    </button>
    <span v-else-if="ios && pwaState.enabled && !standalone"
      >In Safari, use Share → Add to Home Screen.</span
    >
  </aside>
</template>

<style scoped>
.pwa-status {
  padding: 0.5rem 1rem;
  background: var(--panel-bg, #242530);
  color: var(--text-color, #f7f7fb);
}
.pwa-status:empty {
  display: none;
}
button {
  margin-left: 0.5rem;
}
</style>
