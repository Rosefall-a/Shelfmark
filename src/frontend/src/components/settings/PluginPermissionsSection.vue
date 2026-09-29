<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  fetchPluginClientIdentities, fetchPluginPermissionGrants, fetchPluginPermissionRequests,
  approvePluginPermission, denyPluginPermission, revokePluginClientIdentity, revokePluginPermission,
  type PluginClientIdentity, type PluginPermissionGrant, type PluginPermissionRequest,
} from "../../services/pluginPermissions";

const route = useRoute();
const requests = ref<PluginPermissionRequest[]>([]);
const grants = ref<PluginPermissionGrant[]>([]);
const clients = ref<PluginClientIdentity[]>([]);
const loading = ref(true);
const error = ref("");
const action = ref("");

function capabilityRisk(capability: string): "high" | "medium" | "low" {
  if (capability.endsWith(".write") || capability === "notifications.send") return "high";
  if (capability.endsWith(".read") || capability === "events.subscribe") return "medium";
  return "low";
}

function riskLabel(capability: string): string {
  return capabilityRisk(capability).toUpperCase() + " RISK";
}

async function load() {
  loading.value = true; error.value = "";
  try {
    [requests.value, grants.value, clients.value] = await Promise.all([
      fetchPluginPermissionRequests(), fetchPluginPermissionGrants(), fetchPluginClientIdentities(),
    ]);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load plugin permissions.";
  } finally { loading.value = false; }
}
async function approve(id: string) { action.value = id; try { await approvePluginPermission(id); await load(); } catch (err) { error.value = err instanceof Error ? err.message : "Failed to approve request."; } finally { action.value = ""; } }
async function deny(id: string) { action.value = id; try { await denyPluginPermission(id); await load(); } catch (err) { error.value = err instanceof Error ? err.message : "Failed to deny request."; } finally { action.value = ""; } }
async function revoke(id: string) { action.value = id; try { await revokePluginPermission(id); await load(); } catch (err) { error.value = err instanceof Error ? err.message : "Failed to revoke permission."; } finally { action.value = ""; } }
async function revokeClient(id: string) { action.value = id; try { await revokePluginClientIdentity(id); await load(); } catch (err) { error.value = err instanceof Error ? err.message : "Failed to revoke client identity."; } finally { action.value = ""; } }
onMounted(load);
</script>

<template>
  <section>
    <h2>Plugin Permissions</h2>
    <p class="muted">Permissions are enforced at the gateway. Grants are installation-scoped and can be narrowed to a user or device.</p>
    <p v-if="loading">Loading plugin permissions…</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <template v-else>
      <h3>Pending requests<span v-if="route.query.plugin" class="focus"> for {{ route.query.plugin }}</span></h3>
      <p v-if="!requests.some((item) => item.status === 'pending' && (!route.query.plugin || item.plugin_id === route.query.plugin))" class="muted">No pending permission requests for this plugin.</p>
      <div v-for="item in requests.filter((entry) => entry.status === 'pending' && (!route.query.plugin || entry.plugin_id === route.query.plugin))" :key="item.id" class="row">
        <div><strong>{{ item.plugin_id }}</strong><span>{{ item.capability }} v{{ item.capability_version }}</span><small>Risk: <b>{{ riskLabel(item.capability) }}</b> · {{ item.rationale }}</small></div>
        <div class="actions"><button type="button" :disabled="action === item.id" @click="approve(item.id)">Grant</button><button type="button" :disabled="action === item.id" @click="deny(item.id)">Deny</button></div>
      </div>
      <h3>Permission grants</h3>
      <div v-for="item in grants" :key="item.id" class="row">
        <div><strong>{{ item.plugin_id }}</strong><span>{{ item.capability }} v{{ item.capability_version }}</span><small>Risk: <b>{{ riskLabel(item.capability) }}</b> · {{ item.user_id ? "User scope: " + item.user_id : "All users" }}{{ item.device_id ? " · Device: " + item.device_id : "" }}</small></div>
        <button v-if="item.active" type="button" :disabled="action === item.id" @click="revoke(item.id)">Revoke</button>
        <span v-else class="muted">Revoked</span>
      </div>
      <h3>My scoped client identities</h3>
      <p class="muted">Client credentials are returned only at creation time. Existing credentials cannot be viewed again.</p>
      <div v-for="item in clients" :key="item.id" class="row">
        <div><strong>{{ item.name }}</strong><span>{{ item.plugin_id }} · {{ item.device_id }}</span></div>
        <button v-if="item.active" type="button" :disabled="action === item.id" @click="revokeClient(item.id)">Revoke</button>
        <span v-else class="muted">Revoked</span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.focus { color: #d68a34; }
h2 { margin-top: 0; } h3 { margin: 28px 0 10px; } .muted { color: #aaa; } .error { color: #ff7b7b; }
.row { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 0; border-bottom:1px solid #2a2a2a; }
.row div { display:grid; gap:4px; } .row span,.row small { color:#aaa; } .actions { display:flex; gap:8px; } button { cursor:pointer; } b { font-weight: 700; }
</style>
