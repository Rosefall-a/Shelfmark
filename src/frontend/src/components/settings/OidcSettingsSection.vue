<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  fetchDeploymentSettings,
  updateDeploymentSettings,
  type OidcProviderSetting,
} from "../../services/deploymentSettings";

const loading = ref(true);
const saving = ref(false);
const error = ref<string | null>(null);
const saved = ref(false);
const dragIndex = ref<number | null>(null);
const browserOrigin = window.location.origin;
const login = reactive({ default_login_method: "local", enabled: true });
const providers = ref<OidcProviderSetting[]>([]);
const lockedFields = ref<Record<string, boolean>>({});
function responseLocked(name: string) { return lockedFields.value[name] === true; }

function newProvider(): OidcProviderSetting {
  return {
    name: "",
    slug: "",
    issuer_url: "",
    client_id: "",
    client_secret: "",
    scopes: "openid profile email",
    redirect_uri: null,
    groups_claim: "groups",
    admin_group: null,
    user_match_field: "email",
    allow_new_users: true,
    button_text: "Continue with SSO",
    button_image_url: null,
    button_colour: "#d68a34",
    enabled: true,
    show_on_login: true,
    autostart_enabled: true,
    client_secret_configured: false,
  };
}

function slugify(name: string) {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function addProvider() {
  providers.value.push(newProvider());
}

function removeProvider(index: number) {
  providers.value.splice(index, 1);
}

function defaultProviderSlug(provider: OidcProviderSetting) {
  if (!provider.slug) provider.slug = slugify(provider.name);
}

function ensureSlugs() {
  const used = new Set<string>();
  providers.value.forEach((provider, index) => {
    const base = slugify(provider.slug || provider.name) || `provider-${index + 1}`;
    let slug = base;
    let suffix = 2;
    while (used.has(slug)) slug = `${base}-${suffix++}`;
    provider.slug = slug;
    used.add(slug);
  });
}

function redirectUri(provider: OidcProviderSetting) {
  const slug = provider.slug || slugify(provider.name) || "provider-slug";
  return `${browserOrigin}/api/auth/oidc/callback/${slug}`;
}

function moveProvider(index: number, direction: number) {
  const target = index + direction;
  if (target < 0 || target >= providers.value.length) return;
  const items = providers.value;
  [items[index], items[target]] = [items[target], items[index]];
}

function startDrag(index: number) {
  dragIndex.value = index;
}

function dropProvider(index: number) {
  if (dragIndex.value === null || dragIndex.value === index) {
    dragIndex.value = null;
    return;
  }
  const [item] = providers.value.splice(dragIndex.value, 1);
  providers.value.splice(index, 0, item);
  dragIndex.value = null;
}

function endDrag() {
  dragIndex.value = null;
}

onMounted(async () => {
  try {
    const response = await fetchDeploymentSettings();
    login.default_login_method = response.oidc.default_login_method === "sso" ? "sso" : "local";
    login.enabled = response.oidc.enabled !== false;
    lockedFields.value = response.oidc.locked_fields ?? {};
    providers.value = (response.oidc.named_providers ?? []).map((provider) => ({
      ...provider,
      client_secret: "",
      button_colour: provider.button_colour || "#d68a34",
      autostart_enabled: provider.autostart_enabled !== false,
    }));
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load OIDC settings.";
  } finally {
    loading.value = false;
  }
});

async function save() {
  saving.value = true;
  error.value = null;
  saved.value = false;
  try {
    ensureSlugs();
    const providersToSave = providers.value.map((provider) => ({
      ...provider,
      // Always use the address currently being used to access Archive. The
      // displayed redirect URI is intentionally not user-editable.
      redirect_uri: redirectUri(provider),
    }));
    const response = await updateDeploymentSettings({
      oidc_enabled: login.enabled,
      oidc_default_login_method: login.default_login_method,
      oidc_providers_json: JSON.stringify(providersToSave),
    });
    providers.value = (response.oidc.named_providers ?? []).map((provider) => ({
      ...provider,
      client_secret: "",
      button_colour: provider.button_colour || "#d68a34",
      autostart_enabled: provider.autostart_enabled !== false,
    }));
    saved.value = true;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to save OIDC settings.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="section">
    <h2>OpenID Connect / SSO</h2>
    <p class="hint">
      Configure one or more named identity providers. Providers can be reordered, styled,
      shown on the login page, or given independent autostart URLs.
    </p>

    <div v-if="loading">Loading…</div>
    <template v-else>
      <div class="login-panel">
        <div>
          <strong>Enable OIDC</strong>
          <p class="hint">When disabled, partially configured providers may be saved without being used for login.</p>
        </div>
        <input v-model="login.enabled" type="checkbox" :disabled="responseLocked('oidc_enabled')" />
      </div>

      <div class="login-panel">
        <div>
          <strong>Default login method</strong>
          <p class="hint">Choose whether the normal login page initially prioritises local credentials or SSO.</p>
        </div>
        <select v-model="login.default_login_method">
          <option value="local">Local username &amp; password</option>
          <option value="sso">SSO</option>
        </select>
      </div>

      <div class="providers-header">
        <div>
          <h3>Identity providers</h3>
          <p class="hint">Drag using the provider header, or use the arrow controls. Order is reflected on the login
            page.</p>
        </div>
        <button type="button" @click="addProvider">+ Add provider</button>
      </div>

      <div v-if="!providers.length" class="empty">
        No named providers configured. Click <strong>+ Add provider</strong> to create one.
      </div>

      <div v-for="(provider, index) in providers" :key="index" class="provider-card" @dragover.prevent
        @drop="dropProvider(index)">
        <div class="provider-card-head" draggable="true" @dragstart="startDrag(index)" @dragend="endDrag">
          <div class="provider-title">
            <span class="drag-handle" title="Drag to reorder" aria-label="Drag to reorder">⠿</span>
            <div>
              <strong>{{ provider.name || `Provider ${index + 1}` }}</strong>
              <small>{{ provider.slug ? `/${provider.slug}` : "Slug will be generated from the name" }}</small>
            </div>
          </div>
          <div class="provider-actions">
            <button type="button" class="move" :disabled="index === 0" title="Move up"
              @click.stop="moveProvider(index, -1)">↑</button>
            <button type="button" class="move" :disabled="index === providers.length - 1" title="Move down"
              @click.stop="moveProvider(index, 1)">↓</button>
            <button type="button" class="remove" @click.stop="removeProvider(index)">Remove</button>
          </div>
        </div>

        <div class="grid">
          <label><span>Provider name</span><input v-model="provider.name" placeholder="Authentik"
              @blur="defaultProviderSlug(provider)" /></label>
          <label><span>Slug</span><input v-model="provider.slug" placeholder="authentik" autocomplete="off" /></label>
          <label><span>Issuer / discovery URL</span><input v-model="provider.issuer_url"
              placeholder="https://id.example.com" /></label>
          <label><span>Client ID</span><input v-model="provider.client_id" /></label>
          <label><span>Client secret</span><input v-model="provider.client_secret" type="password"
              :placeholder="provider.client_secret_configured ? 'Leave blank to keep saved secret' : 'Required'" /></label>
          <label><span>Scopes</span><input v-model="provider.scopes" /></label>
          <label><span>Groups claim</span><input v-model="provider.groups_claim" placeholder="groups" /></label>
          <label><span>Admin group</span><input v-model="provider.admin_group" placeholder="archive-admins" /></label>
          <label><span>User matching</span><select v-model="provider.user_match_field">
              <option value="email">Email</option>
              <option value="username">Username</option>
            </select></label>
          <label><span>Login button text</span><input v-model="provider.button_text"
              placeholder="Continue with Authentik" /></label>
          <label>
            <span>Button color</span>
            <div class="color-control">
              <input v-model="provider.button_colour" type="color" />
              <input v-model="provider.button_colour" class="color-text" placeholder="#d68a34"
                pattern="^#[0-9a-fA-F]{6}$" />
            </div>
          </label>
          <label><span>Button image URL</span><input v-model="provider.button_image_url"
              placeholder="Optional" /></label>
          <label class="full">
            <span>Redirect URI <small class="generated-label">Automatically generated</small></span>
            <input :value="redirectUri(provider)" class="generated-input" type="text" readonly aria-readonly="true" />
            <small class="field-hint">This is generated from the address currently used to access Archive and
              automatically overrides any previously saved redirect URI when you save.</small>
          </label>
        </div>

        <div class="provider-options">
          <label><input v-model="provider.allow_new_users" type="checkbox" /> Allow new users</label>
          <label><input v-model="provider.enabled" type="checkbox" /> Provider enabled</label>
          <label><input v-model="provider.show_on_login" type="checkbox" /> Show on login page</label>
          <label><input v-model="provider.autostart_enabled" type="checkbox" /> Enable autostart URLs</label>
        </div>

        <div class="autostart">
          <strong>Autostart URL</strong>
          <template v-if="provider.autostart_enabled">
            <span><code>{{ browserOrigin }}/login/{{ provider.slug || slugify(provider.name) || 'provider-slug' }}</code></span>
            <small>This URL starts this provider directly. Disable autostart to make the direct link fall back to the
              normal login page.</small>
          </template>
          <small v-else>Autostart is disabled. The direct link for this provider will redirect to the normal login
            page.</small>
        </div>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="saved" class="success">OIDC settings saved.</p>
      <button :disabled="saving" @click="save">{{ saving ? "Saving…" : "Save OIDC settings" }}</button>
    </template>
  </section>
</template>

<style scoped>
.section {
  display: flex;
  flex-direction: column;
  gap: 16px
}

.section h2 {
  margin: 0;
  color: #fff
}

.hint {
  color: #999;
  font-size: 13px;
  line-height: 1.5
}

.login-panel,
.provider-card {
  border: 1px solid #2f2f2f;
  border-radius: 10px;
  padding: 16px;
  background: #151515
}

.login-panel {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px
}

.login-panel select,
.grid input,
.grid select {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 10px;
  font: inherit
}

.providers-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px
}

.providers-header h3 {
  margin: 0;
  color: #fff
}

.providers-header .hint {
  margin: 4px 0 0
}

.providers-header button,
button {
  background: #d68a34;
  border: 0;
  border-radius: 8px;
  padding: 10px 14px;
  font-weight: 600;
  cursor: pointer
}

.provider-card {
  cursor: default
}

.provider-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 12px;
  cursor: grab;
  user-select: none
}

.provider-card-head:active {
  cursor: grabbing
}

.provider-title {
  display: flex;
  align-items: center;
  gap: 10px
}

.provider-card-head small {
  display: block;
  color: #777;
  margin-top: 3px
}

.drag-handle {
  color: #777;
  font-size: 20px;
  cursor: grab
}

.provider-actions {
  display: flex;
  gap: 6px;
  align-items: center
}

.provider-actions button {
  cursor: pointer
}

.move {
  background: #252525;
  border: 1px solid #3a3a3a;
  color: #ddd;
  padding: 7px 10px
}

.move:disabled {
  opacity: .35;
  cursor: not-allowed
}

.remove {
  background: transparent !important;
  border: 1px solid #633 !important;
  color: #fca5a5 !important
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px
}

.grid label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #ccc;
  font-size: 13px
}

