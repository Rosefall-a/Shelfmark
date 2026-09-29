<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { disablePlugin, enablePlugin, fetchPlugins, installPlugin, updatePlugin, deletePlugin, retryPlugin, revokePluginPermissions, fetchPluginLogs, UntrustedPluginError, type PluginSummary } from "../../services/plugins";
import PluginUiHost from "../plugins/PluginUiHost.vue";
import { fetchPluginUi, type PluginUiDocument, type UiAction, type UiValues } from "../../services/pluginUi";
const router=useRouter();
const plugins=ref<PluginSummary[]>([]), loading=ref(true), error=ref(""), action=ref(""), selectedFile=ref<File|null>(null), installing=ref(false), installMessage=ref("");
const selected=ref<PluginSummary|null>(null), pluginUi=ref<PluginUiDocument|null>(null), pluginLogs=ref<string[]>([]), popupLoading=ref(false);
const untrustedFile=ref<File|null>(null), untrustedDetails=ref<{plugin_id:string;name:string;version:string;publisher:string|null}|null>(null), installingUntrusted=ref(false);
async function load(){loading.value=true;error.value="";try{plugins.value=await fetchPlugins()}catch(err){error.value=err instanceof Error?err.message:"Plugin manager is unavailable."}finally{loading.value=false}}
async function run(id:string,operation:(id:string)=>Promise<void>){action.value=id;try{await operation(id);await load()}catch(err){error.value=err instanceof Error?err.message:"Plugin action failed."}finally{action.value=""}}
function selectFile(event: Event){ selectedFile.value=(event.target as HTMLInputElement).files?.[0] ?? null; installMessage.value=""; }
async function openPlugin(plugin: PluginSummary){
  selected.value=plugin; popupLoading.value=true; error.value="";
  try { const [ui, logs] = await Promise.all([fetchPluginUi(plugin.plugin_id), fetchPluginLogs(plugin.plugin_id)]); pluginUi.value=ui; pluginLogs.value=logs.logs; }
  catch(err){ error.value=err instanceof Error?err.message:"Failed to open plugin."; }
  finally { popupLoading.value=false; }
}
async function refreshPlugin(){ if(selected.value) await openPlugin(selected.value); }
async function savePlugin(values: UiValues){ if(!selected.value) return; const response=await fetch("/api/plugins/"+encodeURIComponent(selected.value.plugin_id)+"/settings",{method:"PUT",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)}); if(!response.ok) throw new Error("Plugin settings could not be saved."); }
async function runPluginAction(item: UiAction, values: UiValues){ if(!selected.value) return; const response=await fetch("/api/plugins/"+encodeURIComponent(selected.value.plugin_id)+"/actions/"+encodeURIComponent(item.id),{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify({values})}); if(!response.ok) throw new Error("Plugin action could not be completed."); await refreshPlugin(); }
async function updateSelected(plugin: PluginSummary, event: Event){
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  action.value = plugin.plugin_id; error.value = "";
  try {
    const result = await updatePlugin(plugin.plugin_id, file);
    installMessage.value = `Updated ${plugin.name} to v${result.version}. ${result.permissions_requested} new permission request(s) created.`;
    await load();
  } catch(err) {
    error.value = err instanceof Error ? err.message : "Plugin update failed.";
  } finally {
    action.value = "";
    (event.target as HTMLInputElement).value = "";
  }
}
async function removePlugin(plugin: PluginSummary){
  if (!window.confirm(`Delete ${plugin.name} and its stored plugin data?`)) return;
  action.value = plugin.plugin_id; error.value = "";
  try {
    await deletePlugin(plugin.plugin_id);
    if (selected.value?.plugin_id === plugin.plugin_id) { selected.value = null; pluginUi.value = null; }
    await load();
  } catch(err) {
    error.value = err instanceof Error ? err.message : "Plugin deletion failed.";
  } finally { action.value = ""; }
}
async function confirmUntrustedInstall(){
  if (!untrustedFile.value) return;
  installingUntrusted.value = true; error.value = ""; installMessage.value = "";
  try {
    const result = await installPlugin(untrustedFile.value, true);
    installMessage.value = "Installed " + result.name + " v" + result.version + " as untrusted.";
    selectedFile.value = null; untrustedFile.value = null; untrustedDetails.value = null;
    await load();
    if (result.permissions_requested > 0) await router.push({ path: "/settings", query: { section: "plugin-permissions", plugin: result.plugin_id } });
  } catch(err) {
    error.value = err instanceof Error ? err.message : "Plugin installation failed.";
  } finally { installingUntrusted.value = false; }
}
function cancelUntrustedInstall(){ untrustedFile.value = null; untrustedDetails.value = null; }
async function installSelected(){ 
  if(!selectedFile.value) return;
  installing.value=true; error.value=""; installMessage.value="";
  try {
    const result=await installPlugin(selectedFile.value);
    installMessage.value="Installed " + result.name + " v" + result.version + " from " + (result.publisher ?? "unknown publisher") + "; " + result.permissions_requested + " permission request(s) created.";
    selectedFile.value=null;
    await load();
    if (result.permissions_requested > 0) await router.push({ path: "/settings", query: { section: "plugin-permissions", plugin: result.plugin_id } });
  } catch(err){
    if (err instanceof UntrustedPluginError) {
      untrustedFile.value = selectedFile.value;
      untrustedDetails.value = err.details;
    } else {
      error.value = err instanceof Error ? err.message : "Plugin installation failed.";
    }
  } finally { installing.value=false; }
}
onMounted(load);
</script>
<template>
<section><h2>Plugins</h2><p class="muted">Install signed <code>.utp</code> packages, then review compatibility, health, permissions and lifecycle state.</p>
<div class="installer">
  <label for="plugin-package">Plugin package (.utp)</label>
  <input id="plugin-package" type="file" accept=".utp,application/zip" @change="selectFile" />
  <button type="button" :disabled="!selectedFile || installing" @click="installSelected">{{ installing ? "Installing…" : "Install plugin" }}</button>
  <p v-if="installMessage" class="success">{{ installMessage }}</p>
