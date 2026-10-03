<script setup lang="ts">
// The one notification entry point, dropped into every page's top bar
// (or, on a page with no shared top bar, floated in the same top-right
// corner). Same list markup and the same shared state SidebarNav.vue's
// panel already used, just always reachable instead of one tap into the
// hamburger menu first.
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";
import { openTopbarPopover } from "../state/topbarPopover";
import {
  mediaNotifications,
  mediaUnread,
  refreshMediaNotifications,
  readMediaNotification,
  readAllMediaNotifications,
  mediaNotificationRoute,
} from "../state/notifications";

const router = useRouter();
const root = ref<HTMLElement | null>(null);
const bellBtn = ref<HTMLElement | null>(null);
const open = ref(false);

// Teleported to <body> so a page's own clipping/stacking context (a hero
// section's overflow:hidden, a sticky bar's own stacking order) never cuts
// the panel off, the same reasoning as MediaExtrasPanel's popovers.
const panelStyle = ref<{ top: string; left: string }>({
  top: "0px",
  left: "0px",
});
const caretOffset = ref(20);
function positionPanel() {
  const rect = bellBtn.value?.getBoundingClientRect();
  if (!rect) return;
  const left = Math.max(
    16,
    Math.min(rect.right - 320, window.innerWidth - 336),
  );
  panelStyle.value = {
    top: `${rect.bottom + 10}px`,
    left: `${left}px`,
  };
  // same pointer the profile menu has, aimed at the bell's centre
  caretOffset.value = Math.max(14, rect.left + rect.width / 2 - left - 5.5);
}

function toggle() {
  if (open.value) {
    open.value = false;
    return;
  }
  positionPanel();
  open.value = true;
  openTopbarPopover.value = "bell";
}
watch(openTopbarPopover, (v) => {
  if (v !== "bell") open.value = false;
});
function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) open.value = false;
}

function timeAgo(unix: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - unix));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function openNotification(id: string, to: string) {
  readMediaNotification(id);
  open.value = false;
  router.push(to);
}
function seeAll() {
  open.value = false;
  router.push("/notifications");
}

function onDocumentClick(e: MouseEvent) {
  const target = e.target as Node;
  const insideTrigger = root.value?.contains(target);
  const insidePanel = (target as HTMLElement).closest?.(".bell-panel");
  if (!insideTrigger && !insidePanel) open.value = false;
}
function onResize() {
  if (open.value) positionPanel();
}

onMounted(() => {
  void refreshMediaNotifications();
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
  <div ref="root" class="bell-wrap">
    <button
      ref="bellBtn"
      type="button"
      class="bell-button"
      :class="{ active: open }"
      title="Notifications"
      aria-haspopup="true"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      <svg
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.7 21a2 2 0 0 1-3.4 0" />
      </svg>
      <span v-if="mediaUnread" class="bell-dot"></span>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        class="bell-panel"
        :style="{ ...panelStyle, '--caret-offset': `${caretOffset}px` }"
      >
        <div class="panel-head">
          <span>Notifications</span>
          <button
            v-if="mediaUnread"
            type="button"
            class="mark-read-btn"
            @click="readAllMediaNotifications"
          >
            Mark all read
          </button>
        </div>
        <p v-if="!mediaNotifications.length" class="panel-empty">
          Nothing to flag right now.
        </p>
        <div class="panel-list">
          <button
            v-for="n in mediaNotifications.slice(0, 15)"
            :key="n.id"
            type="button"
            class="notification-row"
            :class="{ read: n.read }"
            @click="openNotification(n.id, mediaNotificationRoute(n))"
          >
            <span
              v-if="n.posterUrl"
              class="notification-poster"
              :style="{ backgroundImage: `url(${n.posterUrl})` }"
            ></span>
            <span
              v-else
              class="notification-dot"
              :class="{ unread: !n.read }"
            ></span>
            <span class="notification-text">
              <span class="notification-title">{{ n.title }}</span>
              <span class="notification-detail"
                >{{ n.body }} · {{ timeAgo(n.eventAt) }}</span
              >
            </span>
            <span v-if="!n.read" class="notification-unread-dot"></span>
          </button>
        </div>
        <button type="button" class="see-all-btn" @click="seeAll">
          See all notifications
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.bell-wrap {
  display: flex;
}
.bell-button {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: none;
  background: none;
  color: #ccc;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  position: relative;
  flex-shrink: 0;
}
.bell-button:hover,
.bell-button.active {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}
.bell-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d68a34;
  border: 2px solid #171717;
}
</style>

<style>
/* Unscoped: the panel is teleported outside this component's tree, so
   `scoped` attribute selectors would never match it. */
.bell-panel {
  position: fixed;
  z-index: var(--ui-z-popover, 350);
  width: 320px;
  max-width: calc(100vw - 32px);
  box-sizing: border-box;
  background: #171717;
  border: 1px solid #2b2b2b;
  border-radius: 12px;
  padding: 6px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
}
.bell-panel::before {
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
.bell-panel .panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 8px 6px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #888;
}
.bell-panel .mark-read-btn {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  font-size: 11px;
  text-transform: none;
  letter-spacing: 0;
  color: #d68a34;
  cursor: pointer;
}
.bell-panel .panel-empty {
  color: #777;
  font-size: 13px;
  padding: 10px 8px;
  margin: 0;
}
.bell-panel .panel-list {
  max-height: 340px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.bell-panel .notification-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  background: none;
  border: none;
  padding: 8px;
  border-radius: 8px;
  text-align: left;
  text-decoration: none;
  color: inherit;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.bell-panel .notification-row:hover {
  background: rgba(255, 255, 255, 0.06);
}
.bell-panel .notification-row.read {
  opacity: 0.55;
}
.bell-panel .notification-poster {
  width: 30px;
  height: 42px;
  border-radius: 4px;
  flex-shrink: 0;
  background: #222 center / cover;
}
.bell-panel .notification-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
}
.bell-panel .notification-dot.unread {
  background: #6fbf73;
}
.bell-panel .notification-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.bell-panel .notification-title {
  color: #eee;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bell-panel .notification-detail {
  color: #888;
  font-size: 11.5px;
}
.bell-panel .notification-unread-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #d68a34;
  flex-shrink: 0;
  margin: 5px 0 0 auto;
}
.bell-panel .see-all-btn {
  display: block;
  width: 100%;
  background: none;
  border: none;
  border-top: 1px solid #232323;
  margin-top: 4px;
  padding: 9px 8px 4px;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  color: #d68a34;
  text-align: center;
  cursor: pointer;
}
.bell-panel .see-all-btn:hover {
  text-decoration: underline;
}
</style>
