<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { PluginInstallPreview } from "../../services/plugins";

const props = defineProps<{ preview: PluginInstallPreview; busy: boolean }>();
const emit = defineEmits<{
  cancel: [];
  confirm: [approvedPermissions: string[]];
}>();

const approved = ref(new Set<string>());
const trustAccepted = ref(false);
const cancelButton = ref<HTMLButtonElement | null>(null);

watch(
  () => props.preview.plugin_id,
  async () => {
    approved.value = new Set();
    trustAccepted.value = props.preview.trust_status === "trusted";
    await nextTick();
    cancelButton.value?.focus();
  },
  { immediate: true },
);

const fullApiRequested = computed(() =>
  props.preview.permissions.some(
    (permission) => permission.capability === "api.full",
  ),
);

const canInstall = computed(
  () => props.preview.trust_status === "trusted" || trustAccepted.value,
);

function toggle(key: string, checked: boolean) {
  const next = new Set(approved.value);
  if (checked) next.add(key);
  else next.delete(key);
  approved.value = next;
}

function close() {
  if (!props.busy) emit("cancel");
}
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop" @click.self="close" @keydown.esc="close">
      <section
        class="consent-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="plugin-consent-title"
      >
        <header>
          <div>
            <p class="eyebrow">Plugin installation</p>
            <h2 id="plugin-consent-title">Review {{ preview.name }}</h2>
            <p class="identity">
              {{ preview.plugin_id }} · v{{ preview.version }}
            </p>
          </div>
          <span class="trust" :class="preview.trust_status">
            {{
              preview.trust_status === "trusted"
                ? "Verified publisher"
                : "Untrusted package"
            }}
          </span>
        </header>

        <p v-if="preview.description" class="description">
          {{ preview.description }}
        </p>
        <dl class="metadata">
          <div>
            <dt>Publisher</dt>
            <dd>{{ preview.publisher || "Unsigned" }}</dd>
          </div>
          <div>
            <dt>Host versions</dt>
            <dd>{{ preview.application_version_range }}</dd>
          </div>
          <div>
            <dt>SDK versions</dt>
            <dd>{{ preview.sdk_version_range }}</dd>
          </div>
          <div>
            <dt>Package digest</dt>
            <dd class="digest">{{ preview.digest }}</dd>
          </div>
        </dl>

        <div
          v-if="preview.trust_status === 'untrusted'"
          class="warning"
          role="alert"
        >
          <strong>The publisher could not be verified.</strong>
          <p>
            {{
              preview.trust_warning ||
              "Install only if you trust the package source."
            }}
          </p>
          <label>
            <input v-model="trustAccepted" type="checkbox" />
            I understand this package is untrusted and still want to install it.
          </label>
        </div>

        <div
          v-if="fullApiRequested"
          class="warning full-api-warning"
          role="alert"
        >
          <strong>Full API access is extremely broad.</strong>
          <p>
            Full API access allows plugins to read and modify all user data.
            Only enable this for plugins you trust. It is disabled unless you
            explicitly select this permission.
          </p>
        </div>

        <section
          class="permissions"
          aria-labelledby="requested-permissions-title"
        >
          <div class="section-heading">
            <div>
              <h3 id="requested-permissions-title">Requested permissions</h3>
              <p>
                Grant only the access this plugin needs. Unchecked permissions
                are denied.
              </p>
            </div>
            <span
              >{{ approved.size }} of
              {{ preview.permissions.length }} granted</span
            >
          </div>
          <p v-if="!preview.permissions.length" class="empty">
            This plugin requests no host permissions.
          </p>
          <label
            v-for="permission in preview.permissions"
            :key="permission.key"
            class="permission"
          >
            <input
              type="checkbox"
              :checked="approved.has(permission.key)"
              @change="
                toggle(
                  permission.key,
                  ($event.target as HTMLInputElement).checked,
                )
              "
            />
            <span class="permission-copy">
              <span class="permission-title">
                <strong>{{ permission.title }}</strong>
                <span class="risk" :class="permission.risk">
                  {{ permission.risk }} risk
                </span>
              </span>
              <small
                >{{ permission.category }} · {{ permission.capability }} v{{
                  permission.capability_version
                }}
                · {{ permission.rationale }}</small
              >
              <small v-if="permission.children.length">
                Parent permission includes:
                {{ permission.children.join(", ") }}
              </small>
            </span>
          </label>
        </section>

        <p v-if="preview.dependencies.length" class="dependencies">
          Dependencies:
          {{
            preview.dependencies
              .map(
                (item) =>
                  `${item.plugin_id} ${item.version_range}${item.optional ? " (optional)" : ""}`,
              )
              .join(", ")
          }}
        </p>

        <footer>
          <button
            ref="cancelButton"
            type="button"
            :disabled="busy"
            @click="close"
          >
            Cancel
          </button>
          <button
            type="button"
            class="primary"
            :disabled="busy || !canInstall"
            @click="emit('confirm', [...approved])"
          >
            {{ busy ? "Installing…" : "Install with selected access" }}
          </button>
        </footer>
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
.consent-dialog {
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
}
header,
.section-heading,
footer,
.permission-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
h2,
h3,
p {
  margin-top: 0;
}
.eyebrow {
  margin-bottom: 4px;
  color: #d68a34;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.identity,
.description,
.section-heading p,
.empty,
.dependencies,
small {
  color: #aaa;
}
.trust,
.risk {
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
  white-space: nowrap;
}
.trust.trusted,
.risk.low {
  background: #173f2a;
  color: #9ae6b4;
}
.trust.untrusted,
.risk.high,
.risk.critical {
  background: #571d1d;
  color: #fecaca;
}
.risk.medium {
  background: #503a13;
  color: #fde68a;
}
.metadata {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 20px 0;
}
.metadata div {
  min-width: 0;
  padding: 10px;
  background: #0d0d0d;
  border-radius: 8px;
}
.metadata dt {
  font-size: 0.72rem;
  color: #777;
}
.metadata dd {
  margin: 4px 0 0;
}
.digest {
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: monospace;
  font-size: 0.75rem;
}
.warning {
  margin: 16px 0;
  padding: 14px;
  border: 1px solid #8b3434;
  border-radius: 10px;
  background: #2d1515;
}
.warning.full-api-warning {
  border-color: #9b5b1b;
  background: #321f0e;
}
.warning p {
  margin: 6px 0 10px;
  color: #f0b6b6;
}
.permissions {
  margin-top: 22px;
}
.section-heading p {
  margin-bottom: 0;
}
.section-heading > span {
  color: #aaa;
  font-size: 0.8rem;
}
.permission {
  display: flex;
  gap: 12px;
  margin-top: 10px;
  padding: 13px;
  border: 1px solid #303030;
  border-radius: 10px;
  background: #111;
  cursor: pointer;
}
.permission input {
  margin-top: 4px;
}
.permission-copy {
  display: grid;
  gap: 5px;
  min-width: 0;
  flex: 1;
}
.permission-title {
  align-items: center;
}
.dependencies {
  margin-top: 18px;
  font-size: 0.8rem;
}
footer {
  justify-content: flex-end;
  margin-top: 24px;
  padding-top: 18px;
  border-top: 1px solid #2b2b2b;
}
button {
  padding: 9px 14px;
  border: 1px solid #444;
  border-radius: 8px;
  background: #242424;
  color: #eee;
  cursor: pointer;
}
button.primary {
  background: #d68a34;
  color: #111;
  border-color: #d68a34;
  font-weight: 700;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
@media (max-width: 620px) {
  .modal-backdrop {
    padding: 0;
  }
  .consent-dialog {
    height: 100%;
    max-height: none;
    border-radius: 0;
  }
  .metadata {
    grid-template-columns: 1fr;
  }
  header,
  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