</div>
<p v-if="loading">Loading plugins…</p><p v-else-if="error" class="error">{{ error }}</p><p v-else-if="!plugins.length" class="muted">No plugins are installed.</p>
<div v-else class="list"><article v-for="plugin in plugins" :key="plugin.plugin_id" class="plugin">
<header><div><h3>{{ plugin.name }}</h3><span>{{ plugin.plugin_id }} · v{{ plugin.version }}</span></div><strong>{{ plugin.status }}</strong></header>
<p>{{ plugin.compatible ? "Compatible with the current host." : "Incompatible: " + plugin.compatibility_reason }}</p>
<dl><div><dt>Health</dt><dd>{{ plugin.health }}</dd></div><div><dt>Permissions</dt><dd>{{ plugin.permissions.length }}</dd></div><div><dt>Enabled</dt><dd>{{ plugin.enabled ? "Yes" : "No" }}</dd></div></dl>
<div class="actions"><button type="button" :disabled="action===plugin.plugin_id" @click="openPlugin(plugin)">Open</button><button v-if="!plugin.enabled" type="button" :disabled="action===plugin.plugin_id" @click="run(plugin.plugin_id,enablePlugin)">Enable</button><button v-else type="button" :disabled="action===plugin.plugin_id" @click="run(plugin.plugin_id,disablePlugin)">Disable</button><button v-if="plugin.status==='failed'||plugin.status==='quarantined'" type="button" :disabled="action===plugin.plugin_id" @click="run(plugin.plugin_id,retryPlugin)">Retry</button><button type="button" :disabled="action===plugin.plugin_id" @click="run(plugin.plugin_id,revokePluginPermissions)">Revoke permissions</button><label class="file-button">Update<input type="file" accept=".utp,application/zip" :disabled="action===plugin.plugin_id" @change="updateSelected(plugin,$event)" /></label><button type="button" class="danger" :disabled="action===plugin.plugin_id" @click="removePlugin(plugin)">Delete</button></div>
</article></div>
<dialog v-if="selected" open class="plugin-dialog">
  <header><div><h2>{{ selected.name }}</h2><span>{{ selected.plugin_id }} · v{{ selected.version }}</span></div><button type="button" @click="selected=null;pluginUi=null;pluginLogs=[]">Close</button></header>
  <p v-if="popupLoading">Loading plugin…</p>
  <PluginUiHost v-else-if="pluginUi" :document="pluginUi" @save="savePlugin" @action="runPluginAction" />
  <p v-else class="muted">This plugin does not expose a native UI.</p>
  <section class="logs"><header><h3>Runtime logs</h3><button type="button" @click="refreshPlugin">Refresh</button></header><pre v-if="pluginLogs.length">{{ pluginLogs.join("\n") }}</pre><p v-else class="muted">No runtime logs.</p></section>
</dialog></section>
</template>
<style scoped>
.installer{display:grid;gap:8px;margin:16px 0 24px;padding:16px;border:1px solid #2a2a2a;border-radius:10px}.success{color:#8f8}code{font-family:monospace}h2{margin-top:0}.muted{color:#aaa}.error{color:#f77}.list{display:grid;gap:14px}.plugin{border:1px solid #2a2a2a;border-radius:10px;padding:16px}header{display:flex;justify-content:space-between;gap:16px}h3{margin:0 0 4px}header span,dd{color:#aaa}dl{display:flex;flex-wrap:wrap;gap:24px}dt{font-size:12px;color:#777}dd{margin:2px 0 0}.actions{display:flex;flex-wrap:wrap;gap:8px}button,.file-button{cursor:pointer}.file-button{display:inline-flex;align-items:center;padding:2px 8px;border:1px solid #555;border-radius:4px}.file-button input{display:none}.danger{border-color:#a44}.plugin-dialog{width:min(960px,90vw);max-height:90vh;overflow:auto;background:var(--ui-bg,#111);color:inherit;border:1px solid #444;border-radius:12px;padding:24px}.plugin-dialog header,.logs header{display:flex;justify-content:space-between;align-items:center;gap:12px}.logs{margin-top:24px}.logs pre{max-height:260px;overflow:auto;white-space:pre-wrap;background:#080808;padding:12px;border-radius:8px}
</style>