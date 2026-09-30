<script setup lang="ts">
import { onMounted, ref } from "vue";
import PluginInstallConsentDialog from "../plugins/PluginInstallConsentDialog.vue";
import PluginSettingsDialog from "../plugins/PluginSettingsDialog.vue";
import {
  deletePlugin,
  disablePlugin,
  enablePlugin,
  fetchPluginCatalog,
  fetchPluginLogs,
  fetchPlugins,
  installPlugin,
  installPluginFromUrl,
  previewPluginInstall,
  previewPluginInstallUrl,
  retryPlugin,
  updatePlugin,
  type PluginInstallPreview,
  type PluginCatalogEntry,
  type PluginDiagnostics,
  type PluginSummary,
} from "../../services/plugins";
import {
  approvePluginPermission,
  denyPluginPermission,
  fetchPluginPermissionGrants,
  fetchPluginPermissionRequests,
  revokePluginPermission,
  type PluginPermissionGrant,
  type PluginPermissionRequest,
} from "../../services/pluginPermissions";
import {
  fetchPluginUi,
  type PluginUiDocument,
  type UiAction,
  type UiValues,
} from "../../services/pluginUi";

const plugins = ref<PluginSummary[]>([]);
const catalog = ref<PluginCatalogEntry[]>([]);
const loading = ref(true);
const error = ref("");
const action = ref("");
const selectedFile = ref<File | null>(null);
const installFile = ref<File | null>(null);
const installUrl = ref<string | null>(null);
const remoteUrl = ref("");
const installPreview = ref<PluginInstallPreview | null>(null);
const previewing = ref(false);
const installing = ref(false);
const installMessage = ref("");
const selected = ref<PluginSummary | null>(null);
const pluginUi = ref<PluginUiDocument | null>(null);
const pluginDiagnostics = ref<PluginDiagnostics | null>(null);
const pluginGrants = ref<PluginPermissionGrant[]>([]);
const pluginRequests = ref<PluginPermissionRequest[]>([]);
const popupLoading = ref(false);
const installOpen = ref(false);
const catalogEndpoints = ref<string[]>([]);
const enabledCatalogEndpoints = ref<string[]>([]);
const newCatalogEndpoint = ref("");
const officialCatalogUrl = "https://raw.githubusercontent.com/Rosefall-a/unnamed_tracking_app_plugins/main/list.json";

function loadCatalogEndpoints() {
  try {
    const stored = JSON.parse(localStorage.getItem("plugin-catalog-endpoints") || "{}") as
      | { endpoints?: unknown; enabled?: unknown }
      | unknown[];
    const endpoints = Array.isArray(stored) ? stored : stored.endpoints;
    if (Array.isArray(endpoints)) {
      catalogEndpoints.value = [
        officialCatalogUrl,
        ...endpoints.filter(
          (value: unknown): value is string =>
            typeof value === "string" &&
            value.trim().length > 0 &&
            value !== officialCatalogUrl,
        ),
      ];
      const enabled = Array.isArray(stored)
        ? stored
        : Array.isArray(stored.enabled)
          ? stored.enabled
          : catalogEndpoints.value;
      enabledCatalogEndpoints.value = [...new Set(enabled)].filter(
        (url): url is string =>
          typeof url === "string" && catalogEndpoints.value.includes(url),
      );
      return;
    }
  } catch {
    // Fall back to the official source.
  }
  catalogEndpoints.value = [officialCatalogUrl];
  enabledCatalogEndpoints.value = [officialCatalogUrl];
}

function saveCatalogEndpoints() {
  localStorage.setItem("plugin-catalog-endpoints", JSON.stringify({ endpoints: catalogEndpoints.value.filter((url) => url !== officialCatalogUrl), enabled: enabledCatalogEndpoints.value }));
}

