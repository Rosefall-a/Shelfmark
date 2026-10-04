<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { currentUser } from "../state/auth";
import { startTrackingSaves, stopTrackingSaves } from "../state/saveStatus";
import SettingsNav from "../components/settings/SettingsNav.vue";
import type { SettingsGroup } from "../components/settings/SettingsNav.vue";
import SaveStatus from "../components/settings/SaveStatus.vue";
import ProfileSection from "../components/settings/ProfileSection.vue";
import InterfaceSection from "../components/settings/InterfaceSection.vue";
import AppearanceSection from "../components/settings/AppearanceSection.vue";
import UploadSection from "../components/settings/UploadSection.vue";
import LibrarySettings from "../components/settings/LibrarySettings.vue";
import MetadataSettings from "../components/settings/MetadataSettings.vue";
import AdminSettings from "../components/settings/AdminSettings.vue";
import TasksSection from "../components/settings/TasksSection.vue";
import ComingSoonSection from "../components/settings/ComingSoonSection.vue";
import StatsSection from "../components/settings/StatsSection.vue";
import ExportImportSection from "../components/settings/ExportImportSection.vue";
import CalendarNotificationsSection from "../components/settings/CalendarNotificationsSection.vue";
import KeyboardShortcutsSection from "../components/settings/KeyboardShortcutsSection.vue";
import ConnectionsSection from "../components/settings/ConnectionsSection.vue";
import AniListImportSection from "../components/settings/AniListImportSection.vue";
import ApiKeysSection from "../components/settings/ApiKeysSection.vue";
import PasswordPolicySection from "../components/settings/PasswordPolicySection.vue";
import AccountChip from "../components/AccountChip.vue";
import BackButton from "../components/BackButton.vue";

const router = useRouter();
const route = useRoute();
function goBack() {
  if (window.history.length > 1) router.back();
  else router.push("/");
}

onMounted(startTrackingSaves);
onBeforeUnmount(stopTrackingSaves);

const groups = computed<SettingsGroup[]>(() => {
  const result: SettingsGroup[] = [
    {
      label: "Account",
      sections: [
        { id: "profile", label: "Profile" },
        { id: "connections", label: "Connections" },
        { id: "api-keys", label: "API Keys" },
      ],
    },
    {
      label: "Preferences",
      sections: [
        { id: "interface", label: "User Interface" },
        { id: "appearance", label: "Appearance" },
        { id: "notifications", label: "Notifications" },
        { id: "calendar", label: "Calendar" },
        { id: "shortcuts", label: "Keyboard Shortcuts" },
      ],
    },
    {
      label: "Library",
      sections: [
        { id: "upload", label: "Upload" },
        { id: "library", label: "Library" },
        { id: "metadata", label: "Metadata" },
        { id: "export", label: "Export / Import" },
      ],
    },
  ];
  result.push({
    label: "System",
    sections: [
      { id: "stats", label: "Server Stats" },
      ...(currentUser.value?.is_admin
        ? [
            { id: "admin", label: "Administration" },
            { id: "tasks", label: "Tasks" },
            { id: "logs", label: "Logs", comingSoon: true },
          ]
        : []),
    ],
  });
  return result;
});

// Sections that used to be their own entries and now live inside a
// merged page as a tab, so old links (command palette, bookmarks) still
// land in the right place.
const SECTION_ALIASES: Record<string, { section: string; tab?: string }> = {
  "calendar-notifications": { section: "notifications" },
  "media-prefs": { section: "library", tab: "preferences" },
  "media-trash": { section: "library", tab: "trash" },
  sources: { section: "metadata", tab: "sources" },
  scan: { section: "metadata", tab: "scan" },
  "media-refresh": { section: "metadata", tab: "refresh" },
  users: { section: "admin", tab: "users" },
  oidc: { section: "admin", tab: "sso" },
  "server-integrations": { section: "admin", tab: "integrations" },
};
function resolveSection(id: string | undefined): {
  section: string;
  tab?: string;
} {
  const raw = id || "profile";
  return SECTION_ALIASES[raw] ?? { section: raw };
}
const initial = resolveSection(route.query.section as string | undefined);
const activeSection = ref(initial.section);
const initialTab = ref<string | undefined>(
  (route.query.tab as string | undefined) ?? initial.tab,
);
function openSection(id: string) {
  const r = resolveSection(id);
  initialTab.value = r.tab;
  activeSection.value = r.section;
}

