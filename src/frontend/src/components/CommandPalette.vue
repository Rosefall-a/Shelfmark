<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import { fetchGames } from "../services/games";
import type { Game } from "../types/game";
import { isCommandPaletteOpen } from "../state/commandPalette";
import { smartCollections } from "../state/smartCollections";

const router = useRouter();

const open = isCommandPaletteOpen;
const query = ref("");
const inputRef = ref<HTMLInputElement | null>(null);

// fetched lazily on first open, then reused for the rest of the session,
// this is a jump-to tool, not a live search index, so a slightly stale
// list (a game added a minute ago) is an acceptable tradeoff for not
// re-fetching the whole library every keystroke
let gamesCache: Game[] | null = null;
const loaded = ref(false);

async function ensureLoaded() {
  if (loaded.value) return;
  try {
    gamesCache = await fetchGames();
  } catch {
    gamesCache = gamesCache ?? [];
  } finally {
    loaded.value = true;
  }
}

interface Result {
  key: string;
  kind: "game" | "collection" | "page";
  label: string;
  sublabel?: string;
  action: () => void;
}

const SETTINGS_SHORTCUTS: { label: string; section: string }[] = [
  { label: "Profile", section: "profile" },
  { label: "User Interface", section: "interface" },
  { label: "Appearance", section: "appearance" },
  { label: "Upload", section: "upload" },
  { label: "Notifications", section: "notifications" },
  { label: "Calendar", section: "calendar" },
  { label: "Keyboard Shortcuts", section: "shortcuts" },
  { label: "Connections", section: "connections" },
  { label: "Library", section: "library" },
  { label: "Media Trash", section: "media-trash" },
  { label: "Metadata", section: "metadata" },
  { label: "Metadata API keys", section: "sources" },
  { label: "Server Stats", section: "stats" },
  { label: "Export / Import", section: "export" },
];

const PAGE_SHORTCUTS: { label: string; to: string }[] = [
  { label: "Home", to: "/" },
  { label: "Games", to: "/games" },
  { label: "Collections", to: "/collections" },
];

const collectionNames = computed(() => {
  const set = new Set<string>();
  for (const g of gamesCache ?? []) for (const c of g.collections) set.add(c);
  for (const c of smartCollections.value) set.add(c.name);
  return [...set].sort();
});

const results = computed<Result[]>(() => {
  const q = query.value.trim().toLowerCase();
  const out: Result[] = [];

  if (!q) {
    for (const p of PAGE_SHORTCUTS) {
      out.push({
        key: "page:" + p.to,
        kind: "page",
        label: p.label,
        action: () => go(p.to),
      });
    }
    return out;
  }

  const games = (gamesCache ?? [])
    .filter((g) => g.title.toLowerCase().includes(q))
    .slice(0, 6);
  for (const g of games) {
    out.push({
      key: "game:" + g.id,
      kind: "game",
      label: g.title,
      sublabel: g.status,
      action: () => go(`/games/${g.id}`),
    });
  }

  const collections = collectionNames.value
    .filter((c) => c.toLowerCase().includes(q))
    .slice(0, 4);
  for (const c of collections) {
    out.push({
      key: "collection:" + c,
      kind: "collection",
      label: c,
      sublabel: "Collection",
      action: () => go(`/collections/${encodeURIComponent(c)}`),
    });
  }

  for (const s of SETTINGS_SHORTCUTS) {
    if (s.label.toLowerCase().includes(q)) {
      out.push({
        key: "settings:" + s.section,
        kind: "page",
        label: s.label,
        sublabel: "Settings",
        action: () => go(`/settings?section=${s.section}`),
      });
    }
  }
  for (const p of PAGE_SHORTCUTS) {
    if (p.label.toLowerCase().includes(q)) {
      out.push({
        key: "page:" + p.to,
        kind: "page",
        label: p.label,
        action: () => go(p.to),
      });
    }
  }

  return out.slice(0, 20);
});

const activeIndex = ref(0);
watch(results, () => {
  activeIndex.value = 0;
});

