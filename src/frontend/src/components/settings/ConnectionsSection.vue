<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { fetchProviderCredentials } from "../../services/settings";
import type { ProviderCredentialStatus } from "../../services/settings";
import { syncLibrary } from "../../services/librarySync";
import type { LibrarySyncProvider } from "../../services/librarySync";

const emit = defineEmits<{ navigate: [section: string] }>();

// Only providers you sign in to and pull a library from. Metadata sources
// (TMDB, IGDB, SteamGridDB...) live under Library > Metadata.
const ACCOUNT_PROVIDERS = ["Steam", "PlayStation", "RetroAchievements", "Xbox"];

const credentials = ref<Record<string, ProviderCredentialStatus>>({});
const loading = ref(true);
const error = ref<string | null>(null);
const syncing = ref<string | null>(null);
const syncMessage = ref<string | null>(null);

const SYNCABLE: Record<string, LibrarySyncProvider> = {
  Steam: "steam",
  PlayStation: "psn",
  RetroAchievements: "retroachievements",
};

const MARKS: Record<string, { bg: string; fg: string; mark: string }> = {
  Steam: { bg: "#12202e", fg: "#66c0f4", mark: "S" },
  SteamGridDB: { bg: "#0e3b3b", fg: "#2dd4bf", mark: "Gr" },
  IGDB: { bg: "#2b1c4a", fg: "#a78bfa", mark: "IG" },
  TMDB: { bg: "#01283d", fg: "#5dd9c1", mark: "TM" },
  OMDb: { bg: "#2a2205", fg: "#f5c518", mark: "OM" },
  TVDB: { bg: "#1a2a3d", fg: "#7ba7d9", mark: "TV" },
  RetroAchievements: { bg: "#3b0a0a", fg: "#f87171", mark: "RA" },
  PlayStation: { bg: "#0a1a3d", fg: "#60a5fa", mark: "PS" },
  GOG: { bg: "#2a1a3d", fg: "#c084fc", mark: "GOG" },
};
const FALLBACK = { bg: "#1f1f1f", fg: "#d1d5db", mark: "•" };

function markFor(name: string) {
  return MARKS[name] ?? { ...FALLBACK, mark: name.slice(0, 2) };
}

function isConnected(s: ProviderCredentialStatus): boolean {
  return (
    s.status === "connected" ||
    s.status === "configured" ||
    s.status === "saved"
  );
}

function timeAgo(unix: number | null | undefined): string {
  if (!unix) return "never synced";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - unix));
  if (s < 60) return "synced just now";
  if (s < 3600) return `synced ${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `synced ${Math.floor(s / 3600)}h ago`;
  return `synced ${Math.floor(s / 86400)}d ago`;
}

interface Row {
  name: string;
  connected: boolean;
  error: boolean;
  detail: string;
  syncable: LibrarySyncProvider | null;
}

const accountRows = computed<Row[]>(() =>
  Object.entries(credentials.value)
    .filter(([name]) => ACCOUNT_PROVIDERS.includes(name))
    .map(([name, s]) => {
      const bits: string[] = [];
      if (s.display_name) bits.push(s.display_name);
      if (s.library_games != null) bits.push(`${s.library_games} games`);
      if (SYNCABLE[name] && isConnected(s))
        bits.push(timeAgo(s.last_synced_at));
      return {
        name,
        connected: isConnected(s),
        error: s.status === "error",
        detail: bits.join(" · ") || (s.detail ?? ""),
        syncable: SYNCABLE[name] ?? null,
      };
    })
    .sort((a, b) => Number(b.connected) - Number(a.connected)),
);

async function load() {
  loading.value = true;
  try {
    credentials.value = await fetchProviderCredentials();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't load connections.";
  }
  loading.value = false;
}
onMounted(load);

async function sync(row: Row) {
  if (!row.syncable) return;
  syncing.value = row.name;
  syncMessage.value = null;
  try {
    const r = await syncLibrary(row.syncable);
    syncMessage.value = `${row.name}: ${r.games_added} added, ${r.games_updated} updated.`;
    await load();
  } catch (e) {
    syncMessage.value = e instanceof Error ? e.message : "Sync failed.";
  } finally {
    syncing.value = null;
  }
}
</script>

<template>
  <section class="settings-section">
    <h2>Connections</h2>
    <p class="hint">
      The accounts your library is linked to. Adding or changing one happens
      under Library > Metadata.
    </p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="syncMessage" class="note">{{ syncMessage }}</p>

    <p v-if="loading" class="hint">Loading…</p>
    <ul v-else class="rows">
      <li v-for="row in accountRows" :key="row.name" class="row">
        <span
          class="mark"
          :style="{
            background: markFor(row.name).bg,
            color: markFor(row.name).fg,
          }"
          >{{ markFor(row.name).mark }}</span
        >
        <span class="info">
          <strong>{{ row.name }}</strong>
          <span class="detail">{{ row.detail || "Not connected" }}</span>
        </span>
        <span class="pill" :class="{ ok: row.connected, bad: row.error }">{{
          row.error ? "Error" : row.connected ? "Connected" : "Not set up"
        }}</span>
        <button
          v-if="row.syncable && row.connected"
          type="button"
          class="btn"
          :disabled="syncing !== null"
          @click="sync(row)"
        >
          {{ syncing === row.name ? "Syncing…" : "Sync now" }}
        </button>
        <button
          type="button"
          class="btn ghost"
          @click="emit('navigate', 'sources')"
        >
          Manage
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.settings-section h2 {
  margin: 0 0 8px;
  padding-left: 12px;
  border-left: 3px solid #d68a34;
  font-size: 1rem;
  color: #fff;
}
h3 {
  margin: 24px 0 10px;
  font-size: 0.85rem;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.hint {
  color: #888;
  font-size: 0.85rem;
  margin: 0 0 8px;
}
.error {
  color: #fca5a5;
  font-size: 0.85rem;
}
.note {
  color: #86efac;
  font-size: 0.85rem;
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: #151515;
  border: 1px solid #262626;
  border-radius: 10px;
}
.mark {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 800;
  flex-shrink: 0;
}
.info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: #eee;
  font-size: 0.9rem;
}
.detail {
  color: #888;
  font-size: 0.78rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pill {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 999px;
  color: #999;
  background: rgba(255, 255, 255, 0.06);
  white-space: nowrap;
}
.pill.ok {
  color: #86efac;
  background: rgba(34, 197, 94, 0.12);
}
.pill.bad {
  color: #fca5a5;
  background: rgba(220, 38, 38, 0.14);
}
.btn {
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 8px;
  padding: 7px 12px;
  font: inherit;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
}
.btn.ghost {
  background: rgba(255, 255, 255, 0.06);
  color: #ddd;
}
.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
