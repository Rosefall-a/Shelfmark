<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { login } from "../services/auth";
import {
  oidcLoginStatus,
  startOidcLogin,
  type OidcLoginProvider,
} from "../services/oidc";
import { checkAuth } from "../state/auth";

const route = useRoute();
const router = useRouter();
const localOnly = route.path === "/login/local";
const usernameOrEmail = ref("");
const password = ref("");
const showPassword = ref(false);
const error = ref<string | null>(null);
const loading = ref(false);
const oidcAvailable = ref(false);
const oidcLoading = ref(false);
const loginMethod = ref<"sso" | "local">("local");
const ssoButtonText = ref("Continue with SSO");
const oidcProviders = ref<OidcLoginProvider[]>([]);
const passwordResetAvailable = ref(false);

const oidcMessages: Record<string, string> = {
  not_configured: "SSO is not configured yet.", provider_unavailable: "The SSO provider is currently unavailable.", authentication_failed: "SSO authentication failed. Please try again.", verified_email_required: "Your SSO account must provide a verified email address.", account_disabled: "This account is disabled.", identity_missing: "Your SSO account did not provide the identity field required for account matching.", identity_conflict: "This SSO identity is already linked to another account.", user_creation_disabled: "Your SSO account is not registered and automatic account creation is disabled.",
};

onMounted(async () => {
  const resetStatus = await fetch("/api/auth/password-reset/status").then(async (response) => response.ok ? response.json() as Promise<{ enabled: boolean }> : { enabled: false }).catch(() => ({ enabled: false }));
  passwordResetAvailable.value = resetStatus.enabled;
  if (route.query.oidc === "success") { await checkAuth(); await router.replace("/"); return; }
  if (typeof route.query.oidc_error === "string") error.value = oidcMessages[route.query.oidc_error] ?? "SSO sign-in failed.";
  if (localOnly) return;
  const oidc = await oidcLoginStatus(); oidcAvailable.value = oidc.enabled; oidcProviders.value = oidc.providers; ssoButtonText.value = oidc.login_button_text; loginMethod.value = oidc.enabled && oidc.default_login_method === "sso" ? "sso" : "local";
});