function go(to: string) {
  close();
  router.push(to);
}

function close() {
  open.value = false;
  query.value = "";
}

async function openPalette() {
  open.value = true;
  void ensureLoaded();
  await nextTick();
  inputRef.value?.focus();
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

function onGlobalKeydown(e: KeyboardEvent) {
  const isMeta = e.metaKey || e.ctrlKey;
  if (isMeta && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (open.value) close();
    else void openPalette();
    return;
  }
  if (!open.value) return;
  if (e.key === "Escape") {
    close();
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    activeIndex.value = Math.min(
      activeIndex.value + 1,
      results.value.length - 1,
    );
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    activeIndex.value = Math.max(activeIndex.value - 1, 0);
  } else if (e.key === "Enter") {
    e.preventDefault();
    results.value[activeIndex.value]?.action();
  } else if (e.key === "Tab" && !isTypingTarget(e.target)) {
    // no-op, the palette owns focus while open
    e.preventDefault();
  }
}

onMounted(() => window.addEventListener("keydown", onGlobalKeydown));
onUnmounted(() => window.removeEventListener("keydown", onGlobalKeydown));

const KIND_ICON: Record<Result["kind"], string> = {
  game: "🎮",
  collection: "📁",
  page: "→",
};
</script>

<template>
  <div v-if="open" class="palette-backdrop" @click.self="close">
    <div class="palette">
      <input
        ref="inputRef"
        v-model="query"
        type="text"
        class="palette-input"
        placeholder="Jump to a game, collection, or settings section…"
      />
      <div v-if="!loaded" class="palette-loading">Loading…</div>
      <div v-else-if="!results.length" class="palette-empty">No matches.</div>
      <div v-else class="palette-results">
        <button
          v-for="(r, i) in results"
          :key="r.key"
          type="button"
          class="palette-item"
          :class="{ active: i === activeIndex }"
          @mouseenter="activeIndex = i"
          @click="r.action()"
        >
          <span class="palette-item-icon">{{ KIND_ICON[r.kind] }}</span>
          <span class="palette-item-label">{{ r.label }}</span>
          <span v-if="r.sublabel" class="palette-item-sub">{{
            r.sublabel
          }}</span>
        </button>
      </div>
      <div class="palette-footer">
        <span><kbd>↑↓</kbd> navigate</span>
        <span><kbd>Enter</kbd> open</span>
        <span><kbd>Esc</kbd> close</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.palette-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
  z-index: 300;
}
.palette {
  width: 560px;
  max-width: calc(100vw - 40px);
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  box-shadow: 0 32px 80px rgba(0, 0, 0, 0.6);
  overflow: hidden;
}
.palette-input {
  width: 100%;
  box-sizing: border-box;
  background: none;
  border: none;
  border-bottom: 1px solid #2a2a2a;
  color: #fff;
  padding: 16px 18px;
  font: inherit;
  font-size: 15px;
}
.palette-input:focus {
  outline: none;
}
.palette-loading,
.palette-empty {
  color: #777;
  font-size: 13px;
  padding: 20px 18px;
}
.palette-results {
  max-height: 360px;
  overflow-y: auto;
  padding: 6px;
}
.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  background: none;
  border: none;
  color: #eee;
  text-align: left;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13.5px;
}
.palette-item.active {
  background: rgba(214, 138, 52, 0.16);
  color: #fff;
}
.palette-item-icon {
  font-size: 14px;
  width: 18px;
  text-align: center;
  flex-shrink: 0;
}
.palette-item-label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.palette-item-sub {
  color: #999;
  font-size: 11px;
  text-transform: capitalize;
  flex-shrink: 0;
}
.palette-item.active .palette-item-sub {
  color: #d68a34;
}
.palette-footer {
  display: flex;
  gap: 16px;
  padding: 10px 16px;
  border-top: 1px solid #2a2a2a;
  color: #666;
  font-size: 11px;
}
.palette-footer kbd {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 4px;
  padding: 1px 5px;
  font-family: ui-monospace, monospace;
  color: #999;
  margin-right: 4px;
}
</style>
