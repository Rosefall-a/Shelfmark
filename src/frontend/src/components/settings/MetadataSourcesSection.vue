<script setup lang="ts">
import { ref, reactive, onMounted } from "vue";
import PasswordInput from "../PasswordInput.vue";
import { currentUser, checkAuth } from "../../state/auth";
import { updateProfile } from "../../services/auth";
import { fetchPsnStatus, connectPsn, disconnectPsn } from "../../services/psn";
import type { PsnStatus } from "../../services/psn";
import {
  fetchProviderCredentials,
  saveProviderCredentials,
  deleteProviderCredentials,
  fetchScanSettings,
  updateScanSettings,
  fetchAppIntegrations,
  updateAppIntegrations,
} from "../../services/settings";
import type { ProviderCredentialStatus } from "../../services/settings";
import { syncLibrary } from "../../services/librarySync";
import type { LibrarySyncProvider } from "../../services/librarySync";
import {
  startTask,
  completeTask,
  errorTask,
  addFeedItem,
} from "../../state/taskProgress";

// small colored monogram badge per provider, no real logos bundled, so a
// distinct brand-ish color + short mark stands in, RomM-style icon tile
interface CardVisual {
  bg: string;
  fg: string;
  mark: string;
}
// short one-liner shown on every tile so the grid stays scannable without
// hovering, the fuller description still lives in the `title` tooltip
const SHORT_DESC: Record<string, string> = {
  Steam: "Public store data, no key needed",
  SteamGridDB: "Cover art & hero banners",
  IGDB: "General metadata & art (app-wide key)",
  TMDB: "Movie metadata & posters (app-wide key)",
  OMDb: "IMDb-backed movie fallback source (app-wide key)",
  TVDB: "TV show franchise & relations data (app-wide key)",
  GiantBomb: "General metadata & art",
  ScreenScraper: "Retro box art & screenshots",
  GOG: "Metadata search, no key needed",
  LaunchBox: "Local app, not a cloud API",
  RetroAchievements: "Retro metadata & achievements",
  PlayStation: "Trophies & PSN Store data",
  Xbox: "Saved only: no live pull yet",
  HowLongToBeat: "Time-to-beat data",
};

const VISUALS: Record<string, CardVisual> = {
  Steam: { bg: "#12202e", fg: "#66c0f4", mark: "S" },
  SteamGridDB: { bg: "#0e3b3b", fg: "#2dd4bf", mark: "Gr" },
  IGDB: { bg: "#2b1c4a", fg: "#a78bfa", mark: "IG" },
  TMDB: { bg: "#01283d", fg: "#5dd9c1", mark: "TM" },
  OMDb: { bg: "#2a2205", fg: "#f5c518", mark: "OM" },
  TVDB: { bg: "#1a2a3d", fg: "#7ba7d9", mark: "TV" },
  GiantBomb: { bg: "#3d2f00", fg: "#fbbf24", mark: "GB" },
  RetroAchievements: { bg: "#3b0a0a", fg: "#f87171", mark: "RA" },
  ScreenScraper: { bg: "#1a3d0a", fg: "#86efac", mark: "SS" },
  Xbox: { bg: "#0a2e0a", fg: "#4ade80", mark: "Xb" },
  GOG: { bg: "#2a1a3d", fg: "#c084fc", mark: "GOG" },
  LaunchBox: { bg: "#1a1a1a", fg: "#999999", mark: "LB" },
  PlayStation: { bg: "#0a1a3d", fg: "#60a5fa", mark: "PS" },
  HowLongToBeat: { bg: "#1f1f1f", fg: "#d1d5db", mark: "HL" },
};

// which cards are expanded to show their configure form, collapsed by
// default so the grid stays a dense, scannable wall of tiles
const expanded = reactive<Record<string, boolean>>({});
function toggleExpanded(key: string) {
  expanded[key] = !expanded[key];
}

const steamgriddbApiKey = ref(currentUser.value?.steamgriddb_api_key ?? "");
const saving = ref(false);
const saveError = ref<string | null>(null);
const saveSuccess = ref(false);

async function saveSteamgriddbKey() {
  saving.value = true;
  saveError.value = null;
  saveSuccess.value = false;

  try {
    await updateProfile({ steamgriddbApiKey: steamgriddbApiKey.value.trim() });
    await checkAuth();
    saveSuccess.value = true;
  } catch (err) {
    saveError.value =
      err instanceof Error ? err.message : "Failed to save settings";
  } finally {
    saving.value = false;
  }
}

// IGDB, deployment-wide, admin-only credentials (not per-user, see
// database/models/app_integration_settings.py). Non-admins never see the
// form, only whether it's configured.
const isAdmin = ref(currentUser.value?.is_admin ?? false);
const igdbClientId = ref("");
const igdbClientSecret = ref("");
const igdbConfigured = ref(false);
const igdbLoading = ref(true);
const igdbSaving = ref(false);
const igdbError = ref<string | null>(null);

const tmdbApiKey = ref("");
const tmdbConfigured = ref(false);
const tmdbSaving = ref(false);
const tmdbError = ref<string | null>(null);

const omdbApiKey = ref("");
const omdbConfigured = ref(false);
const omdbSaving = ref(false);
const omdbError = ref<string | null>(null);

// a key the server's environment provides is in effect, but Settings can
// only override it, not clear it
const keySources = ref<Record<string, string>>({});
function keyPlaceholder(name: string, configured: boolean, empty: string) {
  if (!configured) return empty;
  return keySources.value[name] === "environment"
    ? "Set by the server: type a key to override it"
    : "Saved: leave blank to keep";
}

const tvdbApiKey = ref("");
const tvdbConfigured = ref(false);
const tvdbSaving = ref(false);
const tvdbError = ref<string | null>(null);

onMounted(async () => {
  if (!isAdmin.value) {
    igdbLoading.value = false;
    return;
  }
  try {
    const result = await fetchAppIntegrations();
    igdbClientId.value = result.igdb_client_id ?? "";
    igdbConfigured.value = result.igdb_configured;
    keySources.value = result.sources ?? {};
    tmdbConfigured.value = result.tmdb_configured;
    omdbConfigured.value = result.omdb_configured;
    tvdbConfigured.value = result.tvdb_configured;
    credentialStatus.TMDB = {
      status: tmdbConfigured.value ? "configured" : "not_configured",
    };
    credentialStatus.OMDb = {
      status: omdbConfigured.value ? "configured" : "not_configured",
    };
    credentialStatus.TVDB = {
      status: tvdbConfigured.value ? "configured" : "not_configured",
    };
  } finally {
    igdbLoading.value = false;
  }
});

async function saveIgdbCredentials() {
  igdbSaving.value = true;
  igdbError.value = null;
  try {
    const payload: { igdb_client_id?: string; igdb_client_secret?: string } = {
      igdb_client_id: igdbClientId.value.trim(),
    };
    if (igdbClientSecret.value.trim())
      payload.igdb_client_secret = igdbClientSecret.value.trim();
    const result = await updateAppIntegrations(payload);
    igdbClientId.value = result.igdb_client_id ?? "";
    igdbConfigured.value = result.igdb_configured;
    igdbClientSecret.value = "";
    credentialStatus.IGDB = {
      status: igdbConfigured.value ? "configured" : "not_configured",
    };
  } catch (err) {
    igdbError.value =
      err instanceof Error ? err.message : "Failed to save IGDB credentials";
  } finally {
    igdbSaving.value = false;
  }
}

