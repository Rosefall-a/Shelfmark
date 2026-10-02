<script setup lang="ts">
// Renders the avatar (with its chevron badge) itself and wraps whatever
// else is passed into the default slot (a name label, usually) into a
// real dropdown — same Teleport-to-body pattern as NotificationBell.vue
// so the panel escapes each page's own clipping. The avatar is owned
// here, not slotted, on purpose: the badge is positioned relative to
// the avatar alone, and that only stays correct if this component
// controls the avatar's markup instead of trusting a slot's DOM order.
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";
import { openTopbarPopover } from "../state/topbarPopover";
import { currentUser } from "../state/auth";
import { logout } from "../services/auth";

defineProps<{ initials: string }>();

const router = useRouter();
const root = ref<HTMLElement | null>(null);
const triggerBtn = ref<HTMLElement | null>(null);
const open = ref(false);

const PANEL_WIDTH = 172;
const panelStyle = ref<{ top: string; left: string }>({
  top: "0px",
  left: "0px",
});
// Anchored the same way NotificationBell's panel is: pinned to the
// trigger's own right edge, never drifting further than the viewport
// allows, so it reads as tied to the avatar instead of a loose box.
const caretOffset = ref(20);
function positionPanel() {
  const rect = triggerBtn.value?.getBoundingClientRect();
  if (!rect) return;
  const left = Math.max(
    16,
    Math.min(rect.right - PANEL_WIDTH, window.innerWidth - PANEL_WIDTH - 16),
  );
  panelStyle.value = {
    top: `${rect.bottom + 10}px`,
    left: `${left}px`,
  };
  // aimed at the avatar's centre (32px avatar, 11px caret)
  caretOffset.value = Math.max(14, rect.right - left - 21.5);
}

function toggle() {
  if (open.value) {
    open.value = false;
    return;
  }
  positionPanel();
  open.value = true;
  openTopbarPopover.value = "profile";
}
watch(openTopbarPopover, (v) => {
  if (v !== "profile") open.value = false;
});
function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) open.value = false;
}

function goProfile() {
  open.value = false;
  router.push("/settings?section=profile");
}
function goSettings() {
  open.value = false;
  router.push("/settings");
}

async function handleLogout() {
  open.value = false;
  await logout();
  currentUser.value = null;
  router.push("/login");
}

function onDocumentClick(e: MouseEvent) {
  const target = e.target as Node;
  const insideTrigger = root.value?.contains(target);
  const insidePanel = (target as HTMLElement).closest?.(".profile-menu-panel");
  if (!insideTrigger && !insidePanel) open.value = false;
}
function onResize() {
  if (open.value) positionPanel();
}

onMounted(() => {
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", onKeydown);
  window.addEventListener("resize", onResize);
});
onBeforeUnmount(() => {
  document.removeEventListener("click", onDocumentClick);
  document.removeEventListener("keydown", onKeydown);
  window.removeEventListener("resize", onResize);
});
</script>

<template>
  <div ref="root" class="profile-menu-wrap">
    <div
      ref="triggerBtn"
      class="profile-menu-trigger"
      :class="{ active: open }"
      role="button"
      tabindex="0"
      title="Profile"
      aria-haspopup="true"
      :aria-expanded="open"
      @click.stop="toggle"
      @keydown.enter.stop="toggle"
      @keydown.space.stop.prevent="toggle"
    >
      <slot />
      <div class="profile-menu-avatar-wrap">
        <div class="profile-menu-avatar">{{ initials }}</div>
        <div class="profile-menu-chevron-badge">
          <svg
            class="profile-menu-chevron"
            :class="{ open }"
            viewBox="0 0 24 24"
            width="9"
            height="9"
            fill="none"
            stroke="#ddd"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M6 9l6 6 6-6" />
          </svg>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="open"
        class="profile-menu-panel"
        :style="{ ...panelStyle, '--caret-offset': `${caretOffset}px` }"
      >
        <div class="profile-menu-head">
          <div class="profile-menu-name">{{ currentUser?.username }}</div>
          <div class="profile-menu-email">{{ currentUser?.email }}</div>
        </div>
        <button type="button" class="profile-menu-item" @click="goProfile">
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c0-4.4 3.6-7 8-7s8 2.6 8 7" />
          </svg>
          Profile
        </button>
        <button type="button" class="profile-menu-item" @click="goSettings">
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="12" r="3" />
            <path
              d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1z"
            />
          </svg>
          Settings
        </button>
        <div class="profile-menu-divider"></div>
        <button
          type="button"
          class="profile-menu-item danger"
          @click="handleLogout"
        >
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
          Log Out
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.profile-menu-wrap {
  display: flex;
}
.profile-menu-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  cursor: pointer;
  transition: gap 0.14s ease;
}
.profile-menu-avatar-wrap {
  position: relative;
  flex-shrink: 0;
  line-height: 0;
}
.profile-menu-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #d68a34;
  color: #111;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
}
.profile-menu-chevron-badge {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  background: #2a2a2a;
  border: 2px solid #171717;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.12s ease;
}
.profile-menu-trigger:hover .profile-menu-chevron-badge,
.profile-menu-trigger.active .profile-menu-chevron-badge {
  background: #3a3a3a;
}
.profile-menu-chevron {
  transition: transform 0.15s ease;
}
.profile-menu-chevron.open {
  transform: rotate(180deg);
}
</style>

<style>
/* Unscoped: the panel is teleported outside this component's tree, so
   `scoped` attribute selectors would never match it. */
.profile-menu-panel {
  position: fixed;
  z-index: var(--ui-z-popover, 350);
  width: 172px;
  max-width: calc(100vw - 32px);
  box-sizing: border-box;
  background: #171717;
  border: 1px solid #2b2b2b;
  border-radius: 12px;
  padding: 6px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
}
.profile-menu-panel::before {
  content: "";
  position: absolute;
  top: -6px;
  left: var(--caret-offset, 20px);
  width: 11px;
  height: 11px;
  background: #171717;
  border-left: 1px solid #2b2b2b;
  border-top: 1px solid #2b2b2b;
  border-radius: 2px;
  transform: rotate(45deg);
}
.profile-menu-panel .profile-menu-divider {
  height: 1px;
  background: #232323;
  margin: 4px 4px;
}
.profile-menu-panel .profile-menu-head {
  padding: 7px 8px 8px;
  border-bottom: 1px solid #232323;
  margin-bottom: 4px;
}
.profile-menu-panel .profile-menu-name {
  color: #eee;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.profile-menu-panel .profile-menu-email {
  color: #888;
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}
.profile-menu-panel .profile-menu-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  background: none;
  border: none;
  padding: 8px 8px;
  border-radius: 8px;
  text-align: left;
  color: #eee;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.profile-menu-panel .profile-menu-item:hover {
  background: rgba(255, 255, 255, 0.06);
}
.profile-menu-panel .profile-menu-item.danger {
  color: #e08585;
}
</style>
