<script setup lang="ts">
import { computed } from "vue";
import type { PluginInstallPermission } from "../../services/plugins";
const props = defineProps<{ permissions: PluginInstallPermission[] }>();
const counts = computed(() =>
  ["critical", "high", "medium", "low"].map((risk) => ({
    risk,
    count: props.permissions.filter((item) => item.risk === risk).length,
  })),
);
</script>
<template>
  <div class="risk-summary" aria-label="Requested permission risks">
    <strong>{{ permissions.length }} scopes</strong>
    <span
      v-for="item in counts"
      :key="item.risk"
      class="risk-bubble"
      :class="item.risk"
    >
      {{ item.count }}
      {{
        item.risk === "high"
          ? "High Risk"
          : item.risk === "medium"
            ? "Medium Risk"
            : item.risk === "low"
              ? "Low Risk"
              : "Critical"
      }}
    </span>
  </div>
</template>
<style scoped>
.risk-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 12px 0;
}
.risk-bubble {
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 0.85rem;
}
.critical {
  color: #ff737b;
  background: #491c29;
}
.high {
  color: #ffb35c;
  background: #49321d;
}
.medium {
  color: #f2da6d;
  background: #3c381c;
}
.low {
  color: #79dca5;
  background: #1b3e2a;
}
</style>