watch(
  () => route.query.section,
  (section) => {
    const next = typeof section === "string" && section ? section : "profile";
    if (activeSection.value !== next) activeSection.value = next;
  },
);

watch(activeSection, (section) => {
  const current =
    typeof route.query.section === "string" ? route.query.section : "profile";
  if (current === section) return;
  void router.replace({ query: { ...route.query, section } });
});

const card = ref<HTMLElement | null>(null);
watch(activeSection, async () => {
  if (!window.matchMedia("(max-width: 760px)").matches) return;
  await nextTick();
  card.value?.scrollIntoView({ behavior: "smooth", block: "start" });
});
</script>

<template>
  <main class="settings-page">
    <BackButton fixed @click="goBack" />
    <AccountChip fixed />
    <div class="settings-layout">
      <div class="settings-head">
        <h1>Settings</h1>
        <SaveStatus />
      </div>
      <div class="settings-body">
        <SettingsNav
          :active-section="activeSection"
          :groups="groups"
          @update:active-section="openSection"
        />
        <div ref="card" class="settings-card">
          <ProfileSection v-if="activeSection === 'profile'" />
          <InterfaceSection v-else-if="activeSection === 'interface'" />
          <AppearanceSection v-else-if="activeSection === 'appearance'" />
          <CalendarNotificationsSection
            v-else-if="activeSection === 'notifications'"
            part="notifications"
          />
          <CalendarNotificationsSection
            v-else-if="activeSection === 'calendar'"
            part="calendar"
          />
          <KeyboardShortcutsSection v-else-if="activeSection === 'shortcuts'" />
          <ConnectionsSection
            v-else-if="activeSection === 'connections'"
            @navigate="openSection"
          />
          <ApiKeysSection v-else-if="activeSection === 'api-keys'" />
          <UploadSection v-else-if="activeSection === 'upload'" />
          <LibrarySettings
            v-else-if="activeSection === 'library'"
            :key="'library' + initialTab"
            :initial-tab="initialTab"
          />
          <PasswordPolicySection v-else-if="activeSection === 'password-policy'" />
          <StatsSection v-else-if="activeSection === 'stats'" />
          <template v-else-if="activeSection === 'export'">
            <ExportImportSection />
            <AniListImportSection />
          </template>
          <MetadataSettings
            v-else-if="activeSection === 'metadata'"
            :key="'metadata' + initialTab"
            :initial-tab="initialTab"
          />
          <AdminSettings
            v-else-if="activeSection === 'admin' && currentUser?.is_admin"
            :key="'admin' + initialTab"
            :initial-tab="initialTab"
          />
          <TasksSection
            v-else-if="activeSection === 'tasks' && currentUser?.is_admin"
          />
          <ComingSoonSection
            v-else-if="activeSection === 'logs' && currentUser?.is_admin"
            title="Logs"
            description="An audit trail of edits made across the library, including changes made by other users."
            :planned-features="[
              'Who changed what, and when',
              'Filter by user, game, or field',
              'Restore a previous value',
            ]"
          />
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.settings-page {
  position: relative;
  min-height: 100vh;
  padding: 84px 40px 40px;
  background: var(--ui-bg);
  font-family: system-ui, sans-serif;
}
.settings-layout {
  width: 100%;
  color: #fff;
}
.settings-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 0 0 24px;
}
.settings-layout h1 {
  margin: 0;
  font-size: 1.7rem;
  font-weight: 800;
}
.settings-body {
  display: flex;
  gap: 32px;
  align-items: flex-start;
}
.settings-card {
  flex: 1;
  min-width: 0;
  scroll-margin-top: 64px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 14px;
  padding: 32px;
}
@media (max-width: 760px) {
  .settings-body {
    flex-direction: column;
  }
  .settings-card {
    width: 100%;
    padding: 20px;
  }
}
</style>
