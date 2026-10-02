<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  managerEntries,
  type ManagerView,
} from "../../services/pluginManagerViews";
import { refreshPluginExtensions } from "../../state/pluginExtensions";
import PluginInstallConsentDialog from "../plugins/PluginInstallConsentDialog.vue";
import PluginSettingsDialog from "../plugins/PluginSettingsDialog.vue";
import {
  deletePlugin,
  deletePluginCatalogue,
  disablePlugin,
  enablePlugin,
  createPluginCatalogue,
  fetchPluginCatalogFromSource,
  fetchPluginCatalogues,
  fetchPluginLogs,
  fetchPlugins,
  checkPluginUpdates,
  installPlugin,
  installPluginFromUrl,
  previewPluginInstall,
  previewPluginInstallUrl,
  previewPluginUpdate,
  previewPluginUpdateUrl,
  retryPlugin,
  updatePluginCatalogue,
  updatePlugin,
  updatePluginFromUrl,
  type PluginCatalogue,
  type PluginInstallConfirmation,
  type PluginInstallPreview,
  type PluginSourceMetadata,
  type PluginCatalogEntry,
  type PluginDiagnostics,
  type PluginSummary,
  type PluginUpdateCheck,
  fetchRuntimeCapabilities,
  fetchManagerSettings,
  saveManagerSettings,
  setPluginAutomaticUpdates,
  packageOperation,
  previewStagedUpdate,
  type RuntimeCapabilities,
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
const catalogues = ref<PluginCatalogue[]>([]);
const catalogueErrors = ref<string[]>([]);
const newCatalogEndpoint = ref("");
const installSource = ref<Partial<PluginSourceMetadata>>({ type: "upload" });
const updateTarget = ref<PluginSummary | null>(null);
const updateFile = ref<File | null>(null);
const updateUrl = ref<string | null>(null);
const replacement = ref(false);
const updateSource = ref<Partial<PluginSourceMetadata>>({});
const availableUpdates = ref<Record<string, PluginUpdateCheck>>({});
const checkingUpdates = ref(false);
const view = ref<ManagerView>("Installed");
const search = ref("");
const tag = ref("");
const runtime = ref<RuntimeCapabilities | null>(null);
const managerSettings = ref({ automatic_updates: false, retained_versions: 1 });
const stagedTarget = ref<string | null>(null);
const grantTarget = ref<string | null>(null);
const duplicate = ref<PluginSummary | null>(null);
const entries = computed(() =>
  managerEntries(
    plugins.value,
    catalog.value,
    view.value,
    search.value,
    tag.value,
  ),
);
const tags = computed(() =>
  [
    ...new Set(
      [...plugins.value, ...catalog.value].flatMap((item) => item.tags ?? []),
    ),
  ].sort(),
);
const installedEntries = computed(() =>
  entries.value.filter((item): item is PluginSummary => "status" in item),
);
const catalogueEntries = computed(() =>
  entries.value.filter(
    (item): item is PluginCatalogEntry => !("status" in item),
  ),
);

async function saveGlobalSettings() {
  try {
    managerSettings.value = await saveManagerSettings(managerSettings.value);
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Settings could not be saved.";
  }
}

async function lifecycleOperation(operation: string, purge = false) {
  const plugin = selected.value;
  if (!plugin) return;
  if (operation === "uninstall") {
    await removePlugin(plugin);
    return;
  }
  if (
    purge &&
    !window.confirm(
      `Permanently purge all ${plugin.name} data, configuration, credentials and permissions?`,
    )
  )
    return;
  await run(plugin.plugin_id, async (id) => {
    if (operation.startsWith("rollback/")) {
      await packageOperation(id, "rollback", {
        history_id: operation.split("/")[1],
        allow_untrusted: plugin.trust?.status !== "trusted",
      });
    } else {
      await packageOperation(id, operation, {
        purge,
        confirmed: purge,
        allow_untrusted: plugin.trust?.status !== "trusted",
      });
    }
  });
}

async function autoUpdateSelected(mode: string) {
  if (selected.value)
    await run(selected.value.plugin_id, async (id) => {
      await setPluginAutomaticUpdates(id, mode);
    });
}

async function deleteHistory(id: string) {
  if (
    !selected.value ||
    !window.confirm("Delete this retained package? Plugin data is preserved.")
  )
    return;
  await run(selected.value.plugin_id, async (pluginId) => {
    const response = await fetch(
      `/api/plugins/${encodeURIComponent(pluginId)}/history/${encodeURIComponent(id)}`,
      { method: "DELETE", credentials: "include" },
    );
    if (!response.ok) throw new Error("Retained package could not be deleted.");
  });
}

async function reviewGrant(key: string) {
  if (!selected.value) return;
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(selected.value.plugin_id)}/permissions/preview`,
    { method: "POST", credentials: "include" },
  );
  if (!response.ok) {
    error.value = "Permission preview is unavailable.";
    return;
  }
  const preview = (await response.json()) as PluginInstallPreview;
  grantTarget.value = selected.value.plugin_id;
  installPreview.value = {
    ...preview,
    operation: "update",
    permissions: preview.permissions
      .filter((item) => item.key === key)
      .map((item) => ({ ...item, new: true })),
  };
}

async function chooseDuplicate(choice: "update" | "reinstall" | "replace") {
  const plugin = duplicate.value;
  duplicate.value = null;
  if (!plugin) return;
  if (choice === "reinstall") {
    cancelInstall();
    selected.value = plugin;
    await lifecycleOperation("reinstall");
    return;
  }
  replacement.value = choice === "replace";
  updateTarget.value = plugin;
  updateFile.value = installFile.value;
  updateUrl.value = installUrl.value;
  updateSource.value = installSource.value;
  installPreview.value = updateFile.value
    ? await previewPluginUpdate(
        plugin.plugin_id,
        updateFile.value,
        replacement.value ? "replace" : "update",
      )
    : await previewPluginUpdateUrl(
        plugin.plugin_id,
        updateUrl.value!,
        installSource.value,
        replacement.value ? "replace" : "update",
      );
}

async function addCatalogEndpoint() {
  const url = newCatalogEndpoint.value.trim();
  if (!/^https?:\/\//i.test(url)) return;
  await createPluginCatalogue({
    name: new URL(url).hostname,
    url,
    enabled: true,
    priority: 100,
  });
  newCatalogEndpoint.value = "";
  await loadCatalogues();
}

async function removeCatalogEndpoint(catalogue: PluginCatalogue) {
  if (catalogue.id === "official") return;
  await deletePluginCatalogue(catalogue.id);
  await loadCatalogues();
}

async function toggleCatalogEndpoint(
  catalogue: PluginCatalogue,
  enabled: boolean,
) {
  await updatePluginCatalogue(catalogue.id, { enabled });
  await loadCatalogues();
}

async function loadCatalogues() {
  catalogueErrors.value = [];
  catalogues.value = await fetchPluginCatalogues();
  const enabled = catalogues.value.filter((catalogue) => catalogue.enabled);
  const results = await Promise.all(
    enabled.map(async (catalogue) => ({
      catalogue,
      entries: await fetchPluginCatalogFromSource(catalogue.url).catch(
        (error: unknown) => {
          catalogueErrors.value.push(
            `${catalogue.name}: ${error instanceof Error ? error.message : "Catalogue could not be loaded"}`,
          );
          return [];
        },
      ),
    })),
  );
  const seen = new Set<string>();
  catalog.value = results
    .flatMap((result) =>
      result.entries.map((entry) => ({
        ...entry,
        catalogue_url: result.catalogue.url,
      })),
    )
    .filter((entry) => {
      if (seen.has(entry.plugin_id)) return false;
      seen.add(entry.plugin_id);
      return true;
    });
}

function openInstaller() {
  if (installing.value || previewing.value) return;
  installOpen.value = true;
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
    availableUpdates.value = Object.fromEntries(
      plugins.value
        .filter((item) => item.available_update?.update_available)
        .map((item) => [item.plugin_id, item.available_update!]),
    );
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
    await refreshPluginExtensions();
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
  if (!selectedFile.value || installing.value || previewing.value) return;
  previewing.value = true;
  error.value = "";
  installMessage.value = "";
  try {
    installUrl.value = null;
    installSource.value = { type: "upload" };
    installFile.value = selectedFile.value;
    installPreview.value = await previewPluginInstall(selectedFile.value);
    duplicate.value =
      plugins.value.find(
        (item) => item.plugin_id === installPreview.value?.plugin_id,
      ) ?? null;
  } catch (err) {
    installFile.value = null;
    installPreview.value = null;
    error.value = err instanceof Error ? err.message : "Plugin preview failed.";
  } finally {
    previewing.value = false;
  }
}

async function previewRemoteUrl(
  url = remoteUrl.value,
  source: Partial<PluginSourceMetadata> = { type: "url" },
) {
  if (installing.value || previewing.value) return;
  const normalized = url.trim();
  if (!normalized) return;
  previewing.value = true;
  error.value = "";
  installMessage.value = "";
  try {
    installFile.value = null;
    installUrl.value = normalized;
    installSource.value = source;
    installPreview.value = await previewPluginInstallUrl(normalized, source);
    duplicate.value =
      plugins.value.find(
        (item) => item.plugin_id === installPreview.value?.plugin_id,
      ) ?? null;
  } catch (err) {
    installUrl.value = null;
    installPreview.value = null;
    error.value =
      err instanceof Error ? err.message : "Plugin URL preview failed.";
  } finally {
    previewing.value = false;
  }
}

async function previewCatalogEntry(entry: PluginCatalogEntry) {
  error.value = "";
  await previewRemoteUrl(entry.url, {
    type: "catalogue",
    catalogue_url: entry.catalogue_url,
    release_notes: entry.release_notes,
    changelog_url: entry.changelog_url,
  });
  if (installPreview.value) {
    installPreview.value.readme ??= entry.readme;
    installPreview.value.icon ??= entry.icon;
  }
}

function cancelInstall() {
  if (installing.value) return;
  installFile.value = null;
  installUrl.value = null;
  installPreview.value = null;
  updateTarget.value = null;
  updateFile.value = null;
  updateUrl.value = null;
  updateSource.value = {};
  stagedTarget.value = null;
  grantTarget.value = null;
  duplicate.value = null;
}

async function confirmInstall(confirmation: PluginInstallConfirmation) {
  if (!installPreview.value) return;
  installing.value = true;
  error.value = "";
  try {
    if (grantTarget.value || stagedTarget.value) {
      const id = grantTarget.value ?? stagedTarget.value!;
      const result = await packageOperation(
        id,
        grantTarget.value ? "permissions/grant" : "update/staged",
        {
          approved_permissions: confirmation.approvedPermissions,
          expected_digest: installPreview.value.digest,
          confirmed: Boolean(
            stagedTarget.value &&
            installPreview.value.new_permission_keys?.length &&
            !confirmation.approvedPermissions.length,
          ),
          admin_password: confirmation.adminPassword,
          confirm_dangerous: confirmation.confirmDangerous,
          allow_untrusted: installPreview.value.trust_status !== "trusted",
        },
      );
      installMessage.value = grantTarget.value
        ? "Selected permissions explicitly granted."
        : result.status === "denied"
          ? "Staged update denied. The current package remains active."
          : result.status === "awaiting_permissions"
            ? "Update remains staged for approval. The current package remains active."
            : result.status === "rolled_back"
              ? `Update failed verification; v${result.version} restored. See diagnostics.`
              : `Update activated: v${result.version}.`;
      grantTarget.value = null;
      stagedTarget.value = null;
    } else if (updateTarget.value && (updateFile.value || updateUrl.value)) {
      const result = updateFile.value
        ? await updatePlugin(
            updateTarget.value.plugin_id,
            updateFile.value,
            confirmation,
            installPreview.value.trust_status !== "trusted",
            replacement.value ? "replace" : "update",
          )
        : await updatePluginFromUrl(
            updateTarget.value.plugin_id,
            updateUrl.value!,
            confirmation,
            installPreview.value.digest,
            installPreview.value.trust_status !== "trusted",
            updateSource.value,
            replacement.value ? "replace" : "update",
          );
      installMessage.value =
        result.status === "awaiting_permissions"
          ? `${updateTarget.value.name}: update staged for permission approval. The current version remains active.`
          : result.status === "rolled_back"
            ? `${updateTarget.value.name}: update failed verification; v${result.version} was restored. See runtime diagnostics.`
            : `Updated ${updateTarget.value.name} to v${result.version}; ${result.permissions_requested} new permission(s) reviewed.`;
    } else if (installUrl.value) {
      const result = await installPluginFromUrl(
        installUrl.value,
        confirmation,
        installPreview.value.digest,
        installPreview.value.trust_status !== "trusted",
        installSource.value,
      );
      installMessage.value =
        `Installed ${result.name} v${result.version}; ` +
        `${result.permissions_granted} permission(s) granted and ${result.permissions_denied} denied.`;
    } else if (installFile.value) {
      const result = await installPlugin(
        installFile.value,
        confirmation,
        installPreview.value.trust_status !== "trusted",
      );
      installMessage.value =
        `Installed ${result.name} v${result.version}; ` +
        `${result.permissions_granted} permission(s) granted and ${result.permissions_denied} denied.`;
    }
    selectedFile.value = null;
    installFile.value = null;
    installUrl.value = null;
    remoteUrl.value = "";
    installPreview.value = null;
    updateTarget.value = null;
    updateFile.value = null;
    updateUrl.value = null;
    updateSource.value = {};
    await load();
    await refreshPluginExtensions();
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
      fetchPluginUi(plugin.plugin_id).catch(() => null),
      fetchPluginLogs(plugin.plugin_id).catch(() => null),
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
    await refreshPluginExtensions();
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
  previewing.value = true;
  error.value = "";
  try {
    updateTarget.value = plugin;
    updateFile.value = file;
    updateUrl.value = null;
    updateSource.value = {};
    installFile.value = file;
    installUrl.value = null;
    installPreview.value = await previewPluginUpdate(plugin.plugin_id, file);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Plugin update failed.";
  } finally {
    previewing.value = false;
    input.value = "";
  }
}

async function reviewAvailableUpdate(plugin: PluginSummary) {
  if (plugin.staged_update) {
    stagedTarget.value = plugin.plugin_id;
    installPreview.value = await previewStagedUpdate(plugin.plugin_id);
    return;
  }
  const update = availableUpdates.value[plugin.plugin_id];
  if (!update?.url) return;
  previewing.value = true;
  error.value = "";
  try {
    const source = {
      ...(update.source ?? {}),
      release_notes: update.release_notes,
      changelog_url: update.changelog_url,
    };
    updateTarget.value = plugin;
    updateFile.value = null;
    updateUrl.value = update.url;
    updateSource.value = source;
    installFile.value = null;
    installUrl.value = null;
    installPreview.value = await previewPluginUpdateUrl(
      plugin.plugin_id,
      update.url,
      source,
    );
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Plugin update preview failed.";
  } finally {
    previewing.value = false;
  }
}

async function refreshUpdates() {
  checkingUpdates.value = true;
  error.value = "";
  try {
    const result = await checkPluginUpdates();
    plugins.value = plugins.value.map((plugin) => ({
      ...plugin,
      available_update: result.updates.find(
        (update) => update.plugin_id === plugin.plugin_id,
      ),
    }));
    availableUpdates.value = Object.fromEntries(
      result.updates
        .filter((update) => update.update_available)
        .map((update) => [update.plugin_id, update]),
    );
    installMessage.value = result.available
      ? `${result.available} plugin update(s) available. Notifications were added for administrators.`
      : "All update-capable plugins are current.";
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Plugin update check failed.";
  } finally {
    checkingUpdates.value = false;
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
    await refreshPluginExtensions();
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Plugin deletion failed.";
  } finally {
    action.value = "";
  }
}

onMounted(() => {
  void load();
  void fetchRuntimeCapabilities()
    .then((value) => (runtime.value = value))
    .catch(() => {});
  void fetchManagerSettings()
    .then((value) => (managerSettings.value = value))
    .catch(() => {});
});
</script>

<template>
  <section>
    <h2>Plugins</h2>
    <p class="muted">
      Browse plugins, review access, and manage installed releases and
      persistent data.
    </p>
    <aside v-if="runtime" class="runtime-notice">
      <strong>{{
        runtime.bubblewrap_available
          ? "Bubblewrap is usable"
          : runtime.bubblewrap_available === null
            ? "Runtime capability is unknown"
            : "Bubblewrap is unavailable"
      }}</strong>
      <p>
        {{
          runtime.sandbox_available
            ? "Per-plugin namespace and filesystem isolation is available."
            : "Per-plugin sandbox isolation is unavailable. Reduced isolation uses separate processes and available resource limits. Continue only where runtime policy permits."
        }}
      </p>
      <p v-if="runtime.last_error">{{ runtime.last_error }}</p>
      <a
        href="https://github.com/Rosefall-a/unnamed_tracking_app/blob/plugin-manager/wiki/docs/development/plugin-runtime.md"
        target="_blank"
        rel="noopener noreferrer"
        >Runtime setup and Bubblewrap help</a
      >
    </aside>
    <details>
      <summary>Plugin Manager settings</summary>
      <label
        ><input
          v-model="managerSettings.automatic_updates"
          type="checkbox"
          @change="saveGlobalSettings"
        />
        Automatic catalogue updates</label
      >
      <label
        >Old package versions to retain
        <input
          v-model.number="managerSettings.retained_versions"
          type="number"
          min="1"
          max="100"
          @change="saveGlobalSettings"
      /></label>
    </details>
    <nav class="manager-tabs" aria-label="Plugin views">
      <button
        v-for="item in [
          'Installed',
          'Updates Available',
          'Available to Install',
          'All',
        ] as ManagerView[]"
        :key="item"
        :aria-pressed="view === item"
        @click="view = item"
      >
        {{ item }}
      </button>
    </nav>
    <div class="manager-filters">
      <input
        v-model="search"
        type="search"
        placeholder="Filter plugins"
        aria-label="Filter plugins"
      /><select v-model="tag" aria-label="Filter by tag">
        <option value="">All tags</option>
        <option v-for="item in tags" :key="item">{{ item }}</option>
      </select>
    </div>
    <p v-for="error in catalogueErrors" :key="error" role="alert" class="muted">
      {{ error }}
    </p>
    <div class="installer-launcher">
      <button
        type="button"
        class="primary install-launcher"
        :disabled="installing || previewing"
        @click="openInstaller"
      >
        Install a plugin
      </button>
      <button type="button" :disabled="checkingUpdates" @click="refreshUpdates">
        {{ checkingUpdates ? "Checking…" : "Check for updates" }}
      </button>
      <p class="muted">
        Add a package, install from a URL, or browse enabled plugin catalogues.
      </p>
      <p v-if="installMessage" class="success">{{ installMessage }}</p>
    </div>
    <Teleport to="body">
      <div
        v-if="installOpen"
        class="modal-backdrop"
        @click.self="closeInstaller"
      >
        <section
          class="installer-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="plugin-installer-title"
        >
          <header class="dialog-header">
            <div>
              <p class="eyebrow">Plugin manager</p>
              <h2 id="plugin-installer-title">Install a plugin</h2>
              <p class="muted">Choose a package, URL, or enabled catalogue.</p>
            </div>
            <button
              type="button"
              :disabled="installing"
              @click="closeInstaller"
            >
              Close
            </button>
          </header>
          <details class="install-method">
            <summary>Upload package</summary>
            <div>
              <strong>Upload package</strong>
              <input
                id="plugin-package"
                type="file"
                accept="*/*"
                @change="selectFile"
              />
              <button
                type="button"
                :disabled="!selectedFile || previewing || installing"
                @click="previewSelected"
              >
                {{ previewing ? "Inspecting…" : "Review package" }}
              </button>
            </div>
          </details>
          <details class="install-method">
            <summary>Install from URL</summary>
            <div>
              <strong>Install from URL</strong>
              <div class="url-row">
                <input
                  v-model="remoteUrl"
                  type="url"
                  placeholder="https://example.com/plugin.utp"
                  @keyup.enter="previewRemoteUrl()"
                /><button
                  type="button"
                  :disabled="!remoteUrl.trim() || previewing || installing"
                  @click="previewRemoteUrl()"
                >
                  Review URL
                </button>
              </div>
            </div>
          </details>
          <details class="catalogue">
            <summary>Manage catalogues</summary>
            <section>
              <div class="catalogue-header">
                <div>
                  <strong>Plugin catalogues</strong>
                  <p class="muted">
                    The official catalogue is enabled by default. Catalogue
                    provenance never replaces package signature verification.
                  </p>
                </div>
              </div>
              <div
                v-for="catalogueSource in catalogues"
                :key="catalogueSource.id"
                class="endpoint-row"
              >
                <label
                  ><input
                    type="checkbox"
                    :checked="catalogueSource.enabled"
                    @change="
                      toggleCatalogEndpoint(
                        catalogueSource,
                        ($event.target as HTMLInputElement).checked,
                      )
                    "
                  />
                  {{ catalogueSource.name }} · priority
                  {{ catalogueSource.priority }}</label
                >
                <span class="muted">{{ catalogueSource.url }}</span>
                <span v-if="catalogueSource.last_error" class="error">{{
                  catalogueSource.last_error
                }}</span>
                <button
                  v-if="catalogueSource.id !== 'official'"
                  type="button"
                  class="danger"
                  @click="removeCatalogEndpoint(catalogueSource)"
                >
                  Remove
                </button>
              </div>
              <div class="endpoint-add">
                <input
                  v-model="newCatalogEndpoint"
                  type="url"
                  placeholder="https://example.com/list.json"
                  @keyup.enter="addCatalogEndpoint"
                /><button
                  type="button"
                  :disabled="!newCatalogEndpoint.trim()"
                  @click="addCatalogEndpoint"
                >
                  Add catalogue
                </button>
              </div>
            </section>
          </details>
          <section class="catalogue">
            <div class="catalogue-header">
              <div>
                <strong>Available plugins</strong>
                <p class="muted">
                  Packages from all enabled catalogues are shown together.
                </p>
              </div>
              <button
                type="button"
                :disabled="previewing || installing"
                @click="loadCatalogues"
              >
                Refresh
              </button>
            </div>
            <div v-if="!catalog.length" class="muted">
              No plugins are currently listed by the enabled catalogues.
            </div>
            <article
              v-for="entry in catalog"
              :key="entry.plugin_id"
              class="catalogue-entry"
            >
              <div>
                <strong>{{ entry.name }}</strong
                ><span>{{ entry.plugin_id }} · v{{ entry.version }}</span>
                <p>{{ entry.description }}</p>
              </div>
              <button
                type="button"
                :disabled="previewing"
                @click="previewCatalogEntry(entry)"
              >
                Install
              </button>
            </article>
          </section>
        </section>
      </div>
    </Teleport>
    <p v-if="loading">Loading plugins…</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <p v-else-if="!entries.length" class="muted">No plugins match this view.</p>
    <div v-else class="list">
      <article
        v-for="entry in catalogueEntries"
        :key="entry.plugin_id"
        class="plugin"
      >
        <img
          v-if="entry.icon"
          :src="entry.icon"
          alt=""
          width="48"
          height="48"
        />
        <h3>{{ entry.name }}</h3>
        <p>{{ entry.description }}</p>
        <p>
          {{ entry.publisher ?? "Publisher information not supplied" }} · v{{
            entry.version
          }}
          · {{ entry.compatibility ?? "Compatibility checked during review" }}
        </p>
        <p>{{ entry.tags?.join(" · ") }}</p>
        <button
          :disabled="previewing || installing"
          @click="previewCatalogEntry(entry)"
        >
          Review plugin
        </button>
      </article>
      <article
        v-for="plugin in installedEntries"
        :key="plugin.plugin_id"
        class="plugin"
      >
        <header>
          <div>
            <img
              v-if="plugin.icon"
              :src="plugin.icon"
              alt=""
              width="48"
              height="48"
            />
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
        <p v-if="plugin.staged_update" class="muted">
          Staged v{{
            plugin.staged_update.available_version ??
            plugin.staged_update.version
          }}
          · {{ plugin.staged_update.status.replaceAll("_", " ") }} · Installed
          release remains v{{ plugin.version }}
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
            Manage plugin
          </button>
          <label class="file-button"
            >Upload update<input
              type="file"
              accept="*/*"
              :disabled="action === plugin.plugin_id"
              @change="updateSelected(plugin, $event)"
          /></label>
          <button
            v-if="
              availableUpdates[plugin.plugin_id]?.update_available ||
              plugin.staged_update
            "
            type="button"
            :disabled="previewing"
            @click="reviewAvailableUpdate(plugin)"
          >
            Review v{{
              availableUpdates[plugin.plugin_id]?.available_version ??
              plugin.staged_update?.available_version ??
              plugin.staged_update?.version
            }}
            update
          </button>
          <button
            type="button"
            class="danger"
            :disabled="action === plugin.plugin_id"
            @click="removePlugin(plugin)"
          >
            Uninstall
          </button>
        </div>
      </article>
    </div>

    <PluginInstallConsentDialog
      v-if="installPreview && !duplicate"
      :preview="installPreview"
      :busy="installing"
      @cancel="cancelInstall"
      @confirm="confirmInstall"
    />
    <Teleport to="body"
      ><div v-if="duplicate" class="modal-backdrop">
        <section
          class="installer-dialog"
          role="dialog"
          aria-modal="true"
          aria-label="Plugin already installed"
        >
          <h2>{{ duplicate.name }} is already installed</h2>
          <p>
            Installed v{{ duplicate.version }}; selected v{{
              installPreview?.version
            }}. Choose the operation explicitly.
          </p>
          <button @click="chooseDuplicate('update')">Review update</button
          ><button @click="chooseDuplicate('reinstall')">
            Reinstall installed release, retaining data</button
          ><button @click="chooseDuplicate('replace')">Replace package</button
          ><button @click="cancelInstall">Cancel</button>
        </section>
      </div></Teleport
    >
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
      @update="reviewAvailableUpdate(selected)"
      @operation="lifecycleOperation"
      @auto-update="autoUpdateSelected"
      @grant="reviewGrant"
      @delete-history="deleteHistory"
    />
  </section>
</template>

<style scoped>
.manager-tabs,
.manager-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0;
}
.manager-tabs [aria-pressed="true"] {
  border-color: #d68a34;
  color: #ffb765;
}
.runtime-notice {
  border: 1px solid #625135;
  padding: 16px;
  border-radius: 10px;
  margin: 16px 0;
}
.readme {
  max-width: 75ch;
  line-height: 1.65;
  overflow-wrap: anywhere;
}
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
.install-launcher {
  font-size: 1rem;
}
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
  font: inherit;
  font-size: 0.875rem;
  padding: 8px 12px;
  color: var(--ui-text);
  background: #242424;
  border: 1px solid var(--ui-border);
  border-radius: 8px;
}
button:hover,
.file-button:hover {
  border-color: var(--ui-accent);
}
button:disabled {
  cursor: wait;
  opacity: 0.55;
}
input:not([type="checkbox"]):not([type="file"]),
select {
  font: inherit;
  padding: 8px 10px;
  color: var(--ui-text);
  background: #171717;
  border: 1px solid var(--ui-border);
  border-radius: 8px;
  min-width: 0;
}
.manager-filters input {
  flex: 1;
}
.primary {
  background: var(--ui-accent-soft);
  border-color: var(--ui-accent-line);
}
.plugin img {
  border-radius: 8px;
  margin-bottom: 8px;
}
.file-button {
  display: inline-flex;
  align-items: center;
}
.file-button input {
  display: none;
}
.danger {
  border-color: #a44;
}
</style>
