<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import PermissionRiskSummary from "./PermissionRiskSummary.vue";
import type {
  PluginPermissionGrant,
  PluginPermissionRequest,
} from "../../services/pluginPermissions";
import type { PluginDiagnostics, PluginSummary } from "../../services/plugins";
import type {
  PluginUiDocument,
  UiAction,
  UiValues,
} from "../../services/pluginUi";

const props = defineProps<{
  plugin: PluginSummary;
  document: PluginUiDocument | null;
  grants: PluginPermissionGrant[];
  requests: PluginPermissionRequest[];
  diagnostics: PluginDiagnostics | null;
  loading: boolean;
  busy: boolean;
}>();
const emit = defineEmits<{
  close: [];
  save: [values: UiValues];
  action: [action: UiAction, values: UiValues];
  enable: [];
  disable: [];
  retry: [];
  revoke: [grantId: string];
  approve: [requestId: string];
  deny: [requestId: string];
  refresh: [];
  update: [];
  operation: [operation: string, purge?: boolean];
  autoUpdate: [mode: string];
  grant: [key: string];
  deleteHistory: [id: string];
}>();

type Tab = "overview" | "settings" | "permissions" | "diagnostics";
const tab = ref<Tab>("overview");
const closeButton = ref<HTMLButtonElement | null>(null);
const permissions = computed(() => props.plugin.permission_details ?? []);

watch(
  () => props.plugin.plugin_id,
  async () => {
    tab.value = "overview";
    await nextTick();
    closeButton.value?.focus();
  },
  { immediate: true },
);
</script>

