<script setup lang="ts">
import { computed, onMounted, type PropType } from "vue";
import type { PluginActionContext } from "../../services/pluginUi";
import {
  pluginSlots,
  refreshPluginExtensions,
} from "../../state/pluginExtensions";
import PluginContributionHost from "./PluginContributionHost.vue";
import { currentUser } from "../../state/auth";

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
const actionContext = computed<PluginActionContext | undefined>(() => {
  const resourceId =
    props.context.game_id ??
    props.context.media_id ??
    props.context.document_id;
  if (resourceId === undefined) return undefined;
  if (props.slotId.startsWith("game.documents"))
    return {
      kind: "documents",
      resource_id: String(resourceId),
      resource_type: "game",
    };
  if (props.slotId.startsWith("game."))
    return { kind: "game", resource_id: String(resourceId) };
  if (props.slotId.startsWith("media."))
    return {
      kind: "media",
      resource_id: String(resourceId),
      resource_type: String(props.context.media_type ?? "media"),
    };
  return undefined;
});

onMounted(() => void refreshPluginExtensions());
</script>

<template>
  <section v-if="contributions.length" class="plugin-extension-slot">
    <p
      v-if="hasReplacementConflict && currentUser?.is_admin"
      class="plugin-conflict"
      role="status"
    >
      Multiple plugins requested this page replacement. The deterministic order
      selected {{ contributions[0]?.pluginId }}.
    </p>
    <PluginContributionHost
      v-for="contribution in contributions"
      :key="`${contribution.pluginId}:${contribution.extensionId}`"
      :document="contribution.document"
      :plugin-id="contribution.pluginId"
      :page-id="contribution.page.id"
      :context="context"
      :action-context="actionContext"
      embedded
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