.grid label.full {
  grid-column: 1/-1
}

.color-control {
  display: grid;
  grid-template-columns: 48px 1fr;
  gap: 8px
}

.color-control input[type=color] {
  width: 48px;
  height: 40px;
  padding: 3px;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  cursor: pointer
}

.color-text {
  min-width: 0
}

.generated-input {
  background: #202020 !important;
  color: #777 !important;
  border-color: #333 !important;
  cursor: not-allowed
}

.generated-label {
  color: #777;
  font-weight: 400;
  margin-left: 6px
}

.field-hint {
  color: #666;
  font-size: 11px;
  line-height: 1.4
}

.provider-options {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 14px;
  color: #bbb;
  font-size: 13px
}

.provider-options label {
  display: flex;
  align-items: center;
  gap: 6px
}

.provider-options input {
  accent-color: #d68a34
}

.autostart {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #111;
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: #ccc;
  font-size: 12px
}

.autostart strong {
  color: #fff
}

.autostart code {
  color: #d68a34;
  overflow-wrap: anywhere
}

.autostart small {
  color: #777
}

.empty {
  border: 1px dashed #3a3a3a;
  border-radius: 10px;
  padding: 24px;
  color: #888;
  text-align: center
}

.error {
  color: #fca5a5
}

.success {
  color: #86efac
}

button:disabled {
  opacity: .6
}

@media(max-width:760px) {
  .grid {
    grid-template-columns: 1fr
  }

  .grid label.full {
    grid-column: auto
  }

  .providers-header,
  .login-panel {
    align-items: flex-start;
    flex-direction: column
  }

  .provider-card-head {
    align-items: flex-start;
    flex-direction: column
  }

  .provider-actions {
    width: 100%
  }
}
</style>
