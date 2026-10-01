<script setup lang="ts">
import { computed, onErrorCaptured, ref, watch } from "vue";
import type {
  PluginActionContext,
  PluginUiDocument,
  UiAction,
  UiValues,
} from "../../services/pluginUi";
import { dispatchPluginAction } from "../../services/pluginUi";
import { nativePluginComponents } from "../../state/pluginNative";
import PluginUiHost from "./PluginUiHost.vue";

const props = defineProps<{
  pluginId: string;
  document: PluginUiDocument;
  pageId: string;
  context?: Record<string, string | number | boolean>;
  embedded?: boolean;
  actionContext?: PluginActionContext;
}>();
const emit = defineEmits<{ navigate: [pageId: string] }>();

const failed = ref(false);
const component = computed(
  () => nativePluginComponents.value[`${props.pluginId}:${props.pageId}`],
);

watch(
  () => `${props.pluginId}:${props.pageId}:${String(component.value)}`,
  () => (failed.value = false),
);

onErrorCaptured(() => {
  failed.value = true;
  return false;
});

async function save(values: UiValues) {
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(props.pluginId)}/settings`,
    {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    },
  );
  if (!response.ok) throw new Error("Plugin settings could not be saved.");
}

async function run(action: UiAction, values: UiValues) {
  await dispatchPluginAction(
    props.pluginId,
    action.id,
    values,
    props.actionContext,
  );
}

const nativeHost = computed(() => ({
  runAction: (actionId: string, values: Record<string, unknown> = {}) =>
    dispatchPluginAction(props.pluginId, actionId, values, props.actionContext),
}));
</script>

<template>
  <p v-if="failed" class="plugin-failure" role="status">
    This plugin contribution failed and was removed from the page.
  </p>
  <component
    :is="component"
    v-else-if="component"
    :plugin-id="pluginId"
    :page-id="pageId"
    :context="context ?? {}"
    :host="nativeHost"
  />
  <PluginUiHost
    v-else
    :document="document"
    :page-id="pageId"
    :context="context"
    :embedded="embedded"
    @save="save"
    @action="run"
    @navigate="emit('navigate', $event)"
  />
</template>

<style scoped>
.plugin-failure {
  padding: 12px;
  border: 1px solid rgba(255, 122, 122, 0.35);
  border-radius: 8px;
  color: #ffb0b0;
}
</style>
