<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import {
  approvePluginAction,
  dispatchPluginAction,
  type PluginActionContext,
} from "../../services/pluginUi";
import {
  pluginContextualActions,
  pluginNavigation,
} from "../../state/pluginExtensions";

const props = defineProps<{ context: PluginActionContext }>();
const error = ref("");
const router = useRouter();
const actions = computed(() =>
  pluginContextualActions.value.filter(
    (item) => item.location === props.context.kind,
  ),
);
const navigation = computed(() => {
  const location =
    props.context.kind === "game"
      ? "game.context"
      : props.context.kind === "media"
        ? "media.context"
        : undefined;
  return location
    ? pluginNavigation.value.filter((item) => item.location === location)
    : [];
});

async function run(index: number) {
  const contribution = actions.value[index];
  if (!contribution) return;
  if (!approvePluginAction(contribution.action, window.confirm)) return;
  error.value = "";
  try {
    await dispatchPluginAction(
      contribution.pluginId,
      contribution.action.id,
      {},
      props.context,
      Boolean(contribution.action.confirmation),
    );
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : "Plugin action could not be completed.";
  }
}

async function navigate(index: number) {
  const contribution = navigation.value[index];
  if (!contribution) return;
  if (contribution.action) {
    if (!approvePluginAction(contribution.action, window.confirm)) return;
    await dispatchPluginAction(
      contribution.pluginId,
      contribution.action.id,
      {},
      props.context,
      Boolean(contribution.action.confirmation),
    );
    return;
  }
  const path = contribution.routePath ?? contribution.pageId;
  if (path)
    await router.push(
      `/plugins/${encodeURIComponent(contribution.pluginId)}/${path}`,
    );
}
</script>

<template>
  <div
    v-if="actions.length || navigation.length"
    class="plugin-context-actions"
  >
    <button
      v-for="(contribution, index) in navigation"
      :key="`${contribution.pluginId}:nav:${contribution.contributionId}`"
      type="button"
      @click="navigate(index)"
    >
      {{ contribution.label }}
    </button>
    <button
      v-for="(contribution, index) in actions"
      :key="`${contribution.pluginId}:${contribution.contributionId}`"
      type="button"
      @click="run(index)"
    >
      {{ contribution.label }}
    </button>
    <p v-if="error" class="error" role="status">{{ error }}</p>
  </div>
</template>

<style scoped>
.plugin-context-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.plugin-context-actions button {
  padding: 7px 11px;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  background: #222;
  color: #fff;
  cursor: pointer;
}
.error {
  color: #f88;
}
</style>
