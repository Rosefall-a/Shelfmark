// How the sidebar behaves: overlay (default, hidden until the menu button
// opens it), pinned (always visible at full width, in flow), or rail
// (always visible collapsed to icons, expands on hover). Device-level, not
// a per-user account setting, so it lives in localStorage like compact mode
// and high contrast do.
import { ref, watch } from "vue";

export type SidebarMode = "overlay" | "pinned" | "rail";

const STORAGE_KEY = "sidebarMode";

function readStored(): SidebarMode {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "pinned" || stored === "rail" ? stored : "overlay";
}

export const sidebarMode = ref<SidebarMode>(readStored());

watch(sidebarMode, (mode) => localStorage.setItem(STORAGE_KEY, mode));

// Drag-resizable width for overlay and pinned modes (and rail's own
// hover-expanded width). The icon rail's collapsed width is fixed at 56px
// on purpose — that's the "just icons" point of the mode.
export const SIDEBAR_MIN_WIDTH = 200;
export const SIDEBAR_MAX_WIDTH = 440;
const WIDTH_STORAGE_KEY = "sidebarWidth";
const DEFAULT_WIDTH = 270;

function clampWidth(width: number): number {
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, width));
}

function readStoredWidth(): number {
  const stored = Number(localStorage.getItem(WIDTH_STORAGE_KEY));
  return stored ? clampWidth(stored) : DEFAULT_WIDTH;
}

export const sidebarWidth = ref<number>(readStoredWidth());

watch(sidebarWidth, (width) =>
  localStorage.setItem(WIDTH_STORAGE_KEY, String(width)),
);

export function setSidebarWidth(width: number) {
  sidebarWidth.value = clampWidth(width);
}

export function resetSidebarWidth() {
  sidebarWidth.value = DEFAULT_WIDTH;
}

// True for the duration of a resize drag, so App.vue can turn off its
// content margin transition too — otherwise the page trails behind the
// pointer instead of tracking it while dragging.
export const sidebarResizing = ref(false);
