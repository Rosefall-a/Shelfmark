<script setup lang="ts">
// The one sticky top bar every page in the Media area and the Calendar and
// Statistics pages share: fixed minimum height, padding, border and the
// account chip live here once, so nothing shifts when you move between
// pages. Callers fill the left side (default slot) and, optionally, the
// right-hand `actions` slot. The chip is pinned to the bar's right edge and
// the bar reserves room for it, so it stays put even when the left side
// wraps onto more lines on a narrow window.
import AccountChip from "./AccountChip.vue";
</script>

<template>
  <div class="media-topbar">
    <div class="topbar-left"><slot /></div>
    <div v-if="$slots.actions" class="media-topbar-actions">
      <slot name="actions" />
    </div>
    <AccountChip />
  </div>
</template>

<style scoped>
.media-topbar {
  position: sticky;
  top: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  gap: 16px;
  box-sizing: border-box;
  min-height: 68px;
  padding: 10px 244px 10px 64px;
  background: rgba(13, 13, 13, 0.94);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid #202020;
}
.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  min-width: 0;
}
.media-topbar-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
  gap: 10px;
}
@media (max-width: 720px) {
  .media-topbar {
    padding-left: 60px;
  }
}
@media (max-width: 520px) {
  .media-topbar {
    padding-right: 116px;
  }
}
</style>
