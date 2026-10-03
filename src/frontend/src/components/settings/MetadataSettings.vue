<script setup lang="ts">
import { ref } from "vue";
import SettingsTabs from "./SettingsTabs.vue";
import MetadataSourcesSection from "./MetadataSourcesSection.vue";
import ScanSettingsSection from "./ScanSettingsSection.vue";
import MediaRefreshSection from "./MediaRefreshSection.vue";

const props = defineProps<{ initialTab?: string }>();

const TABS = [
  { id: "sources", label: "Sources & API keys" },
  { id: "scan", label: "Scan & providers" },
  { id: "refresh", label: "Refresh media" },
];
const tab = ref(
  TABS.some((t) => t.id === props.initialTab) ? props.initialTab! : "sources",
);
</script>

<template>
  <div>
    <SettingsTabs v-model="tab" :tabs="TABS" />
    <MetadataSourcesSection v-if="tab === 'sources'" />
    <ScanSettingsSection v-else-if="tab === 'scan'" />
    <MediaRefreshSection v-else />
  </div>
</template>
