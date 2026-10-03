<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import PermissionRiskSummary from "./PermissionRiskSummary.vue";
import DOMPurify from "dompurify";
import { marked } from "marked";
import type {
  PluginInstallConfirmation,
  PluginInstallPermission,
  PluginInstallPreview,
} from "../../services/plugins";

const props = defineProps<{ preview: PluginInstallPreview; busy: boolean }>();
const readme = computed(() =>
  DOMPurify.sanitize(
    marked.parse(props.preview.readme ?? "", { async: false }),
  ),
);
const emit = defineEmits<{
  cancel: [];
  confirm: [confirmation: PluginInstallConfirmation];
}>();

const approved = ref(new Set<string>());
const trustAccepted = ref(false);
const dangerousConfirmed = ref(false);
const adminPassword = ref("");
const expandedCategories = ref(new Set<string>());
const cancelButton = ref<HTMLButtonElement | null>(null);
const content = ref<HTMLElement | null>(null);

watch(
  () => [props.preview.plugin_id, props.preview.version, props.preview.digest],
  async () => {
    approved.value = new Set();
    trustAccepted.value = props.preview.trust_status === "trusted";
    dangerousConfirmed.value = false;
    adminPassword.value = "";
    expandedCategories.value = new Set(
      props.preview.permissions.map((permission) => permission.category),
    );
    await nextTick();
    cancelButton.value?.focus();
    content.value?.scrollTo({ top: 0 });
  },
  { immediate: true },
);

const selectablePermissions = computed(() =>
  props.preview.operation === "update"
    ? props.preview.permissions.filter((permission) => permission.new)
    : props.preview.permissions,
);

const permissionCategories = computed(() => {
  const grouped = new Map<string, PluginInstallPermission[]>();
  for (const permission of props.preview.permissions) {
    const items = grouped.get(permission.category) ?? [];
    items.push(permission);
    grouped.set(permission.category, items);
  }
  return [...grouped.entries()].map(([name, permissions]) => ({
    name,
    permissions,
  }));
});

function selectableInCategory(category: string) {
  return selectablePermissions.value.filter(
    (permission) => permission.category === category,
  );
}

const dangerousApproved = computed(() =>
  selectablePermissions.value.filter(
    (permission) =>
      permission.highly_privileged && approved.value.has(permission.key),
  ),
);

const reauthenticationRequired = computed(
  () =>
    props.preview.trust_status !== "trusted" &&
    dangerousApproved.value.length > 0,
);

const canInstall = computed(() => {
  const trustAcceptedOrVerified =
    props.preview.trust_status === "trusted" || trustAccepted.value;
  const reauthenticated =
    !reauthenticationRequired.value ||
    (dangerousConfirmed.value && adminPassword.value.length > 0);
  return (
    props.preview.installable &&
    props.preview.dependency_ready &&
    trustAcceptedOrVerified &&
    reauthenticated
  );
});

const trustLabel = computed(
  () =>
    ({
      trusted:
        props.preview.publisher_channel === "official"
          ? "Official · verified signature"
          : props.preview.publisher_channel === "demo"
            ? "Demo/example · verified signature"
            : "Signed · trusted community publisher",
      unknown_publisher: "Signed · unknown publisher key",
      invalid_signature: "Signed · invalid signature",
      unsigned: "Unsigned package",
    })[props.preview.trust_status],
);

function isDescendant(permission: PluginInstallPermission, capability: string) {
  let parent = permission.parent;
  const seen = new Set<string>();
  while (parent && !seen.has(parent)) {
    if (parent === capability) return true;
    seen.add(parent);
    parent =
      props.preview.permissions.find(
        (candidate) => candidate.capability === parent,
      )?.parent ?? null;
  }
  return false;
}

function toggle(key: string, checked: boolean) {
  const permission = selectablePermissions.value.find(
    (item) => item.key === key,
  );
  if (!permission) return;
  const next = new Set(approved.value);
  for (const candidate of selectablePermissions.value) {
    if (
      candidate.key === key ||
      isDescendant(candidate, permission.capability)
    ) {
      if (checked) next.add(candidate.key);
      else next.delete(candidate.key);
    }
  }
  approved.value = next;
}

function toggleCategory(category: string, checked: boolean) {
  const next = new Set(approved.value);
  for (const permission of selectablePermissions.value) {
    if (permission.category !== category) continue;
    if (checked) next.add(permission.key);
    else next.delete(permission.key);
  }
  approved.value = next;
}

