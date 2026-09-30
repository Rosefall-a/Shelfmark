<script setup lang="ts">
import { computed, onMounted, type PropType } from "vue";
import type { UiAction, UiValues } from "../../services/pluginUi";
import {
  pluginSlots,
  refreshPluginExtensions,
} from "../../state/pluginExtensions";
import PluginUiHost from "./PluginUiHost.vue";

const props = defineProps({
  slotId: { type: String, required: true },
  context: {
    type: Object as PropType<Record<string, string | number | boolean>>,
    default: () => ({}),
  },
});
const contributions = computed(() =>
  pluginSlots.value.filter((item) => item.slot === props.slotId),
);

async function save(pluginId: string, values: UiValues) {
  await fetch(`/api/plugins/${encodeURIComponent(pluginId)}/settings`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
}

async function run(pluginId: string, action: UiAction, values: UiValues) {
  await fetch(
    `/api/plugins/${encodeURIComponent(pluginId)}/actions/${encodeURIComponent(action.id)}`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    },
  );
}

onMounted(() => void refreshPluginExtensions());
</script>

<template>
  <section v-if="contributions.length" class="plugin-extension-slot">
    <PluginUiHost
      v-for="contribution in contributions"
      :key="`${contribution.pluginId}:${contribution.extensionId}`"
      :document="contribution.document"
      :page-id="contribution.page.id"
      :context="context"
      embedded
      @save="save(contribution.pluginId, $event)"
      @action="(action, values) => run(contribution.pluginId, action, values)"
    />
  </section>
</template>

<style scoped>
.plugin-extension-slot {
  display: grid;
  gap: 16px;
  margin: 20px 0;
}
</style>
