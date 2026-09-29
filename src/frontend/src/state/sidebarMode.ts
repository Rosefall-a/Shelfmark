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