function addCatalogEndpoint() {
  const url = newCatalogEndpoint.value.trim();
  if (!/^https?:\/\//i.test(url) || catalogEndpoints.value.includes(url)) return;
  catalogEndpoints.value.push(url);
  enabledCatalogEndpoints.value.push(url);
  newCatalogEndpoint.value = "";
  saveCatalogEndpoints();
  void loadCatalogues();
}

function removeCatalogEndpoint(url: string) {
  if (url === officialCatalogUrl) return;
  catalogEndpoints.value = catalogEndpoints.value.filter((item) => item !== url);
  enabledCatalogEndpoints.value = enabledCatalogEndpoints.value.filter((item) => item !== url);
  saveCatalogEndpoints();
  void loadCatalogues();
}

function toggleCatalogEndpoint(url: string, enabled: boolean) {
  if (enabled && !enabledCatalogEndpoints.value.includes(url)) enabledCatalogEndpoints.value.push(url);
  if (!enabled) enabledCatalogEndpoints.value = enabledCatalogEndpoints.value.filter((item) => item !== url);
  saveCatalogEndpoints();
  void loadCatalogues();
}

async function loadCatalogues() {
  const results = await Promise.all(enabledCatalogEndpoints.value.map((url) => fetchPluginCatalog(url).catch(() => [])));
  const seen = new Set<string>();
  catalog.value = results.flat().filter((entry) => {
    if (seen.has(entry.plugin_id)) return false;
    seen.add(entry.plugin_id);
    return true;
  });
}

function openInstaller() {
  installOpen.value = true;
  loadCatalogEndpoints();
  void loadCatalogues();
}

function closeInstaller() {
  if (installing.value) return;
  installOpen.value = false;
  newCatalogEndpoint.value = "";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    plugins.value = await fetchPlugins();
    if (!catalogEndpoints.value.length) loadCatalogEndpoints();
    await loadCatalogues();
    if (selected.value) {
      selected.value =
        plugins.value.find(
          (item) => item.plugin_id === selected.value?.plugin_id,
        ) ?? null;
    }
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Plugin manager is unavailable.";
  } finally {
    loading.value = false;
  }
}

async function run(id: string, operation: (id: string) => Promise<void>) {
  action.value = id;
  error.value = "";
  try {
    await operation(id);
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Plugin action failed.";
  } finally {
    action.value = "";
  }
}

function selectFile(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null;
  installMessage.value = "";
}

async function previewSelected() {
  if (!selectedFile.value) return;
  previewing.value = true;
  error.value = "";
  installMessage.value = "";
  try {
    installUrl.value = null;
    installFile.value = selectedFile.value;
    installPreview.value = await previewPluginInstall(selectedFile.value);
  } catch (err) {
    installFile.value = null;
    installPreview.value = null;
    error.value = err instanceof Error ? err.message : "Plugin preview failed.";
  } finally {
    previewing.value = false;
  }
}

async function previewRemoteUrl(url = remoteUrl.value) {
  const normalized = url.trim();
  if (!normalized) return;
  previewing.value = true;
  error.value = "";
  installMessage.value = "";
  try {
    installFile.value = null;
    installUrl.value = normalized;
    installPreview.value = await previewPluginInstallUrl(normalized);
  } catch (err) {
    installUrl.value = null;
    installPreview.value = null;
    error.value = err instanceof Error ? err.message : "Plugin URL preview failed.";
  } finally {
    previewing.value = false;
  }
}

async function previewCatalogEntry(url: string) {
  error.value = "";
  await previewRemoteUrl(url);
}

function cancelInstall() {
  if (installing.value) return;
  installFile.value = null;
  installUrl.value = null;
  installPreview.value = null;
}

async function confirmInstall(approvedPermissions: string[]) {
  if (!installFile.value || !installPreview.value) return;
  installing.value = true;
  error.value = "";
  try {
    const result = installUrl.value
      ? await installPluginFromUrl(installUrl.value, approvedPermissions, installPreview.value.digest, installPreview.value.trust_status === "untrusted")
      : await installPlugin(installFile.value!, approvedPermissions, installPreview.value.trust_status === "untrusted");
    installMessage.value =
      `Installed ${result.name} v${result.version}; ` +
      `${result.permissions_granted} permission(s) granted and ${result.permissions_denied} denied.`;
    selectedFile.value = null;
    installFile.value = null;
    installUrl.value = null;
    remoteUrl.value = "";
    installPreview.value = null;
    await load();
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Plugin installation failed.";
  } finally {
    installing.value = false;
  }
}

