<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { fetchNotificationProviders, revokeNotificationProviderDestination, updateNotificationProvider, type NotificationProviderSetting } from "../../services/notificationProviders";

const rows=reactive<NotificationProviderSetting[]>([]);
const values=reactive<Record<string,string>>({});
const loading=ref(true),saving=ref<string|null>(null),error=ref<string|null>(null),saved=ref<string|null>(null);

async function load(){try{rows.splice(0,rows.length,...await fetchNotificationProviders());}catch(e){error.value=e instanceof Error?e.message:"Failed to load notification providers.";}finally{loading.value=false;}}
async function save(row:NotificationProviderSetting){
  saving.value=row.id; error.value=null; saved.value=null;
  try{
    const payload:{enabled?:boolean;destination?:string}={enabled:row.enabled};
    if(row.id==="discord" && values.discord?.trim()) payload.destination=values.discord.trim();
    const result=await updateNotificationProvider(row.id,payload);
    Object.assign(row,result); values[row.id]=""; saved.value=row.id;
  }catch(e){error.value=e instanceof Error?e.message:"Failed to save provider settings."}finally{saving.value=null;}
}
async function revoke(row:NotificationProviderSetting){
  saving.value=row.id; error.value=null;
  try{await revokeNotificationProviderDestination(row.id); row.configured=false; row.enabled=false;}catch(e){error.value=e instanceof Error?e.message:"Failed to revoke Discord webhook."}finally{saving.value=null;}
}
onMounted(load);
</script>
<template>
<section class="settings-section">
<h2>Notification providers</h2>
<p class="hint">Choose which notification delivery providers may receive your in-app notifications. In-app notifications continue to work independently.</p>
<div v-if="loading">Loading…</div>
<template v-else>
<div v-for="row in rows" :key="row.id" class="provider">
  <div class="provider-head"><div><strong>{{ row.name }}</strong><p class="hint">{{ row.id==="smtp" ? (row.available ? "Uses your account email and the deployment SMTP configuration." : "SMTP is not configured for this deployment.") : "Uses a Discord webhook configured for this account." }}</p></div>
  <label class="switch"><input v-model="row.enabled" type="checkbox" :disabled="saving===row.id || !row.available || (row.id==='discord' && !row.configured)"><span>Enabled</span></label></div>
  <template v-if="row.id==='smtp'"><p class="destination">Destination: {{ row.destination || "No email address configured" }}</p></template>
  <template v-else-if="row.id==='discord'">
    <p class="destination">{{ row.configured ? "Webhook configured (secret hidden)." : "No webhook configured." }}</p>
    <input v-model="values.discord" type="url" placeholder="https://discord.com/api/webhooks/…" autocomplete="off">
    <div class="actions"><button :disabled="saving===row.id" @click="save(row)">{{ saving===row.id ? "Saving…" : row.configured ? "Replace webhook" : "Save webhook" }}</button><button v-if="row.configured" class="danger" :disabled="saving===row.id" @click="revoke(row)">Revoke</button></div>
  </template>
  <button v-if="row.id==='smtp'" :disabled="saving===row.id" @click="save(row)">{{ saving===row.id ? "Saving…" : "Save preference" }}</button>
  <p v-if="saved===row.id" class="success">Saved.</p>
</div>
<p v-if="error" class="error">{{ error }}</p>
</template>
</section>
</template>
<style scoped>
.settings-section h2{margin:0 0 8px;padding-left:12px;border-left:3px solid #d68a34;font-size:1rem;color:#fff}.hint{color:#999;font-size:.82rem;line-height:1.5}.provider{border-top:1px solid #2a2a2a;padding:18px 0}.provider-head{display:flex;justify-content:space-between;gap:16px}.switch{display:flex;gap:8px;align-items:center;color:#ccc;font-size:13px;white-space:nowrap}.destination{color:#bbb;font-size:13px}.provider input[type=url]{width:100%;box-sizing:border-box;background:#111;border:1px solid #3a3a3a;border-radius:8px;color:#fff;padding:10px}.actions{display:flex;gap:8px;margin-top:10px}button{background:#d68a34;border:0;border-radius:8px;padding:9px 14px;font-weight:600;cursor:pointer}button:disabled{opacity:.5}.danger{background:#442020;color:#fca5a5}.error{color:#fca5a5}.success{color:#86efac}
</style>
