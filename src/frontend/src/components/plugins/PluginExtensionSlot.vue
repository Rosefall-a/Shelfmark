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
const matchingContributions = computed(() =>
  pluginSlots.value.filter((item) => item.slot === props.slotId),
);
const contributions = computed(() =>
  props.slotId.endsWith(".replace")
    ? matchingContributions.value.slice(0, 1)
    : matchingContributions.value,
);
const hasReplacementConflict = computed(
  () =>
    props.slotId.endsWith(".replace") && matchingContributions.value.length > 1,
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
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(pluginId)}/actions/${encodeURIComponent(action.id)}`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    },
  );
  if (!response.ok) throw new Error("Plugin action could not be completed.");
  const result = (await response.json()) as { redirect_url?: unknown };
  if (
    action.external_navigation &&
    typeof result.redirect_url === "string" &&
    /^https?:\/\//.test(result.redirect_url)
  ) {
    window.location.assign(result.redirect_url);
  }
}

onMounted(() => void refreshPluginExtensions());
</script>

<template>
  <section v-if="contributions.length" class="plugin-extension-slot">
    <p v-if="hasReplacementConflict" class="plugin-conflict" role="status">
      Multiple plugins requested this page replacement. The first configured
      contribution is active.
    </p>
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
.plugin-conflict {
  margin: 0;
  color: #d8a15e;
  font-size: 0.85rem;
}
</style>