async function openPlugin(plugin: PluginSummary) {
  selected.value = plugin;
  popupLoading.value = true;
  error.value = "";
  try {
    const [ui, logs, grants, requests] = await Promise.all([
      fetchPluginUi(plugin.plugin_id),
      fetchPluginLogs(plugin.plugin_id),
      fetchPluginPermissionGrants(),
      fetchPluginPermissionRequests(),
    ]);
    pluginUi.value = ui;
    pluginDiagnostics.value = logs;
    pluginGrants.value = grants.filter(
      (grant) => grant.plugin_id === plugin.plugin_id,
    );
    pluginRequests.value = requests.filter(
      (request) =>
        request.plugin_id === plugin.plugin_id && request.status === "pending",
    );
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Failed to open plugin settings.";
  } finally {
    popupLoading.value = false;
  }
}

function closePlugin() {
  selected.value = null;
  pluginUi.value = null;
  pluginDiagnostics.value = null;
  pluginGrants.value = [];
  pluginRequests.value = [];
}

async function refreshPlugin() {
  if (selected.value) await openPlugin(selected.value);
}

async function runSelected(operation: (id: string) => Promise<void>) {
  if (!selected.value) return;
  await run(selected.value.plugin_id, operation);
  await refreshPlugin();
}

async function revokeGrant(grantId: string) {
  if (!selected.value) return;
  action.value = selected.value.plugin_id;
  try {
    await revokePluginPermission(grantId);
    await refreshPlugin();
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Permission revocation failed.";
  } finally {
    action.value = "";
  }
}

async function resolveRequest(requestId: string, approved: boolean) {
  if (!selected.value) return;
  action.value = selected.value.plugin_id;
  try {
    await (approved
      ? approvePluginPermission(requestId)
      : denyPluginPermission(requestId));
    await refreshPlugin();
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Permission review failed.";
  } finally {
    action.value = "";
  }
}

async function savePlugin(values: UiValues) {
  if (!selected.value) return;
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(selected.value.plugin_id)}/settings`,
    {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    },
  );
  if (!response.ok) throw new Error("Plugin settings could not be saved.");
}

async function runPluginAction(item: UiAction, values: UiValues) {
  if (!selected.value) return;
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(selected.value.plugin_id)}/actions/${encodeURIComponent(item.id)}`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    },
  );
  if (!response.ok) throw new Error("Plugin action could not be completed.");
  await refreshPlugin();
}

async function updateSelected(plugin: PluginSummary, event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  action.value = plugin.plugin_id;
  error.value = "";
  try {
    const result = await updatePlugin(plugin.plugin_id, file);
    installMessage.value =
      `Updated ${plugin.name} to v${result.version}. ` +
      `${result.permissions_requested} new permission request(s) require review.`;
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Plugin update failed.";
  } finally {
    action.value = "";
    input.value = "";
  }
}

async function removePlugin(plugin: PluginSummary) {
  if (!window.confirm(`Delete ${plugin.name} and its stored plugin data?`))
    return;
  action.value = plugin.plugin_id;
  error.value = "";
  try {
    await deletePlugin(plugin.plugin_id);
    if (selected.value?.plugin_id === plugin.plugin_id) closePlugin();
    await load();
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Plugin deletion failed.";
  } finally {
    action.value = "";
  }
}

onMounted(() => {
  loadCatalogEndpoints();
  void load();
});
</script>