async function clearIgdbCredentials() {
  igdbSaving.value = true;
  igdbError.value = null;
  try {
    const result = await updateAppIntegrations({
      igdb_client_id: "",
      igdb_client_secret: "",
    });
    keySources.value = result.sources ?? {};
    igdbClientId.value = result.igdb_client_id ?? "";
    igdbClientSecret.value = "";
    igdbConfigured.value = result.igdb_configured;
    credentialStatus.IGDB = {
      status: igdbConfigured.value ? "configured" : "not_configured",
    };
  } catch (err) {
    igdbError.value =
      err instanceof Error ? err.message : "Failed to clear IGDB credentials";
  } finally {
    igdbSaving.value = false;
  }
}

// TMDB/OMDb each save/clear only their own field via PUT — unlike IGDB's
// DELETE above, which clears every app-integration field at once. Reusing
// that same DELETE for a single-key provider would wipe the other two
// providers' keys too, so a plain PUT with an empty string is used to
// clear just one field instead.
async function saveTmdbKey() {
  tmdbSaving.value = true;
  tmdbError.value = null;
  try {
    const result = await updateAppIntegrations({
      tmdb_api_key: tmdbApiKey.value.trim(),
    });
    tmdbConfigured.value = result.tmdb_configured;
    tmdbApiKey.value = "";
    credentialStatus.TMDB = {
      status: tmdbConfigured.value ? "configured" : "not_configured",
    };
  } catch (err) {
    tmdbError.value =
      err instanceof Error ? err.message : "Failed to save TMDB key";
  } finally {
    tmdbSaving.value = false;
  }
}

async function clearTmdbKey() {
  tmdbSaving.value = true;
  tmdbError.value = null;
  try {
    const result = await updateAppIntegrations({ tmdb_api_key: "" });
    tmdbApiKey.value = "";
    keySources.value = result.sources ?? {};
    tmdbConfigured.value = result.tmdb_configured;
    credentialStatus.TMDB = {
      status: tmdbConfigured.value ? "configured" : "not_configured",
    };
  } catch (err) {
    tmdbError.value =
      err instanceof Error ? err.message : "Failed to clear TMDB key";
  } finally {
    tmdbSaving.value = false;
  }
}

async function saveOmdbKey() {
  omdbSaving.value = true;
  omdbError.value = null;
  try {
    const result = await updateAppIntegrations({
      omdb_api_key: omdbApiKey.value.trim(),
    });
    omdbConfigured.value = result.omdb_configured;
    omdbApiKey.value = "";
    credentialStatus.OMDb = {
      status: omdbConfigured.value ? "configured" : "not_configured",
    };
  } catch (err) {
    omdbError.value =
      err instanceof Error ? err.message : "Failed to save OMDb key";
  } finally {
    omdbSaving.value = false;
  }
}

async function clearOmdbKey() {
  omdbSaving.value = true;
  omdbError.value = null;
  try {
    const result = await updateAppIntegrations({ omdb_api_key: "" });
    omdbApiKey.value = "";
    keySources.value = result.sources ?? {};
    omdbConfigured.value = result.omdb_configured;
    credentialStatus.OMDb = {
      status: omdbConfigured.value ? "configured" : "not_configured",
    };
  } catch (err) {
    omdbError.value =
      err instanceof Error ? err.message : "Failed to clear OMDb key";
  } finally {
    omdbSaving.value = false;
  }
}

async function saveTvdbKey() {
  tvdbSaving.value = true;
  tvdbError.value = null;
  try {
    const result = await updateAppIntegrations({
      tvdb_api_key: tvdbApiKey.value.trim(),
    });
    tvdbConfigured.value = result.tvdb_configured;
    tvdbApiKey.value = "";
    credentialStatus.TVDB = {
      status: tvdbConfigured.value ? "configured" : "not_configured",
    };
  } catch (err) {
    tvdbError.value =
      err instanceof Error ? err.message : "Failed to save TVDB key";
  } finally {
    tvdbSaving.value = false;
  }
}

async function clearTvdbKey() {
  tvdbSaving.value = true;
  tvdbError.value = null;
  try {
    const result = await updateAppIntegrations({ tvdb_api_key: "" });
    tvdbApiKey.value = "";
    keySources.value = result.sources ?? {};
    tvdbConfigured.value = result.tvdb_configured;
    credentialStatus.TVDB = {
      status: tvdbConfigured.value ? "configured" : "not_configured",
    };
  } catch (err) {
    tvdbError.value =
      err instanceof Error ? err.message : "Failed to clear TVDB key";
  } finally {
    tvdbSaving.value = false;
  }
}

const psnStatus = ref<PsnStatus>({ connected: false, validated_at: null });
const psnLoading = ref(true);
const npssoToken = ref("");
const psnConnecting = ref(false);
const psnError = ref<string | null>(null);
const showDisconnectConfirm = ref(false);

onMounted(async () => {
  try {
    psnStatus.value = await fetchPsnStatus();
  } finally {
    psnLoading.value = false;
  }
});

async function handleConnectPsn() {
  if (!npssoToken.value.trim()) {
    psnError.value = "Paste your npsso token first.";
    return;
  }
  psnConnecting.value = true;
  psnError.value = null;
  try {
    psnStatus.value = await connectPsn(npssoToken.value.trim());
    npssoToken.value = "";
  } catch (err) {
    psnError.value =
      err instanceof Error
        ? err.message
        : "Failed to connect PlayStation account";
  } finally {
    psnConnecting.value = false;
  }
}

async function confirmDisconnectPsn() {
  showDisconnectConfirm.value = false;
  psnError.value = null;
  try {
    await disconnectPsn();
    psnStatus.value = { connected: false, validated_at: null };
  } catch (err) {
    psnError.value =
      err instanceof Error
        ? err.message
        : "Failed to disconnect PlayStation account";
  }
}

// --- data-driven providers ---------------------------------------------

interface ProviderFieldConfig {
  key: string;
  label: string;
  type: "text" | "password";
}

interface ProviderCardConfig {
  key: string;
  label: string;
  description: string;
  fields: ProviderFieldConfig[];
  kind: "wired" | "deferred";
  linkLabel?: string;
  linkUrl?: string;
}

