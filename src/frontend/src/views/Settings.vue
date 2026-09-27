<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { currentUser } from "../state/auth";
import SettingsNav from "../components/settings/SettingsNav.vue";
import type { SettingsGroup } from "../components/settings/SettingsNav.vue";
import ProfileSection from "../components/settings/ProfileSection.vue";
import InterfaceSection from "../components/settings/InterfaceSection.vue";
import AppearanceSection from "../components/settings/AppearanceSection.vue";
import UploadSection from "../components/settings/UploadSection.vue";
import LibraryManagementSection from "../components/settings/LibraryManagementSection.vue";
import MediaTrashSection from "../components/settings/MediaTrashSection.vue";
import ScanSettingsSection from "../components/settings/ScanSettingsSection.vue";
import MetadataSourcesSection from "../components/settings/MetadataSourcesSection.vue";
import MediaRefreshSection from "../components/settings/MediaRefreshSection.vue";
import TasksSection from "../components/settings/TasksSection.vue";
import AdminSection from "../components/settings/AdminSection.vue";
import StatsSection from "../components/settings/StatsSection.vue";
import ExportImportSection from "../components/settings/ExportImportSection.vue";
import CalendarNotificationsSection from "../components/settings/CalendarNotificationsSection.vue";
import AniListImportSection from "../components/settings/AniListImportSection.vue";
import MediaPreferencesSection from "../components/settings/MediaPreferencesSection.vue";
import ComingSoonSection from "../components/settings/ComingSoonSection.vue";
import ApiKeysSection from "../components/settings/ApiKeysSection.vue";
import ServerIntegrationsSection from "../components/settings/ServerIntegrationsSection.vue";
import OidcSettingsSection from "../components/settings/OidcSettingsSection.vue";

const router = useRouter();
const route = useRoute();
function goBack() { if (window.history.length > 1) router.back(); else router.push("/"); }

const groups = computed<SettingsGroup[]>(() => {
  const result: SettingsGroup[] = [
    { label: "Account", sections: [
      { id: "profile", label: "Profile" }, { id: "interface", label: "User Interface" },
      { id: "appearance", label: "Appearance" }, { id: "api-keys", label: "API Keys" },
      { id: "calendar-notifications", label: "Calendar and Notifications" }, { id: "anilist-import", label: "AniList Import" },
    ]},
    { label: "Library", sections: [
      { id: "upload", label: "Upload" }, { id: "library", label: "Library Management" },
      { id: "media-prefs", label: "Media Preferences" }, { id: "media-trash", label: "Media Trash" },
    ]},
    { label: "Metadata", sections: [
      { id: "scan", label: "Scan Settings" }, { id: "sources", label: "Metadata/API" },
      { id: "media-refresh", label: "Refresh Media" }, { id: "export", label: "Export / Import" },
    ]},
  ];
  const systemSections = [
    ...(currentUser.value?.is_admin ? [{ id: "oidc", label: "OIDC / SSO" }] : []),
    ...(currentUser.value?.is_admin ? [{ id: "server-integrations", label: "Server Integrations" }] : []),
    ...(currentUser.value?.is_admin ? [{ id: "users", label: "Users" }] : []),
    { id: "stats", label: "Server Stats" },
    ...(currentUser.value?.is_admin ? [{ id: "tasks", label: "Tasks", comingSoon: true }] : []),
    ...(currentUser.value?.is_admin ? [{ id: "logs", label: "Logs", comingSoon: true }] : []),
  ];
  result.push({ label: "System", sections: systemSections });
  return result;
});
const activeSection = ref((route.query.section as string) || "profile");
watch(() => route.query.section, (section) => { const next = typeof section === "string" && section ? section : "profile"; if (activeSection.value !== next) activeSection.value = next; });
watch(activeSection, (section) => { const current = typeof route.query.section === "string" ? route.query.section : "profile"; if (current === section) return; void router.replace({ query: { ...route.query, section } }); });
const card = ref<HTMLElement | null>(null);
watch(activeSection, async () => { if (!window.matchMedia("(max-width: 760px)").matches) return; await nextTick(); card.value?.scrollIntoView({ behavior: "smooth", block: "start" }); });
</script>

<template>
  <main class="settings-page">
    <button type="button" class="back-arrow-button" title="Back" @click="goBack">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5" /><path d="M12 19l-7-7 7-7" /></svg>
    </button>
    <div class="settings-layout">
      <h1>Settings</h1>
      <div class="settings-body">
        <SettingsNav v-model:active-section="activeSection" :groups="groups" />
        <div ref="card" class="settings-card">
          <ProfileSection v-if="activeSection === 'profile'" />
          <InterfaceSection v-else-if="activeSection === 'interface'" />
          <AppearanceSection v-else-if="activeSection === 'appearance'" />
          <CalendarNotificationsSection v-else-if="activeSection === 'calendar-notifications'" />
          <AniListImportSection v-else-if="activeSection === 'anilist-import'" />
          <ApiKeysSection v-else-if="activeSection === 'api-keys'" />
          <UploadSection v-else-if="activeSection === 'upload'" />
          <LibraryManagementSection v-else-if="activeSection === 'library'" />
          <MediaPreferencesSection v-else-if="activeSection === 'media-prefs'" />
          <MediaTrashSection v-else-if="activeSection === 'media-trash'" />
          <ScanSettingsSection v-else-if="activeSection === 'scan'" />
          <MetadataSourcesSection v-else-if="activeSection === 'sources'" />
          <MediaRefreshSection v-else-if="activeSection === 'media-refresh'" />
          <OidcSettingsSection v-else-if="activeSection === 'oidc' && currentUser?.is_admin" />
          <ServerIntegrationsSection v-else-if="activeSection === 'server-integrations' && currentUser?.is_admin" />
          <AdminSection v-else-if="activeSection === 'users' && currentUser?.is_admin" />
          <StatsSection v-else-if="activeSection === 'stats'" />
          <ExportImportSection v-else-if="activeSection === 'export'" />
          <TasksSection v-else-if="activeSection === 'tasks' && currentUser?.is_admin" />
          <ComingSoonSection v-else-if="activeSection === 'logs' && currentUser?.is_admin" title="Logs" description="An audit trail of edits made across the library, including changes made by other users." :planned-features="['Who changed what, and when', 'Filter by user, game, or field', 'Restore a previous value']" />
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.settings-page { position: relative; min-height: 100vh; padding: 84px 40px 40px; background: var(--ui-bg); font-family: system-ui, sans-serif; }
.back-arrow-button { position: fixed; top: 16px; left: 62px; width: 38px; height: 38px; border-radius: 50%; border: 1px solid rgba(255,255,255,.14); background: rgba(20,20,20,.55); backdrop-filter: blur(6px); color: #fff; display:flex; align-items:center; justify-content:center; cursor:pointer; z-index:100; }
.settings-layout { width: 100%; color: #fff; }
.settings-layout h1 { margin: 0 0 24px; font-size: 1.5rem; }
.settings-body { display:flex; gap:32px; align-items:flex-start; }
.settings-card { flex:1; min-width:0; scroll-margin-top:64px; background:#1a1a1a; border:1px solid #2a2a2a; border-radius:14px; padding:32px; }
@media (max-width:760px) { .settings-body { flex-direction:column; } .settings-card { width:100%; padding:20px; } }
</style>
