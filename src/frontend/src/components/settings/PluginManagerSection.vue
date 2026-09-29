<script setup lang="ts">
import { onMounted, ref } from "vue";
import PluginInstallConsentDialog from "../plugins/PluginInstallConsentDialog.vue";
import PluginSettingsDialog from "../plugins/PluginSettingsDialog.vue";
import {
  deletePlugin,
  disablePlugin,
  enablePlugin,
  fetchPluginLogs,
  fetchPlugins,
  installPlugin,
  previewPluginInstall,
  retryPlugin,
  updatePlugin,
  type PluginInstallPreview,
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
const loading = ref(true);
const error = ref("");
const action = ref("");
const selectedFile = ref<File | null>(null);
const installFile = ref<File | null>(null);
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

async function load() {
  loading.value = true;
  error.value = "";
  try {
    plugins.value = await fetchPlugins();
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

function cancelInstall() {
  if (installing.value) return;
  installFile.value = null;
  installPreview.value = null;
}

async function confirmInstall(approvedPermissions: string[]) {
  if (!installFile.value || !installPreview.value) return;
  installing.value = true;
  error.value = "";
  try {
    const result = await installPlugin(
      installFile.value,
      approvedPermissions,
      installPreview.value.trust_status === "untrusted",
    );
    installMessage.value =
      `Installed ${result.name} v${result.version}; ` +
      `${result.permissions_granted} permission(s) granted and ${result.permissions_denied} denied.`;
    selectedFile.value = null;
    installFile.value = null;
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

onMounted(load);
</script>

<template>
  <section>
    <h2>Plugins</h2>
    <p class="muted">
      Install a <code>.utp</code> package, review its identity and requested
      access, then manage it here.
    </p>
    <div class="installer">
      <label for="plugin-package">Plugin package (.utp)</label>
      <input
        id="plugin-package"
        type="file"
        accept=".utp,application/zip"
        @change="selectFile"
      />
      <button
        type="button"
        :disabled="!selectedFile || previewing"
        @click="previewSelected"
      >
        {{ previewing ? "Inspecting…" : "Review and install" }}
      </button>
      <p v-if="installMessage" class="success">{{ installMessage }}</p>
    </div>

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
              accept=".utp,application/zip"
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
.installer {
  display: grid;
  gap: 8px;
  margin: 16px 0 24px;
  padding: 16px;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
}
.success {
  color: #8f8;
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