const PROVIDER_CARDS: Record<string, ProviderCardConfig> = {
  Steam: {
    key: "Steam",
    label: "Steam",
    description:
      "No account needed for metadata search. Importing your library and achievements requires both fields below: your profile ID (the part after steamcommunity.com/id/, not the full link) and a Web API key. Your profile's game details must also be set to Public, or Steam silently returns an empty library.",
    fields: [
      { key: "steam_id", label: "Profile ID", type: "text" },
      { key: "api_key", label: "Web API Key", type: "password" },
    ],
    kind: "wired",
    linkLabel: "Get a Steam Web API key",
    linkUrl: "https://steamcommunity.com/dev/apikey",
  },
  IGDB: {
    key: "IGDB",
    label: "IGDB",
    description:
      "General game metadata and cover art. Uses one deployment-wide developer credential, managed by a server administrator here rather than per-user.",
    fields: [],
    kind: "wired",
  },
  TMDB: {
    key: "TMDB",
    label: "TMDB",
    description:
      "Movie metadata and poster art. Uses one deployment-wide API key, managed by a server administrator here rather than per-user.",
    fields: [],
    kind: "wired",
  },
  OMDb: {
    key: "OMDb",
    label: "OMDb",
    description:
      "IMDb-backed movie metadata, used alongside TMDB so a search still returns results if one source is down or missing a title. Uses one deployment-wide API key, managed by a server administrator here rather than per-user.",
    fields: [],
    kind: "wired",
  },
  TVDB: {
    key: "TVDB",
    label: "TheTVDB",
    description:
      "The only real franchise/relations source for TV shows (TMDB has no collection concept outside of movies). It powers the Related tab on a show's page. Uses one deployment-wide API key, managed by a server administrator here rather than per-user.",
    fields: [],
    kind: "wired",
  },
  RetroAchievements: {
    key: "RetroAchievements",
    label: "RetroAchievements",
    description:
      "Retro/console game metadata, plus your username to pull your library and unlocked achievements: powers all three from one key.",
    fields: [
      { key: "username", label: "Username", type: "text" },
      { key: "api_key", label: "API Key", type: "password" },
    ],
    kind: "wired",
    linkLabel: "Get a free key from RetroAchievements",
    linkUrl: "https://retroachievements.org/controlpanel.php",
  },
  GiantBomb: {
    key: "GiantBomb",
    label: "Giant Bomb",
    description: "General game metadata and cover art.",
    fields: [{ key: "api_key", label: "API Key", type: "password" }],
    kind: "wired",
    linkLabel: "Get a free key from Giant Bomb",
    linkUrl: "https://www.giantbomb.com/api/",
  },
  ScreenScraper: {
    key: "ScreenScraper",
    label: "ScreenScraper",
    description:
      "Retro box art and screenshots. Needs your personal screenscraper.fr account on top of the app-wide developer credentials your server administrator configures.",
    fields: [
      { key: "ssid", label: "Username", type: "text" },
      { key: "sspassword", label: "Password", type: "password" },
    ],
    kind: "wired",
    linkLabel: "Create a free ScreenScraper account",
    linkUrl: "https://www.screenscraper.fr/membreinscription.php",
  },
  Xbox: {
    key: "Xbox",
    label: "Xbox",
    description:
      "Unofficial: Xbox's real API needs a full sign-in flow this page can't host yet. Saving your Azure app credentials here just gets them ready for that; nothing is pulled from Xbox yet.",
    fields: [
      { key: "client_id", label: "Application (client) ID", type: "text" },
      { key: "client_secret", label: "Client secret", type: "password" },
    ],
    kind: "deferred",
  },
  GOG: {
    key: "GOG",
    label: "GOG",
    description:
      "Metadata search uses GOG's public store catalog: no key needed. The refresh token below is only for a future library import, not search.",
    fields: [
      {
        key: "refresh_token",
        label: "Refresh token (library import only)",
        type: "password",
      },
    ],
    kind: "wired",
  },
};

const credentialStatus = reactive<Record<string, ProviderCredentialStatus>>({});
const fieldValues = reactive<Record<string, Record<string, string>>>({});
const cardSaving = reactive<Record<string, boolean>>({});
const cardError = reactive<Record<string, string | null>>({});
const cardInfo = reactive<Record<string, string | null>>({});
const credentialsLoading = ref(true);

// must be ready before first render, the template binds
// fieldValues[card.key][field.key] immediately, not just after mount
for (const key of Object.keys(PROVIDER_CARDS)) {
  fieldValues[key] = {};
}

onMounted(async () => {
  try {
    const result = await fetchProviderCredentials();
    Object.assign(credentialStatus, result);
    // prefill non-secret fields (profile IDs, usernames) that are already
    // saved, so the form shows them filled instead of misleadingly blank
    for (const [key, status] of Object.entries(result)) {
      if (status.fields)
        Object.assign(
          fieldValues[key] ?? (fieldValues[key] = {}),
          status.fields,
        );
    }
  } finally {
    credentialsLoading.value = false;
  }
});

// a password-type field that's already saved gets a placeholder instead of
// its real value (never echoed back), still communicates "this is filled"
function passwordPlaceholder(
  key: string,
  fieldKey: string,
  label: string,
): string {
  const status = credentialStatus[key]?.status;
  const alreadySaved =
    status === "connected" || status === "saved" || status === "configured";
  if (alreadySaved && !fieldValues[key]?.[fieldKey])
    return "Already saved: paste a new value to replace it";
  return `Paste your ${label.toLowerCase()}`;
}

// no personal key, but the server's own key covers searches (#234)
function usesServerKey(key: string): boolean {
  const entry = credentialStatus[key];
  return entry?.status === "not_configured" && !!entry.server_configured;
}

function statusLabel(key: string): string {
  const status = credentialStatus[key]?.status;
  if (status === "connected") return "Connected";
  if (status === "saved" || status === "configured") return "Saved";
  if (status === "error") return "Error";
  if (usesServerKey(key)) return "Using server key";
  return "Not configured";
}
function statusClass(key: string): string {
  const status = credentialStatus[key]?.status;
  if (status === "connected") return "connected";
  if (status === "saved" || status === "configured") return "saved";
  if (status === "error") return "error";
  if (usesServerKey(key)) return "saved";
  return "disconnected";
}

async function saveCard(card: ProviderCardConfig) {
  cardSaving[card.key] = true;
  cardError[card.key] = null;
  cardInfo[card.key] = null;
  try {
    const result = await saveProviderCredentials(
      card.key,
      fieldValues[card.key],
    );
    credentialStatus[card.key] = result;
    if (result.status === "error") {
      cardError[card.key] =
        result.detail ?? "Could not verify these credentials.";
    } else if (result.status === "saved" && result.detail) {
      cardInfo[card.key] = result.detail;
    }
  } catch (err) {
    cardError[card.key] = err instanceof Error ? err.message : "Failed to save";
  } finally {
    cardSaving[card.key] = false;
  }
}

async function clearCard(card: ProviderCardConfig) {
  try {
    await deleteProviderCredentials(card.key);
    credentialStatus[card.key] = { status: "not_configured" };
    cardError[card.key] = null;
    fieldValues[card.key] = {};
  } catch (err) {
    cardError[card.key] =
      err instanceof Error ? err.message : "Failed to disconnect";
  }
}

// --- library sync (real owned-games + achievements pull) ---------------

const librarySyncing = reactive<Record<LibrarySyncProvider, boolean>>({
  steam: false,
  psn: false,
  retroachievements: false,
});
const LIBRARY_SYNC_LABELS: Record<LibrarySyncProvider, string> = {
  steam: "Steam",
  psn: "PlayStation",
  retroachievements: "RetroAchievements",
};