function toggleExpanded(category: string) {
  const next = new Set(expandedCategories.value);
  if (next.has(category)) next.delete(category);
  else next.add(category);
  expandedCategories.value = next;
}

function confirm() {
  emit("confirm", {
    approvedPermissions: [...approved.value],
    adminPassword: adminPassword.value || undefined,
    confirmDangerous: dangerousConfirmed.value,
  });
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
        ref="content"
        role="dialog"
        aria-modal="true"
        aria-labelledby="plugin-consent-title"
      >
        <header>
          <div>
            <p class="eyebrow">Plugin installation</p>
            <img
              v-if="preview.icon"
              :src="preview.icon"
              alt=""
              width="48"
              height="48"
            />
            <h2 id="plugin-consent-title">Review {{ preview.name }}</h2>
            <p class="identity">
              {{ preview.plugin_id }} · v{{ preview.version }}
            </p>
          </div>
          <span class="trust" :class="preview.trust_status">{{
            trustLabel
          }}</span>
        </header>
        <details v-if="readme" class="readme">
          <summary>Plugin documentation</summary>
          <article v-html="readme" />
        </details>

        <p v-if="preview.description" class="description">
          {{ preview.description }}
        </p>
        <dl class="metadata">
          <div>
            <dt>Publisher</dt>
            <dd>
              {{
                preview.publisher || preview.publisher_key_id || "Not supplied"
              }}
              <small v-if="preview.publisher_key_id"
                >Key {{ preview.publisher_key_id }}</small
              >
            </dd>
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
          v-if="preview.trust_status !== 'trusted'"
          class="warning"
          role="alert"
        >
          <strong>{{ trustLabel }}</strong>
          <p>
            {{
              preview.trust_warning ||
              "Install only if you trust the package source."
            }}
          </p>
          <label>
            <input v-model="trustAccepted" type="checkbox" />
            I understand this package is not cryptographically trusted and want
            to continue.
          </label>
        </div>

        <div v-if="preview.identity_warning" class="warning" role="alert">
          <strong>Permission grants cannot be inherited</strong>
          <p>{{ preview.identity_warning }}</p>
        </div>

        <div
          v-if="
            preview.permissions.some(
              (permission) => permission.highly_privileged,
            )
          "
          class="warning full-api-warning"
          role="alert"
        >
          <strong>This package requests highly privileged access.</strong>
          <p>
            Critical capabilities can alter host behavior or sensitive data.
            They remain disabled unless selected below.
          </p>
        </div>

        <section
          class="permissions"
          aria-labelledby="requested-permissions-title"
        >
          <div class="section-heading">
            <div>
              <h3 id="requested-permissions-title">
                {{
                  preview.operation === "update"
                    ? "Permission changes"
                    : "Requested permissions"
                }}
              </h3>
              <p>
                Grant only the access this plugin needs. Unchecked permissions
                are denied.
              </p>
            </div>
            <span
              >{{ approved.size }} of {{ selectablePermissions.length }} newly
              granted</span
            >
          </div>
          <p v-if="!preview.permissions.length" class="empty">
            This plugin requests no host permissions.
          </p>
          <PermissionRiskSummary :permissions="preview.permissions" />
          <article
            v-for="category in permissionCategories"
            :key="category.name"
            class="permission-category"
          >
            <header class="category-header">
              <button
                type="button"
                class="disclosure"
                @click="toggleExpanded(category.name)"
              >
                {{ expandedCategories.has(category.name) ? "▾" : "▸" }}
                {{ category.name }}
                — {{ category.permissions.length }}
                {{ category.permissions.length === 1 ? "scope" : "scopes" }}
              </button>
              <label>
                <input
                  type="checkbox"
                  :disabled="selectableInCategory(category.name).length === 0"
                  :checked="
                    selectableInCategory(category.name).length > 0 &&
                    selectableInCategory(category.name).every((item) =>
                      approved.has(item.key),
                    )
                  "
                  @change="
                    toggleCategory(
                      category.name,
                      ($event.target as HTMLInputElement).checked,
                    )
                  "
                />
                Approve subtree
              </label>
            </header>
            <PermissionRiskSummary :permissions="category.permissions" />
            <div v-if="expandedCategories.has(category.name)">
              <label
                v-for="permission in category.permissions"
                :key="permission.key"
                class="permission"
                :class="{
                  privileged: permission.highly_privileged,
                  retained: preview.operation && !permission.new,
                }"
              >
                <input
                  type="checkbox"
                  :disabled="preview.operation === 'update' && !permission.new"
                  :checked="
                    preview.operation === 'update' && !permission.new
                      ? true
                      : approved.has(permission.key)
                  "
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
                    <span class="risk" :class="permission.risk"
                      >{{ permission.risk }} risk</span
                    >
                  </span>
                  <small
                    >{{ permission.capability }} v{{
                      permission.capability_version
                    }}
                    · {{ permission.rationale }}</small
                  >
                  <small v-if="preview.operation && !permission.new"
                    >Existing reviewed permission retained</small
                  >
                  <small v-else-if="permission.children.length"
                    >Approving this parent includes its requested
                    subtree.</small
                  >
                </span>
              </label>
            </div>
          </article>
        </section>

        <section v-if="preview.dependencies.length" class="dependencies">
          <h3>Dependencies</h3>
          <ul>
            <li
              v-for="dependency in preview.dependencies"
              :key="dependency.plugin_id"
              :class="dependency.state"
            >
              <strong>{{ dependency.plugin_id }}</strong>
              {{ dependency.version_range }} ·
              {{ dependency.state.replaceAll("_", " ") }}
              <span v-if="dependency.installed_version">
                (installed {{ dependency.installed_version }})</span
              >
              <span v-if="dependency.available_version">
                (available {{ dependency.available_version }})</span
              >
              <span v-if="dependency.optional"> · optional</span>
            </li>
          </ul>
          <p v-if="preview.dependency_conflicts.length" class="warning">
            {{ preview.dependency_conflicts.join("; ") }}
          </p>
        </section>

        <section v-if="preview.release_notes" class="release-notes">
          <h3>Release notes</h3>
          <pre>{{ preview.release_notes }}</pre>
        </section>

        <div
          v-if="reauthenticationRequired"
          class="warning reauthentication"
          role="alert"
        >
          <strong>Administrator reauthentication required</strong>
          <p>
            This unverified package will receive:
            {{ dangerousApproved.map((item) => item.title).join(", ") }}.
          </p>
          <label>
            Administrator password
            <input
              v-model="adminPassword"
              type="password"
              autocomplete="current-password"
            />
          </label>
          <label>
            <input v-model="dangerousConfirmed" type="checkbox" />
            I explicitly confirm granting these dangerous capabilities to an
            unverified package.
          </label>
        </div>

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
            @click="confirm"
          >
            {{
              busy
                ? "Applying…"
                : preview.operation === "update"
                  ? "Update with selected access"
                  : "Install with selected access"
            }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.readme {
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.readme :deep(h1) {
  font-size: 1.5rem;
  margin: 18px 0 12px;
  color: var(--ui-text);
}
.readme :deep(h2),
.readme :deep(h3) {
  color: var(--ui-text);
  margin: 18px 0 10px;
}
.readme :deep(p) {
  margin: 10px 0;
}
.readme :deep(img) {
  max-width: 100%;
}
.readme :deep(pre) {
  overflow: auto;
  padding: 12px;
  background: #0d0d0d;
  border-radius: 8px;
}
.readme :deep(table) {
  width: 100%;
  border-collapse: collapse;
}
.readme :deep(td),
.readme :deep(th) {
  padding: 8px;
  border: 1px solid var(--ui-border);
  text-align: left;
}
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
h2,
h3 {
  color: var(--ui-text);
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
.trust.unknown_publisher,
.trust.invalid_signature,
.trust.unsigned,
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
.permission.privileged {
  border-color: #9b5b1b;
  background: #25170c;
}
.permission.retained {
  opacity: 0.72;
}
.permission-category {
  margin-top: 12px;
  border: 1px solid #303030;
  border-radius: 10px;
  overflow: hidden;
}
.category-header {
  align-items: center;
  padding: 10px 12px;
  background: #0d0d0d;
}
.category-header label {
  display: flex;
  gap: 7px;
  align-items: center;
  font-size: 0.8rem;
}
.disclosure {
  border: 0;
  background: transparent;
  font-weight: 700;
}
.dependencies ul {
  padding-left: 20px;
}
.dependencies .missing,
.dependencies .incompatible {
  color: #fecaca;
}
.dependencies .available {
  color: #fde68a;
}
.release-notes pre {
  max-height: 220px;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
  background: #0d0d0d;
  border-radius: 8px;
}
.reauthentication > label {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 10px;
}
.reauthentication input[type="password"] {
  flex: 1;
  min-width: 0;
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
