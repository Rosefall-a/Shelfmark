<script setup lang="ts">
import { ref } from "vue";
import SettingsTabs from "./SettingsTabs.vue";
import AdminSection from "./AdminSection.vue";
import OidcSettingsSection from "./OidcSettingsSection.vue";
import ServerIntegrationsSection from "./ServerIntegrationsSection.vue";
import LimitsSection from "./LimitsSection.vue";
import DevToolsSection from "./DevToolsSection.vue";

const props = defineProps<{ initialTab?: string }>();

// Admin-only server settings in one place. Tasks and Logs keep their own
// entries in the sidebar.
const TABS = [
  { id: "users", label: "Users" },
  { id: "sso", label: "Single sign-on" },
  { id: "integrations", label: "Integrations" },
  { id: "limits", label: "Limits" },
  { id: "dev-tools", label: "Dev Tools" },
];
const tab = ref(
  TABS.some((t) => t.id === props.initialTab) ? props.initialTab! : "users",
);
</script>

<template>
  <div>
    <SettingsTabs v-model="tab" :tabs="TABS" />
    <AdminSection v-if="tab === 'users'" />
    <OidcSettingsSection v-else-if="tab === 'sso'" />
    <ServerIntegrationsSection v-else-if="tab === 'integrations'" />
    <LimitsSection v-else-if="tab === 'limits'" />
    <DevToolsSection v-else />
  </div>
</template>