<template>
  <section>
    <h2>Plugins</h2>
    <p class="muted">
      Upload a plugin package (the filename extension is ignored), review its identity and requested
      access, then manage it here.
    </p>
    <div class="installer-launcher">
      <button type="button" class="primary install-launcher" @click="openInstaller">Install a plugin</button>
      <p class="muted">Add a package, install from a URL, or browse enabled plugin catalogues.</p>
      <p v-if="installMessage" class="success">{{ installMessage }}</p>
    </div>
    <Teleport to="body">
      <div v-if="installOpen" class="modal-backdrop" @click.self="closeInstaller">
        <section class="installer-dialog" role="dialog" aria-modal="true" aria-labelledby="plugin-installer-title">
          <header class="dialog-header">
            <div><p class="eyebrow">Plugin manager</p><h2 id="plugin-installer-title">Install a plugin</h2><p class="muted">Choose a package, URL, or enabled catalogue.</p></div>
            <button type="button" :disabled="installing" @click="closeInstaller">Close</button>
          </header>
          <div class="install-method">
            <strong>Upload package</strong>
            <input id="plugin-package" type="file" accept="*/*" @change="selectFile" />
            <button type="button" :disabled="!selectedFile || previewing" @click="previewSelected">{{ previewing ? "Inspecting…" : "Review package" }}</button>
          </div>
          <div class="install-method">
            <strong>Install from URL</strong>
            <div class="url-row"><input v-model="remoteUrl" type="url" placeholder="https://example.com/plugin.utp" @keyup.enter="previewRemoteUrl()" /><button type="button" :disabled="!remoteUrl.trim() || previewing" @click="previewRemoteUrl()">Review URL</button></div>
          </div>
          <section class="catalogue">
            <div class="catalogue-header"><div><strong>Plugin catalogues</strong><p class="muted">The official catalogue is enabled by default. Add other trusted catalogue URLs as needed.</p></div></div>
            <div v-for="endpoint in catalogEndpoints" :key="endpoint" class="endpoint-row">
              <label><input type="checkbox" :checked="enabledCatalogEndpoints.includes(endpoint)" @change="toggleCatalogEndpoint(endpoint, ($event.target as HTMLInputElement).checked)" /> {{ endpoint === officialCatalogUrl ? "Official" : endpoint }}</label>
              <button v-if="endpoint !== officialCatalogUrl" type="button" class="danger" @click="removeCatalogEndpoint(endpoint)">Remove</button>
            </div>
            <div class="endpoint-add"><input v-model="newCatalogEndpoint" type="url" placeholder="https://example.com/list.json" @keyup.enter="addCatalogEndpoint" /><button type="button" :disabled="!newCatalogEndpoint.trim()" @click="addCatalogEndpoint">Add catalogue</button></div>
          </section>
          <section class="catalogue">
            <div class="catalogue-header"><div><strong>Available plugins</strong><p class="muted">Packages from all enabled catalogues are shown together.</p></div><button type="button" :disabled="previewing" @click="loadCatalogues">Refresh</button></div>
            <div v-if="!catalog.length" class="muted">No plugins are currently listed by the enabled catalogues.</div>
            <article v-for="entry in catalog" :key="entry.plugin_id" class="catalogue-entry"><div><strong>{{ entry.name }}</strong><span>{{ entry.plugin_id }} · v{{ entry.version }}</span><p>{{ entry.description }}</p></div><button type="button" :disabled="previewing" @click="previewCatalogEntry(entry.url)">Install</button></article>
          </section>
        </section>
      </div>
    </Teleport>
    <p v-if="loading">Loading plugins…</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <p v-else-if="!plugins.length" class="muted">No plugins are installed.</p>
    <div v-else class="list">
      <article v-for="plugin in plugins" :key="plugin.plugin_id" class="plugin">
        <header>
          <div>
            <h3>{{ plugin.name }}</h3>
            <span>{{ plugin.plugin_id }} · v{{ plugin.version }}</span>
          </div>
          <strong>{{ plugin.status }}</strong>
        </header>
        <p>
          {{
            plugin.compatible
              ? "Compatible with the current host."
              : `Incompatible: ${plugin.compatibility_reason}`
          }}
        </p>
        <dl>
          <div>
            <dt>Health</dt>
            <dd>{{ plugin.health }}</dd>
          </div>
          <div>
            <dt>Permissions</dt>
            <dd>{{ plugin.permissions.length }}</dd>
          </div>
          <div>
            <dt>Enabled</dt>
            <dd>{{ plugin.enabled ? "Yes" : "No" }}</dd>
          </div>
        </dl>
        <div class="actions">
          <button
            type="button"
            :disabled="action === plugin.plugin_id"
            @click="openPlugin(plugin)"
          >
            Settings
          </button>
          <label class="file-button"
            >Update<input
              type="file"
              accept="*/*"
              :disabled="action === plugin.plugin_id"
              @change="updateSelected(plugin, $event)"
          /></label>
          <button
            type="button"
            class="danger"
            :disabled="action === plugin.plugin_id"
            @click="removePlugin(plugin)"
          >
            Delete
          </button>
        </div>
      </article>
    </div>

    <PluginInstallConsentDialog
      v-if="installPreview"
      :preview="installPreview"
      :busy="installing"
      @cancel="cancelInstall"
      @confirm="confirmInstall"
    />
    <PluginSettingsDialog
      v-if="selected"
      :plugin="selected"
      :document="pluginUi"
      :grants="pluginGrants"
      :requests="pluginRequests"
      :diagnostics="pluginDiagnostics"
      :loading="popupLoading"
      :busy="action === selected.plugin_id"
      @close="closePlugin"
      @save="savePlugin"
      @action="runPluginAction"
      @enable="runSelected(enablePlugin)"
      @disable="runSelected(disablePlugin)"
      @retry="runSelected(retryPlugin)"
      @revoke="revokeGrant"
      @approve="resolveRequest($event, true)"
      @deny="resolveRequest($event, false)"
      @refresh="refreshPlugin"
    />
  </section>
