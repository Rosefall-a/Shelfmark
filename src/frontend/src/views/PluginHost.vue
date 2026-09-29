<script setup lang="ts">
import { onMounted, ref } from "vue";
import PluginUiHost from "../components/plugins/PluginUiHost.vue";
import { fetchPluginUi, type PluginUiDocument, type UiAction, type UiValues } from "../services/pluginUi";
import { useRoute } from "vue-router";
const route=useRoute(); const document=ref<PluginUiDocument|null>(null); const loading=ref(true); const error=ref("");
async function load(){loading.value=true;error.value="";try{document.value=await fetchPluginUi(String(route.params.pluginId))}catch(err){error.value=err instanceof Error?err.message:"Failed to load plugin UI."}finally{loading.value=false}}
async function save(values:UiValues){const response=await fetch(`/api/plugins/${encodeURIComponent(String(route.params.pluginId))}/settings`,{method:"PUT",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)});if(!response.ok)error.value="Plugin settings could not be saved."}
async function action(action:UiAction,values:UiValues){const response=await fetch(`/api/plugins/${encodeURIComponent(String(route.params.pluginId))}/actions/${encodeURIComponent(action.id)}`,{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify({values})});if(!response.ok)error.value="Plugin action could not be completed."}
onMounted(load);
</script>
<template><main class="plugin-page"><p v-if="loading">Loading plugin…</p><p v-else-if="error" class="error">{{ error }}</p><PluginUiHost v-else-if="document" :document="document" @save="save" @action="action" /></main></template>
<style scoped>.plugin-page{min-height:100vh;padding:40px;background:var(--ui-bg);color:#fff}.error{color:#f77}</style>