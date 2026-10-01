<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import PluginContributionHost from "../components/plugins/PluginContributionHost.vue";
import {
  fetchPluginUi,
  pluginPathForPage,
  resolvePluginPageId,
  type PluginUiDocument,
} from "../services/pluginUi";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
const document = ref<PluginUiDocument | null>(null);
const loading = ref(true);
const error = ref("");
const activePageId = ref<string | undefined>();

function requestedPluginPath(): string | undefined {
  const value = route.params.pluginPath;
  if (Array.isArray(value)) return value.join("/");
  return typeof value === "string" ? value : undefined;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    document.value = await fetchPluginUi(String(route.params.pluginId));
    activePageId.value = resolvePluginPageId(
      document.value,
      requestedPluginPath(),
    );
    if (!activePageId.value && requestedPluginPath())
      throw new Error("Plugin route not found.");
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Failed to load plugin UI.";
  } finally {
    loading.value = false;
  }
}

function navigate(pageId: string) {
  activePageId.value = pageId;
  void router.replace({
    name: "plugin-route",
    params: {
      pluginId: String(route.params.pluginId),
      pluginPath: document.value
        ? pluginPathForPage(document.value, pageId)
        : pageId,
    },
  });
}

watch(
  () => route.params.pluginPath,
  () => {
    if (!document.value) return;
    activePageId.value = resolvePluginPageId(
      document.value,
      requestedPluginPath(),
    );
  },
);
watch(
  () => route.params.pluginId,
  () => void load(),
);
onMounted(load);
</script>

<template>
  <main class="plugin-page">
    <p v-if="loading">Loading plugin…</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <PluginContributionHost
      v-else-if="document && activePageId"
      :plugin-id="document.plugin_id"
      :document="document"
      :page-id="activePageId"
      @navigate="navigate"
    />
  </main>
</template>

<style scoped>
.plugin-page {
  min-height: 100vh;
  padding: 40px;
  background: var(--ui-bg);
  color: #fff;
}
.error {
  color: #f77;
}
</style>
