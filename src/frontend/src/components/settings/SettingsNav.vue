<script setup lang="ts">
export interface SettingsSection {
  id: string;
  label: string;
  comingSoon?: boolean;
}

export interface SettingsGroup {
  label: string;
  sections: SettingsSection[];
}

defineProps<{
  groups: SettingsGroup[];
  activeSection: string;
}>();

const emit = defineEmits<{
  "update:activeSection": [id: string];
}>();

const ICON_PATHS: Record<string, string> = {
  profile: "M20 21a8 8 0 0 0-16 0 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
  interface: "M3 4h18v12H3z M8 20h8 M12 16v4",
  upload: "M12 16V4 M6 10l6-6 6 6 M4 20h16",
  library:
    "M4 19V5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z M9 3v6h6",
  scan: "M3 7V4a1 1 0 0 1 1-1h3 M17 3h3a1 1 0 0 1 1 1v3 M21 17v3a1 1 0 0 1-1 1h-3 M7 21H4a1 1 0 0 1-1-1v-3",
  sources:
    "M12 3C7 3 3 5 3 8s4 5 9 5 9-2 9-5-4-5-9-5Z M3 8v8c0 3 4 5 9 5s9-2 9-5V8",
  export: "M12 3v12 M7 8l5-5 5 5 M5 21h14",
  oidc: "M12 2a5 5 0 0 1 5 5c0 2.2-1.4 4.1-3.4 4.7L15 15h4a2 2 0 0 1 2 2v5H3v-5a2 2 0 0 1 2-2h4l1.4-3.3A5 5 0 0 1 7 7a5 5 0 0 1 5-5Z",
  "server-integrations": "M4 7h16 M4 12h16 M4 17h16 M8 7v10 M16 7v10",
  "password-policy": "M12 2v20 M2 12h20",
  users:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M22 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75",
  stats: "M4 20V10 M11 20V4 M18 20v-7",
  tasks:
    "M9 11l3 3 8-8 M21 12v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h11",
  logs: "M4 6h16 M4 12h16 M4 18h10",
};
const DEFAULT_ICON = "M12 8v4l3 3 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z";

function iconPath(id: string): string {
  return ICON_PATHS[id] ?? DEFAULT_ICON;
}
</script>

<template>
  <nav class="settings-nav">
    <div v-for="group in groups" :key="group.label" class="settings-nav-group">
      <span class="settings-nav-group-label">{{ group.label }}</span>
      <button
        v-for="section in group.sections"
        :key="section.id"
        type="button"
        class="settings-nav-item"
        :class="{ active: activeSection === section.id }"
        @click="emit('update:activeSection', section.id)"
      >
        <span class="settings-nav-item-main">
          <svg
            class="nav-icon"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path :d="iconPath(section.id)" />
          </svg>
          <span>{{ section.label }}</span>
        </span>
        <span v-if="section.comingSoon" class="soon-badge">soon</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.settings-nav {
  display: flex;
  flex-direction: column;
  gap: 18px;
  width: 220px;
  flex-shrink: 0;
}
@media (max-width: 760px) {
  .settings-nav {
    width: 100%;
  }
}
.settings-nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.settings-nav-group-label {
  color: #777;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0 12px 6px;
}
.settings-nav-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  border: none;
  background: none;
  color: #ccc;
  text-align: left;
  font-size: 14px;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.settings-nav-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.nav-icon {
  flex-shrink: 0;
  opacity: 0.8;
}
.settings-nav-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}
.settings-nav-item.active {
  background: rgba(214, 138, 52, 0.14);
  color: #d68a34;
}
.soon-badge {
  font-size: 10px;
  color: #777;
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 6px;
  border-radius: 999px;
  flex-shrink: 0;
}
</style>