async function submit() {
  if (!usernameOrEmail.value.trim() || !password.value) { error.value = "Enter your username/email and password."; return; }
  loading.value = true; error.value = null;
  try { await login(usernameOrEmail.value.trim(), password.value); await checkAuth(); await router.push("/"); }
  catch (err) { error.value = err instanceof Error ? err.message : "Login failed"; }
  finally { loading.value = false; }
}
function sso(slug?: string) { oidcLoading.value = true; error.value = null; try { startOidcLogin(slug); } catch (err) { error.value = err instanceof Error ? err.message : "Unable to start SSO."; oidcLoading.value = false; } }
function buttonStyle(provider: OidcLoginProvider) { const hex = (provider.button_color || "#d68a34").slice(1); const r = parseInt(hex.slice(0, 2), 16); const g = parseInt(hex.slice(2, 4), 16); const b = parseInt(hex.slice(4, 6), 16); return { backgroundColor: provider.button_color || "#d68a34", borderColor: provider.button_color || "#d68a34", color: (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? "#111" : "#fff" }; }
</script>
<template>
  <main class="login-page"><form class="login-card" @submit.prevent="submit"><div class="login-brand"><span class="brand-icon">🎮</span><h1>Archive</h1></div><p class="login-subtitle">Sign in to your library</p>
    <template v-if="localOnly"><label class="field"><span>Username or email</span><input v-model="usernameOrEmail" type="text" autocomplete="username" required /></label><label class="field"><span>Password</span><input v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" required /></label><label class="password-toggle"><input v-model="showPassword" type="checkbox" /> Show password</label><div v-if="error" class="login-error">{{ error }}</div><button type="submit" class="login-button" :disabled="loading">{{ loading ? "Signing in…" : "Sign in" }}</button><router-link v-if="passwordResetAvailable" class="forgot-link" to="/reset-password">Forgot your password?</router-link></template>
    <template v-else-if="loginMethod === 'local' || !oidcAvailable"><label class="field"><span>Username or email</span><input v-model="usernameOrEmail" type="text" autocomplete="username" required /></label><label class="field"><span>Password</span><input v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" required /></label><label class="password-toggle"><input v-model="showPassword" type="checkbox" /> Show password</label><div v-if="error" class="login-error">{{ error }}</div><button type="submit" class="login-button" :disabled="loading || oidcLoading">{{ loading ? "Signing in…" : "Sign in" }}</button><router-link v-if="passwordResetAvailable" class="forgot-link" to="/reset-password">Forgot your password?</router-link><div v-if="oidcAvailable" class="sso-divider"><span>or</span></div><div v-if="oidcAvailable" class="provider-buttons"><button v-for="provider in oidcProviders" :key="provider.slug" type="button" class="oidc-button" :style="buttonStyle(provider)" :disabled="oidcLoading" @click="sso(provider.slug)"><img v-if="provider.button_image_url" :src="provider.button_image_url" alt="" /><span>{{ provider.button_text || provider.name }}</span></button></div><button v-if="oidcAvailable && !oidcProviders.length" type="button" class="oidc-button" :disabled="oidcLoading" @click="sso()">{{ oidcLoading ? "Opening SSO…" : ssoButtonText }}</button></template>
    <template v-else><div class="sso-heading"><span class="sso-icon">◉</span><div><strong>Single sign-on</strong><p>Select an identity provider to continue.</p></div></div><div v-if="error" class="login-error">{{ error }}</div><div class="provider-buttons"><button v-for="provider in oidcProviders" :key="provider.slug" type="button" class="oidc-button primary" :style="buttonStyle(provider)" :disabled="oidcLoading" @click="sso(provider.slug)"><img v-if="provider.button_image_url" :src="provider.button_image_url" alt="" /><span>{{ provider.button_text || provider.name }}</span></button></div><button v-if="!oidcProviders.length" type="button" class="oidc-button primary" :disabled="oidcLoading" @click="sso()">{{ oidcLoading ? "Opening SSO…" : ssoButtonText }}</button><details class="local-credentials"><summary>Use local credentials</summary><div class="local-fields"><label class="field"><span>Username or email</span><input v-model="usernameOrEmail" type="text" autocomplete="username" /></label><label class="field"><span>Password</span><input v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" /></label><label class="password-toggle"><input v-model="showPassword" type="checkbox" /> Show password</label><button type="submit" class="login-button" :disabled="loading || oidcLoading">{{ loading ? "Signing in…" : "Sign in locally" }}</button><router-link v-if="passwordResetAvailable" class="forgot-link" to="/reset-password">Forgot your password?</router-link></div></details></template>
  </form></main>
</template>
<style scoped>.login-page{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#121212;font-family:system-ui,sans-serif;position:relative;overflow:hidden}.login-page::before{content:"";position:absolute;width:600px;height:600px;background:radial-gradient(circle,rgba(214,138,52,.18) 0%,transparent 70%);top:50%;left:50%;transform:translate(-50%,-50%)}.login-card{position:relative;z-index:1;width:100%;max-width:360px;background:rgba(26,26,26,.9);backdrop-filter:blur(12px);border:1px solid #2a2a2a;border-radius:14px;padding:32px;box-shadow:0 24px 64px rgba(0,0,0,.5);display:flex;flex-direction:column;gap:16px}.login-brand{display:flex;align-items:center;gap:10px;justify-content:center}.brand-icon{font-size:26px}.login-brand h1{margin:0;color:#fff;font-size:1.4rem}.login-subtitle{margin:-8px 0 4px;color:#999;font-size:13px;text-align:center}.field{display:flex;flex-direction:column;gap:6px;font-size:.85rem;color:#ccc}.field input{background:#111;border:1px solid #3a3a3a;border-radius:8px;color:#fff;padding:10px 12px;font:inherit}.field input:focus{outline:none;border-color:#d68a34}.password-toggle{display:flex;align-items:center;gap:8px;color:#aaa;font-size:12px}.login-error{color:#fca5a5;font-size:13px;background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.3);border-radius:8px;padding:8px 10px}.login-button,.oidc-button{border:0;border-radius:8px;padding:11px;font-weight:600;cursor:pointer}.login-button{background:#d68a34;color:#111}.login-button:disabled,.oidc-button:disabled{opacity:.6;cursor:not-allowed}.forgot-link{color:#aaa;font-size:12px;text-align:center;text-decoration:none}.forgot-link:hover{text-decoration:underline;color:#d68a34}.oidc-button{background:#2a2a2a;color:#fff;border:1px solid #444;display:flex;align-items:center;justify-content:center;gap:10px}.oidc-button.primary{color:#111}.oidc-button img{width:20px;height:20px;object-fit:contain;border-radius:4px}.provider-buttons{display:flex;flex-direction:column;gap:10px}.sso-divider{display:flex;align-items:center;gap:10px;color:#666;font-size:12px}.sso-divider::before,.sso-divider::after{content:"";height:1px;background:#333;flex:1}.sso-divider span{text-transform:uppercase;letter-spacing:.08em}.sso-heading{display:flex;align-items:center;gap:12px;padding:8px 2px}.sso-icon{width:38px;height:38px;border-radius:10px;background:#242424;border:1px solid #3a3a3a;display:grid;place-items:center;color:#d68a34;font-size:20px}.sso-heading strong{color:#fff;font-size:15px}.sso-heading p{margin:3px 0 0;color:#999;font-size:12px}.local-credentials{border-top:1px solid #2f2f2f;padding-top:14px;color:#ccc}.local-credentials summary{cursor:pointer;list-style:none;text-align:center;color:#aaa;font-size:13px;padding:8px 0}.local-credentials summary::-webkit-details-marker{display:none}.local-credentials summary::before{content:"▸";display:inline-block;margin-right:7px;color:#d68a34;transition:transform .15s ease}.local-credentials[open] summary::before{transform:rotate(90deg)}.local-fields{display:flex;flex-direction:column;gap:12px;padding-top:10px}</style>