async function handleSyncLibrary(provider: LibrarySyncProvider) {
  librarySyncing[provider] = true;
  // indeterminate, the backend is one all-at-once request with no
  // per-game signal until it resolves, so there's nothing real to show as
  // a fraction while it's in flight
  const taskId = startTask(
    `Syncing ${LIBRARY_SYNC_LABELS[provider]} library`,
    1,
    { indeterminate: true },
  );
  try {
    const result = await syncLibrary(provider);
    completeTask(
      taskId,
      `${result.games_added} added, ${result.games_updated} updated, ${result.achievements_synced} achievements`,
    );
    // the request itself wasn't live, but revealing the touched titles one
    // at a time still reads as a real "feed" once the result is in
    for (const [i, title] of result.games.entries()) {
      setTimeout(() => addFeedItem(taskId, title), i * 90);
    }
    // refresh the persistent "N games, last synced ..." line so it reflects
    // this run immediately instead of only on the next page load
    Object.assign(credentialStatus, await fetchProviderCredentials());
  } catch (err) {
    errorTask(taskId, err instanceof Error ? err.message : "Sync failed");
  } finally {
    librarySyncing[provider] = false;
  }
}

// only claims "synced" once a library sync has actually run, a game
// count alone (e.g. from manually-added Steam games) doesn't mean that
function formatLastSynced(
  status: ProviderCredentialStatus | undefined,
): string | null {
  if (!status?.last_synced_at) return null;
  const when = new Date(status.last_synced_at * 1000).toLocaleString(
    undefined,
    {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    },
  );
  const count = status.library_games ?? 0;
  return `${count} game${count === 1 ? "" : "s"} · synced ${when}`;
}

// HowLongToBeat, a real toggle now, not just informational. "Enabled"
// means "HowLongToBeat" is present in the user's scan provider_order.
const hltbEnabled = ref(false);
const hltbLoading = ref(true);
const hltbSaving = ref(false);
const hltbError = ref<string | null>(null);

onMounted(async () => {
  try {
    const scan = await fetchScanSettings();
    hltbEnabled.value = scan.provider_order.includes("HowLongToBeat");
  } finally {
    hltbLoading.value = false;
  }
});

async function toggleHltb(enabled: boolean) {
  hltbSaving.value = true;
  hltbError.value = null;
  try {
    const scan = await fetchScanSettings();
    const nextOrder = enabled
      ? [
          ...scan.provider_order.filter((p) => p !== "HowLongToBeat"),
          "HowLongToBeat",
        ]
      : scan.provider_order.filter((p) => p !== "HowLongToBeat");
    await updateScanSettings({
      provider_order: nextOrder as typeof scan.provider_order,
    });
    hltbEnabled.value = enabled;
  } catch (err) {
    hltbError.value =
      err instanceof Error ? err.message : "Failed to update HowLongToBeat";
  } finally {
    hltbSaving.value = false;
  }
}
</script>

