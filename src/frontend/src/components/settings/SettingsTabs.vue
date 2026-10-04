<script setup lang="ts">
export interface SettingsTab {
  id: string;
  label: string;
}

defineProps<{ tabs: SettingsTab[]; modelValue: string }>();
defineEmits<{ "update:modelValue": [id: string] }>();
</script>

<template>
  <div class="settings-tabs" role="tablist">
    <button
      v-for="t in tabs"
      :key="t.id"
      type="button"
      role="tab"
      class="settings-tab"
      :class="{ active: modelValue === t.id }"
      :aria-selected="modelValue === t.id"
      @click="$emit('update:modelValue', t.id)"
    >
      {{ t.label }}
    </button>
  </div>
</template>

<style scoped>
.settings-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 0 0 22px;
  border-bottom: 1px solid #2a2a2a;
}
.settings-tab {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  color: #999;
  font: inherit;
  font-size: 0.9rem;
  font-weight: 600;
  padding: 10px 14px;
  cursor: pointer;
  transition:
    color 0.15s ease,
    border-color 0.15s ease;
}
.settings-tab:hover {
  color: #fff;
}
.settings-tab.active {
  color: #d68a34;
  border-bottom-color: #d68a34;
}
</style>
