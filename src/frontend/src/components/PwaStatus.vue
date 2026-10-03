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
  box-sizing: border-box;
  min-height: 70px;
  padding: 1rem 1rem 1rem 112px;
  background: var(--ui-surface, #242530);
  color: var(--ui-text, #f7f7fb);
  border-bottom: 1px solid var(--ui-border, #2b2b2b);
  font-family: system-ui, sans-serif;
  font-size: 0.9rem;
}
.pwa-status:empty {
  display: none;
}
button {
  margin-left: 0.5rem;
  border: 1px solid var(--ui-accent-line, #d68a34);
  border-radius: var(--ui-radius-control, 8px);
  padding: 0.35rem 0.65rem;
  background: var(--ui-surface-2, #222);
  color: inherit;
  font: inherit;
  cursor: pointer;
}
a {
  color: var(--ui-accent, #d68a34);
}
button:focus-visible,
a:focus-visible {
  outline: 2px solid var(--ui-accent, #d68a34);
  outline-offset: 3px;
}
</style>
