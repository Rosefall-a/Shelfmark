<script setup lang="ts">
import { onMounted, ref } from "vue";
import { disablePlugin, enablePlugin, fetchPlugins, retryPlugin, revokePluginPermissions, type PluginSummary } from "../../services/plugins";
const plugins=ref<PluginSummary[]>([]), loading=ref(true), error=ref(""), action=ref("");
async function load(){loading.value=true;error.value="";try{plugins.value=await fetchPlugins()}catch(err){error.value=err instanceof Error?err.message:"Plugin manager is unavailable."}finally{loading.value=false}}
async function run(id:string,operation:(id:string)=>Promise<void>){action.value=id;try{await operation(id);await load()}catch(err){error.value=err instanceof Error?err.message:"Plugin action failed."}finally{action.value=""}}
onMounted(load);
</script>
<template>
<section><h2>Plugins</h2><p class="muted">Review plugin version compatibility, health, permissions and lifecycle state. Core startup does not depend on plugin health.</p>
<p v-if="loading">Loading plugins…</p><p v-else-if="error" class="error">{{ error }}</p><p v-else-if="!plugins.length" class="muted">No plugins are installed.</p>
<div v-else class="list"><article v-for="plugin in plugins" :key="plugin.plugin_id" class="plugin">
<header><div><h3>{{ plugin.name }}</h3><span>{{ plugin.plugin_id }} · v{{ plugin.version }}</span></div><strong>{{ plugin.status }}</strong></header>
<p>{{ plugin.compatible ? "Compatible with the current host." : "Incompatible: " + plugin.compatibility_reason }}</p>
<dl><div><dt>Health</dt><dd>{{ plugin.health }}</dd></div><div><dt>Permissions</dt><dd>{{ plugin.permissions.length }}</dd></div><div><dt>Enabled</dt><dd>{{ plugin.enabled ? "Yes" : "No" }}</dd></div></dl>
<div class="actions"><button v-if="!plugin.enabled" type="button" :disabled="action===plugin.plugin_id" @click="run(plugin.plugin_id,enablePlugin)">Enable</button><button v-else type="button" :disabled="action===plugin.plugin_id" @click="run(plugin.plugin_id,disablePlugin)">Disable</button><button v-if="plugin.status==='failed'||plugin.status==='quarantined'" type="button" :disabled="action===plugin.plugin_id" @click="run(plugin.plugin_id,retryPlugin)">Retry</button><button type="button" :disabled="action===plugin.plugin_id" @click="run(plugin.plugin_id,revokePluginPermissions)">Revoke permissions</button></div>
</article></div></section>
</template>
<style scoped>
h2{margin-top:0}.muted{color:#aaa}.error{color:#f77}.list{display:grid;gap:14px}.plugin{border:1px solid #2a2a2a;border-radius:10px;padding:16px}header{display:flex;justify-content:space-between;gap:16px}h3{margin:0 0 4px}header span,dd{color:#aaa}dl{display:flex;flex-wrap:wrap;gap:24px}dt{font-size:12px;color:#777}dd{margin:2px 0 0}.actions{display:flex;flex-wrap:wrap;gap:8px}button{cursor:pointer}
</style>