<template>
  <Teleport to="body">
    <div
      class="modal-backdrop"
      @click.self="emit('close')"
      @keydown.esc="emit('close')"
    >
      <section
        class="plugin-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="plugin-dialog-title"
      >
        <header class="dialog-header">
          <div>
            <p class="eyebrow">Plugin settings</p>
            <img
              v-if="plugin.icon"
              :src="plugin.icon"
              alt=""
              width="48"
              height="48"
            />
            <h2 id="plugin-dialog-title">{{ plugin.name }}</h2>
            <p>{{ plugin.plugin_id }} · v{{ plugin.version }}</p>
            <p>{{ plugin.description }}</p>
            <p>
              Publisher:
              {{
                plugin.trust?.publisher_identity ??
                plugin.publisher ??
                "Unverified"
              }}
            </p>
          </div>
          <button
            ref="closeButton"
            type="button"
            aria-label="Close plugin settings"
            @click="emit('close')"
          >
            Close
          </button>
        </header>

        <nav aria-label="Plugin settings sections">
          <button
            v-for="item in [
              'overview',
              'settings',
              'permissions',
              'diagnostics',
            ] as Tab[]"
            :key="item"
            type="button"
            :class="{ active: tab === item }"
            @click="tab = item"
          >
            {{ item[0].toUpperCase() + item.slice(1) }}
          </button>
        </nav>

        <p v-if="loading" class="state">Loading plugin details…</p>
        <template v-else>
          <section v-if="tab === 'overview'" class="panel">
            <dl class="overview-grid">
              <div>
                <dt>Status</dt>
                <dd>{{ plugin.status }}</dd>
              </div>
              <div>
                <dt>Health</dt>
                <dd>{{ plugin.health }}</dd>
              </div>
              <div>
                <dt>Enabled</dt>
                <dd>{{ plugin.enabled ? "Yes" : "No" }}</dd>
              </div>
              <div>
                <dt>Compatibility</dt>
                <dd>
                  {{
                    plugin.compatible
                      ? "Compatible"
                      : plugin.compatibility_reason
                  }}
                </dd>
              </div>
            </dl>
            <div class="actions">
              <button
                v-if="
                  plugin.available_update?.update_available ||
                  plugin.staged_update
                "
                :disabled="busy"
                @click="emit('update')"
              >
                Review update
                {{
                  plugin.available_update?.available_version ??
                  plugin.staged_update?.available_version
                }}
              </button>
              <button
                v-if="plugin.enabled"
                :disabled="busy"
                @click="
                  emit(
                    'operation',
                    plugin.status === 'running' ? 'stop' : 'start',
                  )
                "
              >
                {{ plugin.status === "running" ? "Stop" : "Start" }}
              </button>
              <button :disabled="busy" @click="emit('operation', 'reinstall')">
                Reinstall this release
              </button>
              <button
                class="danger"
                :disabled="busy"
                @click="emit('operation', 'reinstall', true)"
              >
                Reinstall and purge data
              </button>
              <button
                class="danger"
                :disabled="busy"
                @click="emit('operation', 'uninstall')"
              >
                Uninstall and purge data
              </button>
              <button
                v-if="plugin.enabled"
                type="button"
                :disabled="busy"
                @click="emit('disable')"
              >
                Disable
              </button>
              <button
                v-else
                type="button"
                :disabled="busy || !plugin.compatible"
                class="primary"
                @click="emit('enable')"
              >
                Enable
              </button>
              <button
                v-if="
                  plugin.status === 'failed' || plugin.status === 'quarantined'
                "
                type="button"
                :disabled="busy"
                @click="emit('retry')"
              >
                Retry
              </button>
            </div>
          </section>

          <section v-else-if="tab === 'settings'" class="panel">
            <h3>Plugin Manager settings</h3>
            <label
              >Automatic updates
              <select
                :value="plugin.automatic_updates ?? 'follow'"
                :disabled="busy || plugin.source?.type !== 'catalogue'"
                @change="
                  emit('autoUpdate', ($event.target as HTMLSelectElement).value)
                "
              >
                <option value="follow">Follow global setting</option>
                <option value="enabled">Enabled</option>
                <option value="disabled">Disabled</option>
              </select>
            </label>
            <p v-if="plugin.source?.type !== 'catalogue'">
              Automatic tracking requires a catalogue installation.
            </p>
            <RouterLink :to="`/plugins/${encodeURIComponent(plugin.plugin_id)}`"
              >Open plugin application pages and configuration</RouterLink
            >
            <h3>Retained package versions</h3>
            <p>
              Version history is separate from plugin data. Rollback preserves
              data and does not restore revoked grants.
            </p>
            <article
              v-for="version in plugin.history ?? []"
              :key="version.id"
              class="grant"
            >
              <strong>v{{ version.version }}</strong>
              <button
                :disabled="busy"
                @click="emit('operation', `rollback/${version.id}`)"
              >
                Roll back
              </button>
              <button
                class="danger"
                :disabled="busy"
                @click="emit('deleteHistory', version.id)"
              >
                Delete retained package
              </button>
            </article>
          </section>

          <section v-else-if="tab === 'permissions'" class="panel">
            <PermissionRiskSummary :permissions="permissions" />
            <article
              v-for="permission in permissions"
              :key="permission.key"
              class="grant"
            >
              <div>
                <strong>{{ permission.title }}</strong
                ><small
                  >{{ permission.capability }} ·
                  {{ permission.risk }} risk</small
                >
              </div>
              <button
                v-if="
                  !grants.some(
                    (grant) =>
                      grant.active &&
                      `${grant.capability}:v${grant.capability_version}` ===
                        permission.key,
                  )
                "
                :disabled="busy"
                @click="emit('grant', permission.key)"
              >
                Review and grant
              </button>
            </article>
            <p class="state">
              Permissions are enforced by the gateway and can be revoked
              immediately.
            </p>
            <article
              v-for="request in requests"
              :key="request.id"
              class="grant pending"
            >
              <div>
                <strong>{{ request.capability }}</strong>
                <small
                  >v{{ request.capability_version }} · Pending request</small
                >
                <p>{{ request.rationale }}</p>
              </div>
              <div class="request-actions">
                <button
                  type="button"
                  :disabled="busy"
                  @click="emit('deny', request.id)"
                >
                  Deny
                </button>
                <button
                  type="button"
                  :disabled="busy"
                  class="primary"
                  @click="emit('approve', request.id)"
                >
                  Allow
                </button>
              </div>
            </article>
            <p v-if="!grants.length" class="state">
              No permission grants are recorded for this plugin.
            </p>
            <article v-for="grant in grants" :key="grant.id" class="grant">
              <div>
                <strong>{{ grant.capability }}</strong>
                <small
                  >v{{ grant.capability_version }} ·
                  {{
                    grant.user_id
                      ? `User ${grant.user_id}`
                      : "All authenticated users"
                  }}</small
                >
              </div>
              <button
                v-if="grant.active"
                type="button"
                :disabled="busy"
                class="danger"
                @click="emit('revoke', grant.id)"
              >
                Revoke
              </button>
              <span v-else>Revoked</span>
            </article>
          </section>

          <section v-else class="panel diagnostics">
            <dl class="diagnostic-summary">
              <div>
                <dt>Runtime availability</dt>
                <dd>
                  {{
                    plugin.runtime_available === false
                      ? "Unavailable"
                      : "Available"
                  }}
                </dd>
              </div>
              <div>
                <dt>Isolation</dt>
                <dd>{{ plugin.runtime?.mechanism ?? "Unknown" }}</dd>
              </div>
              <div>
                <dt>Bubblewrap</dt>
                <dd>
                  {{
                    plugin.runtime?.bubblewrap_available
                      ? "Usable"
                      : "Unavailable"
                  }}
                </dd>
              </div>
              <div>
                <dt>Sandbox</dt>
                <dd>
                  {{
                    plugin.runtime?.sandbox_available
                      ? "Active"
                      : "Reduced isolation"
                  }}
                </dd>
              </div>
              <div>
                <dt>Last error</dt>
                <dd>
                  {{
                    plugin.last_error ??
                    plugin.last_update_error ??
                    plugin.runtime?.last_error ??
                    "None"
                  }}
                </dd>
              </div>
            </dl>
            <div class="diagnostic-heading">
              <h3>Runtime diagnostics</h3>
              <button type="button" :disabled="busy" @click="emit('refresh')">
                Refresh
              </button>
            </div>
            <dl v-if="diagnostics" class="diagnostic-summary">
              <div>
                <dt>Status</dt>
                <dd>{{ diagnostics.status }}</dd>
              </div>
              <div>
                <dt>Last exit code</dt>
                <dd>{{ diagnostics.last_exit_code ?? "—" }}</dd>
              </div>
            </dl>
            <ol v-if="diagnostics?.events.length" class="event-list">
              <li
                v-for="event in diagnostics.events"
                :key="event.sequence"
                :class="`level-${event.level}`"
              >
                <div class="event-heading">
                  <time :datetime="event.timestamp">{{
                    new Date(event.timestamp).toLocaleString()
                  }}</time>
                  <strong>{{ event.level }}</strong>
                  <code>{{ event.event }}</code>
                </div>
                <p>{{ event.message }}</p>
                <small v-if="event.correlation_id">
                  Correlation: {{ event.correlation_id }}
                </small>
              </li>
            </ol>
            <p v-else class="state">No runtime diagnostics are available.</p>
          </section>
        </template>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--ui-z-dialog);
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.72);
}
.plugin-dialog {
  width: min(980px, 100%);
  max-height: 90vh;
  overflow: auto;
  box-sizing: border-box;
  padding: 24px;
  background: #151515;
  color: #f4f4f4;
  border: 1px solid #3b3b3b;
  border-radius: 14px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.65);
}
.dialog-header,
.diagnostic-heading,
.actions,
.grant,
.request-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.pending {
  border-color: #76512a;
}
.pending p {
  margin: 6px 0 0;
  color: #c9c9c9;
}
.dialog-header h2,
.dialog-header p,
h3 {
  margin: 0;
  color: var(--ui-text);
}
.eyebrow {
  color: #d68a34 !important;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.dialog-header p,
.state,
small,
dt,
.grant > span {
  color: #aaa;
}
.dialog-header > button,
nav button,
.actions button,
.grant button,
.diagnostic-heading button {
  padding: 8px 12px;
  border: 1px solid #444;
  border-radius: 8px;
  background: #242424;
  color: #eee;
  cursor: pointer;
}
nav {
  display: flex;
  gap: 6px;
  overflow: auto;
  margin: 20px 0;
  border-bottom: 1px solid #303030;
}
nav button {
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  background: transparent;
}
nav button.active {
  color: #f3a657;
  border-bottom-color: #d68a34;
}
.panel {
  min-height: 220px;
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.overview-grid div {
  padding: 14px;
  background: #0d0d0d;
  border-radius: 9px;
}
.overview-grid dd {
  margin: 5px 0 0;
}
.actions {
  justify-content: flex-start;
  margin-top: 18px;
}
.actions .primary {
  background: #d68a34;
  color: #111;
  border-color: #d68a34;
  font-weight: 700;
}
.grant {
  padding: 13px 0;
  border-bottom: 1px solid #303030;
}
.grant > div {
  display: grid;
  gap: 4px;
}
.grant .danger {
  border-color: #8b3434;
  color: #fecaca;
}
.diagnostic-summary {
  display: flex;
  gap: 24px;
}
.diagnostic-summary dd {
  margin: 2px 0 0;
}
.event-list {
  display: grid;
  gap: 8px;
  max-height: 340px;
  overflow: auto;
  padding: 0;
  list-style: none;
}
.event-list li {
  padding: 12px;
  border-left: 3px solid #666;
  border-radius: 6px;
  background: #080808;
}
.event-list li.level-warning {
  border-left-color: #d68a34;
}
.event-list li.level-error {
  border-left-color: #d65a5a;
}
.event-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.event-heading time,
.event-heading code {
  color: #aaa;
}
.event-heading strong {
  text-transform: uppercase;
}
.event-list p {
  margin: 8px 0 0;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
@media (max-width: 620px) {
  .modal-backdrop {
    padding: 0;
  }
  .plugin-dialog {
    height: 100%;
    max-height: none;
    border-radius: 0;
  }
  .overview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