<template>
  <section class="settings-section">
    <h2>Metadata/API</h2>
    <p class="section-hint">
      Providers used to search for and fill in game metadata and art, plus
      achievement/account connections. Click a tile's key icon to configure it:
      hover a name for details.
    </p>
    <p class="section-hint">
      Keys saved here are yours alone. An administrator can also set server-wide
      keys under Settings &rsaquo; Server Integrations; those are used for
      anyone without their own, shown here as "Using server key". A key of your
      own always takes precedence for your account.
    </p>

    <h3 class="group-heading">Metadata</h3>

    <div class="source-grid">
      <!-- SteamGridDB -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{
            background: VISUALS.SteamGridDB.bg,
            color: VISUALS.SteamGridDB.fg,
          }"
        >
          {{ VISUALS.SteamGridDB.mark }}
        </div>
        <div class="tile-body">
          <span
            class="tile-name"
            title="Cover art and hero banners. Your own key, used instead of the server's for your account."
            >SteamGridDB</span
          >
          <span
            class="tile-status"
            :class="
              steamgriddbApiKey
                ? 'connected'
                : credentialStatus.SteamGridDB?.server_configured
                  ? 'saved'
                  : 'disconnected'
            "
          >
            {{
              steamgriddbApiKey
                ? "Configured"
                : credentialStatus.SteamGridDB?.server_configured
                  ? "Using server key"
                  : "Not configured"
            }}
          </span>
        </div>
        <p class="tile-desc">{{ SHORT_DESC.SteamGridDB }}</p>
        <div class="tile-actions">
          <button
            type="button"
            class="icon-btn"
            :class="{ active: expanded.SteamGridDB }"
            title="Configure"
            @click="toggleExpanded('SteamGridDB')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
          <a
            class="icon-btn"
            href="https://www.steamgriddb.com/profile/preferences/api"
            target="_blank"
            rel="noopener noreferrer"
            title="Get a free key"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <path
                d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
              />
            </svg>
          </a>
        </div>
        <form
          v-if="expanded.SteamGridDB"
          class="tile-form"
          @submit.prevent="saveSteamgriddbKey"
        >
          <label class="field">
            <span>API Key</span>
            <PasswordInput
              v-model="steamgriddbApiKey"
              placeholder="Paste your SteamGridDB API key"
            />
          </label>
          <div v-if="saveError" class="form-error">{{ saveError }}</div>
          <div v-if="saveSuccess" class="form-success">Settings saved.</div>
          <button type="submit" class="primary-button" :disabled="saving">
            {{ saving ? "Saving…" : "Save" }}
          </button>
        </form>
      </div>

      <!-- IGDB: deployment-wide, admin-only credentials -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{ background: VISUALS.IGDB.bg, color: VISUALS.IGDB.fg }"
        >
          {{ VISUALS.IGDB.mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name" :title="PROVIDER_CARDS.IGDB.description"
            >IGDB</span
          >
          <span
            v-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass('IGDB')"
            >{{ statusLabel("IGDB") }}</span
          >
        </div>
        <p class="tile-desc">{{ SHORT_DESC.IGDB }}</p>
        <div class="tile-actions">
          <button
            v-if="isAdmin"
            type="button"
            class="icon-btn"
            :class="{ active: expanded.IGDB }"
            title="Configure (admin only)"
            @click="toggleExpanded('IGDB')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
        </div>
        <p v-if="!isAdmin" class="tile-desc admin-note">
          Configured deployment-wide by your server administrator.
        </p>
        <form
          v-if="isAdmin && expanded.IGDB"
          class="tile-form"
          @submit.prevent="saveIgdbCredentials"
        >
          <p class="tile-desc admin-note">
            Applies to every user on this server, not just you. Register a free
            app at
            <a
              href="https://dev.twitch.tv/console/apps"
              target="_blank"
              rel="noopener noreferrer"
              >dev.twitch.tv/console/apps</a
            >.
          </p>
          <label class="field">
            <span>Client ID</span>
            <input
              v-model="igdbClientId"
              type="text"
              autocomplete="off"
              placeholder="Paste your Twitch Client ID"
            />
          </label>
          <label class="field">
            <span>Client Secret</span>
            <PasswordInput
              v-model="igdbClientSecret"
              :placeholder="
                keyPlaceholder(
                  'igdb_client_secret',
                  igdbConfigured,
                  'Paste your Twitch Client Secret',
                )
              "
            />
          </label>
          <div v-if="igdbError" class="form-error">{{ igdbError }}</div>
          <div class="card-actions">
            <button type="submit" class="primary-button" :disabled="igdbSaving">
              {{ igdbSaving ? "Saving…" : "Save" }}
            </button>
            <button
              v-if="igdbConfigured"
              type="button"
              class="secondary-button"
              @click="clearIgdbCredentials"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- TMDB: deployment-wide, admin-only credentials -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{ background: VISUALS.TMDB.bg, color: VISUALS.TMDB.fg }"
        >
          {{ VISUALS.TMDB.mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name" :title="PROVIDER_CARDS.TMDB.description"
            >TMDB</span
          >
          <span
            v-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass('TMDB')"
            >{{ statusLabel("TMDB") }}</span
          >
        </div>
        <p class="tile-desc">{{ SHORT_DESC.TMDB }}</p>
        <div class="tile-actions">
          <button
            v-if="isAdmin"
            type="button"
            class="icon-btn"
            :class="{ active: expanded.TMDB }"
            title="Configure (admin only)"
            @click="toggleExpanded('TMDB')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
        </div>
        <p v-if="!isAdmin" class="tile-desc admin-note">
          Configured deployment-wide by your server administrator.
        </p>
        <form
          v-if="isAdmin && expanded.TMDB"
          class="tile-form"
          @submit.prevent="saveTmdbKey"
        >
          <p class="tile-desc admin-note">
            Applies to every user on this server, not just you. Register a free
            key at
            <a
              href="https://www.themoviedb.org/settings/api"
              target="_blank"
              rel="noopener noreferrer"
              >themoviedb.org/settings/api</a
            >.
          </p>
          <label class="field">
            <span>API Key</span>
            <PasswordInput
              v-model="tmdbApiKey"
              :placeholder="
                keyPlaceholder(
                  'tmdb_api_key',
                  tmdbConfigured,
                  'Paste your TMDB API key',
                )
              "
            />
          </label>
          <div v-if="tmdbError" class="form-error">{{ tmdbError }}</div>
          <div class="card-actions">
            <button type="submit" class="primary-button" :disabled="tmdbSaving">
              {{ tmdbSaving ? "Saving…" : "Save" }}
            </button>
            <button
              v-if="tmdbConfigured"
              type="button"
              class="secondary-button"
              @click="clearTmdbKey"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- OMDb: deployment-wide, admin-only credentials -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{ background: VISUALS.OMDb.bg, color: VISUALS.OMDb.fg }"
        >
          {{ VISUALS.OMDb.mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name" :title="PROVIDER_CARDS.OMDb.description"
            >OMDb</span
          >
          <span
            v-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass('OMDb')"
            >{{ statusLabel("OMDb") }}</span
          >
        </div>
        <p class="tile-desc">{{ SHORT_DESC.OMDb }}</p>
        <div class="tile-actions">
          <button
            v-if="isAdmin"
            type="button"
            class="icon-btn"
            :class="{ active: expanded.OMDb }"
            title="Configure (admin only)"
            @click="toggleExpanded('OMDb')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
        </div>
        <p v-if="!isAdmin" class="tile-desc admin-note">
          Configured deployment-wide by your server administrator.
        </p>
        <form
          v-if="isAdmin && expanded.OMDb"
          class="tile-form"
          @submit.prevent="saveOmdbKey"
        >
          <p class="tile-desc admin-note">
            Applies to every user on this server, not just you. Register a free
            key at
            <a
              href="https://www.omdbapi.com/apikey.aspx"
              target="_blank"
              rel="noopener noreferrer"
              >omdbapi.com/apikey.aspx</a
            >.
          </p>
          <label class="field">
            <span>API Key</span>
            <PasswordInput
              v-model="omdbApiKey"
              :placeholder="
                keyPlaceholder(
                  'omdb_api_key',
                  omdbConfigured,
                  'Paste your OMDb API key',
                )
              "
            />
          </label>
          <div v-if="omdbError" class="form-error">{{ omdbError }}</div>
          <div class="card-actions">
            <button type="submit" class="primary-button" :disabled="omdbSaving">
              {{ omdbSaving ? "Saving…" : "Save" }}
            </button>
            <button
              v-if="omdbConfigured"
              type="button"
              class="secondary-button"
              @click="clearOmdbKey"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- TVDB: deployment-wide, admin-only credentials -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{ background: VISUALS.TVDB.bg, color: VISUALS.TVDB.fg }"
        >
          {{ VISUALS.TVDB.mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name" :title="PROVIDER_CARDS.TVDB.description"
            >TheTVDB</span
          >
          <span
            v-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass('TVDB')"
            >{{ statusLabel("TVDB") }}</span
          >
        </div>
        <p class="tile-desc">{{ SHORT_DESC.TVDB }}</p>
        <div class="tile-actions">
          <button
            v-if="isAdmin"
            type="button"
            class="icon-btn"
            :class="{ active: expanded.TVDB }"
            title="Configure (admin only)"
            @click="toggleExpanded('TVDB')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
        </div>
        <p v-if="!isAdmin" class="tile-desc admin-note">
          Configured deployment-wide by your server administrator.
        </p>
        <form
          v-if="isAdmin && expanded.TVDB"
          class="tile-form"
          @submit.prevent="saveTvdbKey"
        >
          <p class="tile-desc admin-note">
            Applies to every user on this server, not just you. Register a free
            key at
            <a
              href="https://thetvdb.com/api-information"
              target="_blank"
              rel="noopener noreferrer"
              >thetvdb.com/api-information</a
            >.
          </p>
          <label class="field">
            <span>API Key</span>
            <PasswordInput
              v-model="tvdbApiKey"
              :placeholder="
                keyPlaceholder(
                  'tvdb_api_key',
                  tvdbConfigured,
                  'Paste your TVDB API key',
                )
              "
            />
          </label>
          <div v-if="tvdbError" class="form-error">{{ tvdbError }}</div>
          <div class="card-actions">
            <button type="submit" class="primary-button" :disabled="tvdbSaving">
              {{ tvdbSaving ? "Saving…" : "Save" }}
            </button>
            <button
              v-if="tvdbConfigured"
              type="button"
              class="secondary-button"
              @click="clearTvdbKey"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- generic wired-provider tiles -->
      <div
        v-for="key in ['GiantBomb', 'ScreenScraper']"
        :key="key"
        class="source-tile"
      >
        <div
          class="tile-icon"
          :style="{ background: VISUALS[key].bg, color: VISUALS[key].fg }"
        >
          {{ VISUALS[key].mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name" :title="PROVIDER_CARDS[key].description">{{
            PROVIDER_CARDS[key].label
          }}</span>
          <span
            v-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass(key)"
            >{{ statusLabel(key) }}</span
          >
        </div>
        <p class="tile-desc">{{ SHORT_DESC[key] }}</p>
        <div class="tile-actions">
          <button
            v-if="PROVIDER_CARDS[key].fields.length"
            type="button"
            class="icon-btn"
            :class="{ active: expanded[key] }"
            title="Configure"
            @click="toggleExpanded(key)"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
          <a
            v-if="PROVIDER_CARDS[key].linkUrl"
            class="icon-btn"
            :href="PROVIDER_CARDS[key].linkUrl"
            target="_blank"
            rel="noopener noreferrer"
            title="Get a free key"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <path
                d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
              />
            </svg>
          </a>
        </div>
        <form
          v-if="expanded[key] && PROVIDER_CARDS[key].fields.length"
          class="tile-form"
          @submit.prevent="saveCard(PROVIDER_CARDS[key])"
        >
          <label
            v-for="field in PROVIDER_CARDS[key].fields"
            :key="field.key"
            class="field"
          >
            <span>{{ field.label }}</span>
            <PasswordInput
              v-if="field.type === 'password'"
              v-model="fieldValues[key][field.key]"
              :placeholder="passwordPlaceholder(key, field.key, field.label)"
            />
            <input
              v-else
              v-model="fieldValues[key][field.key]"
              type="text"
              autocomplete="off"
              :placeholder="`Paste your ${field.label.toLowerCase()}`"
            />
          </label>
          <div v-if="cardError[key]" class="form-error">
            {{ cardError[key] }}
          </div>
          <div class="card-actions">
            <button
              type="submit"
              class="primary-button"
              :disabled="cardSaving[key]"
            >
              {{ cardSaving[key] ? "Saving…" : "Save" }}
            </button>
            <button
              v-if="statusClass(key) !== 'disconnected'"
              type="button"
              class="secondary-button"
              @click="clearCard(PROVIDER_CARDS[key])"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- GOG -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{ background: VISUALS.GOG.bg, color: VISUALS.GOG.fg }"
        >
          {{ VISUALS.GOG.mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name" :title="PROVIDER_CARDS.GOG.description"
            >GOG</span
          >
          <span
            v-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass('GOG')"
            >{{ statusLabel("GOG") }}</span
          >
        </div>
        <p class="tile-desc">{{ SHORT_DESC.GOG }}</p>
        <div class="tile-actions">
          <button
            type="button"
            class="icon-btn"
            :class="{ active: expanded.GOG }"
            title="Configure"
            @click="toggleExpanded('GOG')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
        </div>
        <form
          v-if="expanded.GOG"
          class="tile-form"
          @submit.prevent="saveCard(PROVIDER_CARDS.GOG)"
        >
          <label
            v-for="field in PROVIDER_CARDS.GOG.fields"
            :key="field.key"
            class="field"
          >
            <span>{{ field.label }}</span>
            <PasswordInput
              v-model="fieldValues.GOG[field.key]"
              :placeholder="passwordPlaceholder('GOG', field.key, field.label)"
            />
          </label>
          <div v-if="cardError.GOG" class="form-error">{{ cardError.GOG }}</div>
          <div class="card-actions">
            <button
              type="submit"
              class="primary-button"
              :disabled="cardSaving.GOG"
            >
              {{ cardSaving.GOG ? "Saving…" : "Save" }}
            </button>
            <button
              v-if="statusClass('GOG') !== 'disconnected'"
              type="button"
              class="secondary-button"
              @click="clearCard(PROVIDER_CARDS.GOG)"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- LaunchBox: unavailable -->
      <div
        class="source-tile unavailable"
        title="Local Windows app with an offline XML export, not a cloud API this server can call."
      >
        <div
          class="tile-icon"
          :style="{
            background: VISUALS.LaunchBox.bg,
            color: VISUALS.LaunchBox.fg,
          }"
        >
          {{ VISUALS.LaunchBox.mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name">LaunchBox</span>
          <span class="tile-status disconnected">Not available</span>
        </div>
        <p class="tile-desc">{{ SHORT_DESC.LaunchBox }}</p>
        <div class="tile-actions"></div>
      </div>
    </div>

    <h3 class="group-heading">Achievements &amp; Accounts</h3>

    <div class="source-grid">
      <!-- Steam -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{ background: VISUALS.Steam.bg, color: VISUALS.Steam.fg }"
        >
          {{ VISUALS.Steam.mark }}
        </div>
        <div class="tile-body">
          <span
            class="tile-name"
            title="Metadata search needs no account. Importing your library and achievements needs a Web API key + your profile."
            >Steam</span
          >
          <span
            v-if="credentialStatus.Steam?.display_name"
            class="tile-profile"
          >
            <img
              v-if="credentialStatus.Steam.avatar_url"
              :src="credentialStatus.Steam.avatar_url"
              class="tile-avatar"
              alt=""
            />
            {{ credentialStatus.Steam.display_name }}
          </span>
          <span
            v-else-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass('Steam')"
            >{{ statusLabel("Steam") }}</span
          >
        </div>
        <p class="tile-desc">
          {{ formatLastSynced(credentialStatus.Steam) ?? SHORT_DESC.Steam }}
        </p>
        <div class="tile-actions">
          <button
            type="button"
            class="icon-btn"
            :class="{ active: expanded.Steam }"
            title="Connect account to import your library"
            @click="toggleExpanded('Steam')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
        </div>
        <button
          v-if="statusClass('Steam') !== 'disconnected'"
          type="button"
          class="import-button"
          :disabled="librarySyncing.steam"
          @click="handleSyncLibrary('steam')"
        >
          <svg
            viewBox="0 0 24 24"
            width="14"
            height="14"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M23 4v6h-6M1 20v-6h6" />
            <path
              d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"
            />
          </svg>
          {{ librarySyncing.steam ? "Importing…" : "Import Library" }}
        </button>
        <form
          v-if="expanded.Steam"
          class="tile-form"
          @submit.prevent="saveCard(PROVIDER_CARDS.Steam)"
        >
          <p class="tile-hint">
            Both fields are required to import your library: your profile ID
            (after steamcommunity.com/id/, not the full link) and a Web API key.
            Your profile's game details must be set to Public.
          </p>
          <label
            v-for="field in PROVIDER_CARDS.Steam.fields"
            :key="field.key"
            class="field"
          >
            <span>{{ field.label }}</span>
            <PasswordInput
              v-if="field.type === 'password'"
              v-model="fieldValues.Steam[field.key]"
              :placeholder="
                passwordPlaceholder('Steam', field.key, field.label)
              "
            />
            <input
              v-else
              v-model="fieldValues.Steam[field.key]"
              type="text"
              autocomplete="off"
              :placeholder="`Paste your ${field.label.toLowerCase()}`"
            />
          </label>
          <div v-if="cardError.Steam" class="form-error">
            {{ cardError.Steam }}
          </div>
          <div v-if="cardInfo.Steam" class="form-success">
            {{ cardInfo.Steam }}
          </div>
          <div class="card-actions">
            <button
              type="submit"
              class="primary-button"
              :disabled="cardSaving.Steam"
            >
              {{ cardSaving.Steam ? "Connecting…" : "Connect" }}
            </button>
            <button
              v-if="statusClass('Steam') !== 'disconnected'"
              type="button"
              class="secondary-button"
              @click="clearCard(PROVIDER_CARDS.Steam)"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- RetroAchievements -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{
            background: VISUALS.RetroAchievements.bg,
            color: VISUALS.RetroAchievements.fg,
          }"
        >
          {{ VISUALS.RetroAchievements.mark }}
        </div>
        <div class="tile-body">
          <span
            class="tile-name"
            :title="PROVIDER_CARDS.RetroAchievements.description"
            >RetroAchievements</span
          >
          <span
            v-if="credentialStatus.RetroAchievements?.display_name"
            class="tile-profile"
          >
            <img
              v-if="credentialStatus.RetroAchievements.avatar_url"
              :src="credentialStatus.RetroAchievements.avatar_url"
              class="tile-avatar"
              alt=""
            />
            {{ credentialStatus.RetroAchievements.display_name }}
          </span>
          <span
            v-else-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass('RetroAchievements')"
          >
            {{ statusLabel("RetroAchievements") }}
          </span>
        </div>
        <p class="tile-desc">{{ SHORT_DESC.RetroAchievements }}</p>
        <div class="tile-actions">
          <button
            type="button"
            class="icon-btn"
            :class="{ active: expanded.RetroAchievements }"
            title="Configure"
            @click="toggleExpanded('RetroAchievements')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
          <a
            class="icon-btn"
            :href="PROVIDER_CARDS.RetroAchievements.linkUrl"
            target="_blank"
            rel="noopener noreferrer"
            title="Get a free key"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <path
                d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
              />
            </svg>
          </a>
        </div>
        <button
          v-if="statusClass('RetroAchievements') !== 'disconnected'"
          type="button"
          class="import-button"
          :disabled="librarySyncing.retroachievements"
          @click="handleSyncLibrary('retroachievements')"
        >
          <svg
            viewBox="0 0 24 24"
            width="14"
            height="14"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M23 4v6h-6M1 20v-6h6" />
            <path
              d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"
            />
          </svg>
          {{
            librarySyncing.retroachievements ? "Importing…" : "Import Library"
          }}
        </button>
        <form
          v-if="expanded.RetroAchievements"
          class="tile-form"
          @submit.prevent="saveCard(PROVIDER_CARDS.RetroAchievements)"
        >
          <label
            v-for="field in PROVIDER_CARDS.RetroAchievements.fields"
            :key="field.key"
            class="field"
          >
            <span>{{ field.label }}</span>
            <PasswordInput
              v-if="field.type === 'password'"
              v-model="fieldValues.RetroAchievements[field.key]"
              :placeholder="
                passwordPlaceholder('RetroAchievements', field.key, field.label)
              "
            />
            <input
              v-else
              v-model="fieldValues.RetroAchievements[field.key]"
              type="text"
              autocomplete="off"
              :placeholder="`Paste your ${field.label.toLowerCase()}`"
            />
          </label>
          <div v-if="cardError.RetroAchievements" class="form-error">
            {{ cardError.RetroAchievements }}
          </div>
          <div class="card-actions">
            <button
              type="submit"
              class="primary-button"
              :disabled="cardSaving.RetroAchievements"
            >
              {{ cardSaving.RetroAchievements ? "Saving…" : "Save" }}
            </button>
            <button
              v-if="statusClass('RetroAchievements') !== 'disconnected'"
              type="button"
              class="secondary-button"
              @click="clearCard(PROVIDER_CARDS.RetroAchievements)"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- PlayStation -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{
            background: VISUALS.PlayStation.bg,
            color: VISUALS.PlayStation.fg,
          }"
        >
          {{ VISUALS.PlayStation.mark }}
        </div>
        <div class="tile-body">
          <span
            class="tile-name"
            title="Unofficial npsso token flow. Also powers PSN Store data."
            >PlayStation</span
          >
          <span
            v-if="psnStatus.connected && psnStatus.display_name"
            class="tile-profile"
          >
            <img
              v-if="psnStatus.avatar_url"
              :src="psnStatus.avatar_url"
              class="tile-avatar"
              alt=""
            />
            {{ psnStatus.display_name }}
          </span>
          <span
            v-else-if="!psnLoading"
            class="tile-status"
            :class="psnStatus.connected ? 'connected' : 'disconnected'"
          >
            {{ psnStatus.connected ? "Connected" : "Not connected" }}
          </span>
        </div>
        <p class="tile-desc">{{ SHORT_DESC.PlayStation }}</p>
        <div class="tile-actions">
          <button
            type="button"
            class="icon-btn"
            :class="{ active: expanded.PlayStation }"
            title="Configure"
            @click="toggleExpanded('PlayStation')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
          <a
            class="icon-btn"
            href="https://www.playstation.com"
            target="_blank"
            rel="noopener noreferrer"
            title="playstation.com"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <path
                d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
              />
            </svg>
          </a>
        </div>
        <button
          v-if="psnStatus.connected"
          type="button"
          class="import-button"
          :disabled="librarySyncing.psn"
          @click="handleSyncLibrary('psn')"
        >
          <svg
            viewBox="0 0 24 24"
            width="14"
            height="14"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M23 4v6h-6M1 20v-6h6" />
            <path
              d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"
            />
          </svg>
          {{ librarySyncing.psn ? "Importing…" : "Import Library" }}
        </button>
        <div v-if="expanded.PlayStation" class="tile-form">
          <template v-if="!psnLoading">
            <template v-if="!psnStatus.connected">
              <label class="field">
                <span>npsso token</span>
                <PasswordInput
                  v-model="npssoToken"
                  placeholder="Paste your npsso token"
                />
              </label>
              <div v-if="psnError" class="form-error">{{ psnError }}</div>
              <button
                type="button"
                class="primary-button"
                :disabled="psnConnecting"
                @click="handleConnectPsn"
              >
                {{ psnConnecting ? "Connecting…" : "Connect" }}
              </button>
            </template>
            <template v-else>
              <p class="tile-hint">
                Connected: reconnect with a fresh token to re-check it.
              </p>
              <div v-if="psnError" class="form-error">{{ psnError }}</div>
              <button
                type="button"
                class="secondary-button"
                @click="showDisconnectConfirm = true"
              >
                Disconnect
              </button>
            </template>
          </template>
        </div>
      </div>

      <!-- Xbox -->
      <div class="source-tile">
        <div
          class="tile-icon"
          :style="{ background: VISUALS.Xbox.bg, color: VISUALS.Xbox.fg }"
        >
          {{ VISUALS.Xbox.mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name" :title="PROVIDER_CARDS.Xbox.description"
            >Xbox</span
          >
          <span
            v-if="!credentialsLoading"
            class="tile-status"
            :class="statusClass('Xbox')"
            >{{ statusLabel("Xbox") }}</span
          >
        </div>
        <p class="tile-desc">{{ SHORT_DESC.Xbox }}</p>
        <div class="tile-actions">
          <button
            type="button"
            class="icon-btn"
            :class="{ active: expanded.Xbox }"
            title="Configure"
            @click="toggleExpanded('Xbox')"
          >
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
              />
            </svg>
          </button>
        </div>
        <form
          v-if="expanded.Xbox"
          class="tile-form"
          @submit.prevent="saveCard(PROVIDER_CARDS.Xbox)"
        >
          <label
            v-for="field in PROVIDER_CARDS.Xbox.fields"
            :key="field.key"
            class="field"
          >
            <span>{{ field.label }}</span>
            <PasswordInput
              v-if="field.type === 'password'"
              v-model="fieldValues.Xbox[field.key]"
              :placeholder="passwordPlaceholder('Xbox', field.key, field.label)"
            />
            <input
              v-else
              v-model="fieldValues.Xbox[field.key]"
              type="text"
              autocomplete="off"
              :placeholder="`Paste your ${field.label.toLowerCase()}`"
            />
          </label>
          <div v-if="cardError.Xbox" class="form-error">
            {{ cardError.Xbox }}
          </div>
          <div class="card-actions">
            <button
              type="submit"
              class="primary-button"
              :disabled="cardSaving.Xbox"
            >
              {{ cardSaving.Xbox ? "Saving…" : "Save" }}
            </button>
            <button
              v-if="statusClass('Xbox') !== 'disconnected'"
              type="button"
              class="secondary-button"
              @click="clearCard(PROVIDER_CARDS.Xbox)"
            >
              Disconnect
            </button>
          </div>
        </form>
      </div>

      <!-- HowLongToBeat -->
      <div
        class="source-tile"
        title="No key needed. HLTB's anti-bot protection can make this fail silently: that's not a bug in your setup."
      >
        <div
          class="tile-icon"
          :style="{
            background: VISUALS.HowLongToBeat.bg,
            color: VISUALS.HowLongToBeat.fg,
          }"
        >
          {{ VISUALS.HowLongToBeat.mark }}
        </div>
        <div class="tile-body">
          <span class="tile-name">HowLongToBeat</span>
          <span
            v-if="!hltbLoading"
            class="tile-status"
            :class="hltbEnabled ? 'connected' : 'disconnected'"
          >
            {{ hltbEnabled ? "Enabled" : "Disabled" }}
          </span>
        </div>
        <p class="tile-desc">{{ hltbError ?? SHORT_DESC.HowLongToBeat }}</p>
        <div class="tile-actions">
          <button
            type="button"
            class="mini-switch"
            :class="{ on: hltbEnabled }"
            role="switch"
            :aria-checked="hltbEnabled"
            :disabled="hltbLoading || hltbSaving"
            title="Enable HowLongToBeat"
            @click="toggleHltb(!hltbEnabled)"
          >
            <span class="mini-switch-knob"></span>
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="showDisconnectConfirm"
      class="confirm-backdrop"
      @click.self="showDisconnectConfirm = false"
    >
      <div class="confirm-dialog">
        <h3>Disconnect PlayStation account?</h3>
        <p>You'll need to paste your npsso token again to reconnect.</p>
        <div class="confirm-actions">
          <button
            type="button"
            class="secondary-button"
            @click="showDisconnectConfirm = false"
          >
            Cancel
          </button>
          <button
            type="button"
            class="danger-button"
            @click="confirmDisconnectPsn"
          >
            Disconnect
          </button>
        </div>
      </div>
    </div>
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
.section-hint {
  color: #999;
  font-size: 0.82rem;
  line-height: 1.6;
  margin: 0 0 16px;
}
.group-heading {
  color: #999;
  font-size: 0.76rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 20px 0 10px;
}
.group-heading:first-of-type {
  margin-top: 4px;
}
.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 8px;
  margin-bottom: 8px;
  align-items: start;
}
.source-tile {
  display: flex;
  flex-direction: column;
  min-height: 148px;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 10px;
  transition:
    transform 0.15s ease,
    border-color 0.15s ease;
}
.source-tile:hover {
  transform: translateY(-1px);
  border-color: #3a3a3a;
}
.source-tile.unavailable {
  opacity: 0.55;
}
.source-tile.unavailable:hover {
  transform: none;
}
.tile-icon {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.02em;
  flex-shrink: 0;
  margin-bottom: 8px;
}
.tile-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin-bottom: 8px;
  min-width: 0;
}
.tile-name {
  color: #fff;
  font-weight: 600;
  font-size: 0.82rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}
.tile-status {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.tile-status.connected {
  color: #86efac;
}
.tile-status.saved {
  color: #999;
}
.tile-status.error {
  color: #fca5a5;
}
.tile-status.disconnected {
  color: #777;
}
.tile-profile {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #ccc;
  font-size: 0.72rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tile-avatar {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  flex-shrink: 0;
  object-fit: cover;
}
.tile-desc {
  color: #888;
  font-size: 0.68rem;
  line-height: 1.4;
  margin: 0 0 8px;
  height: 2.8em;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tile-desc.admin-note {
  height: auto;
  display: block;
  -webkit-line-clamp: unset;
}
.tile-desc.admin-note a {
  color: #d68a34;
}
.tile-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  margin-top: auto;
}
.icon-btn {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.08);
  color: #ccc;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.icon-btn:hover {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}
.icon-btn.active {
  background: rgba(214, 138, 52, 0.22);
  color: #d68a34;
}
.mini-switch {
  width: 30px;
  height: 17px;
  border-radius: 999px;
  border: none;
  background: #3a3a3a;
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease;
}
.mini-switch.on {
  background: #d68a34;
}
.mini-switch:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mini-switch-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.15s ease;
}
.mini-switch.on .mini-switch-knob {
  transform: translateX(13px);
}
.import-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  margin-top: 8px;
  background: rgba(214, 138, 52, 0.14);
  color: #d68a34;
  border: 1px solid rgba(214, 138, 52, 0.35);
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}
.import-button:hover:not(:disabled) {
  background: rgba(214, 138, 52, 0.24);
}
.import-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.tile-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #232323;
}
.tile-hint {
  color: #999;
  font-size: 0.72rem;
  line-height: 1.5;
  margin: 0;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.72rem;
  color: #ccc;
}
.field input {
  background: #1a1a1a;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  color: #fff;
  padding: 7px 9px;
  font: inherit;
  font-size: 0.78rem;
}
.field input:focus {
  outline: none;
  border-color: #d68a34;
}
.card-actions {
  display: flex;
  gap: 8px;
}
.form-error {
  color: #fca5a5;
  font-size: 12px;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 6px;
  padding: 6px 8px;
}
.form-success {
  color: #86efac;
  font-size: 12px;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 6px;
  padding: 6px 8px;
}
.primary-button {
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}
.primary-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.secondary-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 7px 12px;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}
.secondary-button:hover {
  background: rgba(255, 255, 255, 0.14);
}
.confirm-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}
.confirm-dialog {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 22px;
  max-width: 360px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}
.confirm-dialog h3 {
  margin: 0 0 8px;
  color: #fff;
}
.confirm-dialog p {
  margin: 0 0 18px;
  color: #999;
  font-size: 0.85rem;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.danger-button {
  background: rgba(220, 38, 38, 0.18);
  color: #fca5a5;
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-weight: 600;
  cursor: pointer;
}
</style>
