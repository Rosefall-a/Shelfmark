<script setup lang="ts">
import { computed } from "vue";
import { saveState } from "../../state/saveStatus";

const label = computed(() => {
  if (saveState.value === "saving") return "Saving…";
  if (saveState.value === "saved") return "All changes saved";
  if (saveState.value === "error") return "Couldn't save. Try again";
  return "";
});
</script>

<template>
  <div
    v-if="label"
    class="save-status"
    :class="saveState"
    role="status"
    aria-live="polite"
  >
    <span class="dot"></span>{{ label }}
  </div>
</template>

<style scoped>
.save-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid #2a2a2a;
  color: #aaa;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #888;
}
.save-status.saving .dot {
  background: #d68a34;
  animation: pulse 1s ease-in-out infinite;
}
.save-status.saved {
  color: #86efac;
}
.save-status.saved .dot {
  background: #4ade80;
}
.save-status.error {
  color: #fca5a5;
  border-color: rgba(220, 38, 38, 0.35);
}
.save-status.error .dot {
  background: #f87171;
}
@keyframes pulse {
  50% {
    opacity: 0.35;
  }
}
@media (prefers-reduced-motion: reduce) {
  .save-status.saving .dot {
    animation: none;
  }
}
</style>