</template>

<style scoped>
.installer-launcher {
  display: grid;
  gap: 16px;
  margin: 16px 0 24px;
  padding: 16px;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
}
.success {
  color: #8f8;
}
.install-launcher { font-size: 1rem; }
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--ui-z-dialog);
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.72);
}
.installer-dialog {
  width: min(760px, 100%);
  max-height: 90vh;
  overflow: auto;
  box-sizing: border-box;
  padding: 24px;
  background: #151515;
  color: #f4f4f4;
  border: 1px solid #3b3b3b;
  border-radius: 14px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.65);
  display: grid;
  gap: 18px;
}
.dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.eyebrow {
  margin: 0 0 4px;
  color: #d68a34;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.endpoint-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}
.endpoint-add {
  display: flex;
  gap: 8px;
}
.endpoint-add input {
  flex: 1;
  min-width: 0;
}
.install-method,
.catalogue {
  display: grid;
  gap: 8px;
}
.url-row,
.catalogue-header,
.catalogue-entry {
  display: flex;
  gap: 8px;
  align-items: center;
}
.url-row input {
  flex: 1;
  min-width: 0;
}
.catalogue-header {
  justify-content: space-between;
}
.catalogue-header p {
  margin: 4px 0 0;
}
.catalogue-entry {
  justify-content: space-between;
  padding: 10px 0;
  border-top: 1px solid #2a2a2a;
}
.catalogue-entry div {
  min-width: 0;
}
.catalogue-entry span {
  display: block;
  color: #aaa;
  font-size: 12px;
}
.catalogue-entry p {
  margin: 4px 0 0;
  color: #aaa;
}
code {
  font-family: monospace;
}
h2 {
  margin-top: 0;
}
.muted {
  color: #aaa;
}
.error {
  color: #f77;
}
.list {
  display: grid;
  gap: 14px;
}
.plugin {
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 16px;
}
.plugin header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}
.plugin h3 {
  margin: 0 0 4px;
}
.plugin header span,
.plugin dd {
  color: #aaa;
}
.plugin dl {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
}
.plugin dt {
  font-size: 12px;
  color: #777;
}
.plugin dd {
  margin: 2px 0 0;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
button,
.file-button {
  cursor: pointer;
}
.file-button {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid #555;
  border-radius: 4px;
}
.file-button input {
  display: none;
}
.danger {
  border-color: #a44;
}
</style>
