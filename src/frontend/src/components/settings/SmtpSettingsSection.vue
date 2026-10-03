<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { fetchDeploymentSettings, sendSmtpTest, updateDeploymentSettings } from "../../services/deploymentSettings";

const fields = [
  ["smtp_enabled", "Enable SMTP notifications", "checkbox"],
  ["smtp_host", "SMTP host", "text"],
  ["smtp_port", "SMTP port", "number"],
  ["smtp_username", "SMTP username", "text"],
  ["smtp_password", "SMTP password", "password"],
  ["smtp_from_email", "SMTP sender address", "email"],
  ["smtp_security", "SMTP security", "select"],
] as const;

const values=reactive<Record<string,string|number|boolean|null>>({});
const locked=reactive<Record<string,boolean>>({});
const configured=ref(false);
const loading=ref(true),saving=ref(false),testing=ref(false);
const error=ref<string|null>(null),saved=ref(false),tested=ref(false);

onMounted(async()=>{try{
  const result=await fetchDeploymentSettings();
  for(const [key] of fields){
    locked[key]=result.smtp.locked_fields[key]===true;
    if(key!=="smtp_password") values[key]=result.smtp[key as keyof typeof result.smtp] as string|number|boolean|null;
  }
  configured.value=result.smtp.smtp_password_configured;
}catch(e){error.value=e instanceof Error?e.message:"Failed to load SMTP settings."}finally{loading.value=false}});

async function save(){
  saving.value=true;error.value=null;saved.value=false;
  try{
    const payload:Record<string,string|number|boolean>={};
    for(const [key] of fields){
      if(locked[key])continue;
      const value=values[key];
      if(key==="smtp_password"&&!String(value??"").trim())continue;
      if(value!==null&&value!==undefined&&value!=="")payload[key]=value;
    }
    const result=await updateDeploymentSettings(payload);
    for(const [key] of fields)if(key!=="smtp_password"&&result.smtp[key as keyof typeof result.smtp]!==undefined)values[key]=result.smtp[key as keyof typeof result.smtp] as string|number|boolean|null;
    configured.value=result.smtp.smtp_password_configured;saved.value=true;
  }catch(e){error.value=e instanceof Error?e.message:"Failed to save SMTP settings."}finally{saving.value=false}
}
async function test(){
  testing.value=true;error.value=null;tested.value=false;
  try{await sendSmtpTest();tested.value=true}catch(e){error.value=e instanceof Error?e.message:"SMTP test failed."}finally{testing.value=false}
}
</script>
<template>
<section class="section">
<h2>SMTP / Email</h2>
<p class="hint">Deployment-wide SMTP settings used by the Email notification provider. Environment values are authoritative and cannot be overridden here.</p>
<div v-if="loading">Loading…</div>
<template v-else>
<div class="grid">
<label v-for="[key,label,type] in fields" :key="key">
<span>{{label}} <small v-if="locked[key]" class="env-badge">Managed by .env</small></span>
<input v-if="type!=='select'&&type!=='checkbox'" v-model="values[key]" :type="type" :disabled="locked[key]" :placeholder="locked[key]?'Managed by deployment environment':key==='smtp_password'&&configured?'Already configured — enter a new value to replace it':''">
<input v-else-if="type==='checkbox'" v-model="values[key]" type="checkbox" :disabled="locked[key]">
<select v-else v-model="values[key]" :disabled="locked[key]"><option value="none">None</option><option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option></select>
</label>
</div>
<p class="hint">SMTP passwords are encrypted at rest and never returned to the page.</p>
<div class="actions"><button :disabled="saving" @click="save">{{saving?"Saving…":"Save SMTP settings"}}</button><button class="secondary" :disabled="testing" @click="test">{{testing?"Sending…":"Send test email"}}</button></div>
<p v-if="saved" class="success">SMTP settings saved.</p><p v-if="tested" class="success">Test email sent to the current administrator email address.</p><p v-if="error" class="error">{{error}}</p>
</template>
</section>
</template>
<style scoped>
.section{display:flex;flex-direction:column;gap:16px}.section h2{margin:0;color:#fff}.hint{color:#999;font-size:13px;line-height:1.5}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.grid label{display:flex;flex-direction:column;gap:6px;color:#ccc;font-size:13px}.grid input,.grid select{background:#111;border:1px solid #3a3a3a;border-radius:8px;color:#fff;padding:10px;font:inherit}.grid input[type=checkbox]{width:18px;height:18px}.env-badge{margin-left:8px;color:#f0b36b;font-weight:700}.actions{display:flex;gap:10px;flex-wrap:wrap}button{background:#d68a34;border:0;border-radius:8px;padding:10px 14px;font-weight:600;cursor:pointer}.secondary{background:#252525;color:#ddd;border:1px solid #3a3a3a}button:disabled{opacity:.6}.error{color:#fca5a5}.success{color:#86efac}@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style>
