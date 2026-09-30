<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  createInitialAdmin,
  fetchSetupConfiguration,
  fetchSetupStatus,
  saveSetupConfiguration,
  type SetupConfiguration,
  type SetupField,
  type SetupSection,
} from "../services/setup";
import { currentUser, checkAuth } from "../state/auth";

const route = useRoute();
const router = useRouter();

const configuration = ref<SetupConfiguration | null>(null);
const selectedSections = ref<string[]>([]);
const values = ref<Record<string, unknown>>({});
const currentSection = ref("welcome");
const loading = ref(true);
const saving = ref(false);
const error = ref<string | null>(null);
const saved = ref(false);

const sections = computed(() => (configuration.value?.sections ?? []).filter((section) => section.visible));
const current = computed(() =>
  sections.value.find((section) => section.id === currentSection.value),
);
const selected = computed(() =>
  sections.value.filter((section) => selectedSections.value.includes(section.id)),
);
const isLastSelectedSection = computed(() =>
  currentSection.value === selected.value[selected.value.length - 1]?.id,
);
const canAdvance = computed(() =>
  currentSection.value !== "welcome" && !isLastSelectedSection.value,
);
const optionalSections = computed(() =>
  sections.value.filter((section) => !section.required),
);
const requiredSections = computed(() =>
  sections.value.filter((section) => section.required),
);
const actionLabel = computed(() => saving.value ? "Saving…" : "Finish setup");
const welcomeBlocked = computed(() =>
  requiredSections.value.some((section) => section.blocked),
);
function fieldValue(field: SetupField): unknown {
  if (field.name in values.value) return values.value[field.name];
  return field.value;
}

function setField(field: SetupField, value: unknown) {
  values.value[field.name] = value;
}

function sectionIsComplete(section: SetupSection): boolean {
  const groups = new Map<string, SetupField[]>();
  for (const field of section.fields) {
    if (!field.required_group) continue;
    const group = field.required_group.split(":")[0];
    const variant = field.required_group.split(":")[1] ?? "default";
    const key = `${group}:${variant}`;
    const members = groups.get(key) ?? [];
    members.push(field);
    groups.set(key, members);
  }

  for (const group of new Set([...groups.keys()].map((key) => key.split(":")[0]))) {
    const groupName = group;
    const variants = [...groups.entries()]
      .filter(([key]) => key.startsWith(`${groupName}:`))
      .map(([, fields]) => fields);
    if (!variants.some((fields) => fields.every((field) => field.configured || hasValue(fieldValue(field))))) {
      return false;
    }
  }

  return section.fields
    .filter((field) => field.required && !field.required_group)
    .every((field) => field.configured || hasValue(fieldValue(field)));
}

function hasValue(value: unknown): boolean {
  if (typeof value === "boolean") return true;
  return value !== null && value !== undefined && String(value).trim() !== "";
}

function optionalSectionAction(section: SetupSection): string {
  if (section.status === "blocked_by_env") return "Needs .env";
  if (section.status === "completed_by_env") return "Completed by .env";
  return selectedSections.value.includes(section.id) ? "Remove" : "Add";
}

function inputValue(field: SetupField): string | number | undefined {
  const value = fieldValue(field);
  return typeof value === "string" || typeof value === "number" ? value : undefined;
}

function fieldPlaceholder(field: SetupField): string {
  return field.secret && field.configured
    ? "Already configured — leave blank to keep it"
    : field.placeholder;
}

function visibleFields(section: SetupSection): SetupField[] {
  return section.fields.filter((field) => field.visible);
}

function fieldGroups(section: SetupSection): Array<{ heading: string | null; fields: SetupField[] }> {
  const unheaded = visibleFields(section).filter((field) => !field.heading);
  const groups = new Map<string, SetupField[]>();
  for (const field of visibleFields(section)) {
    if (!field.heading) continue;
    groups.set(field.heading, [...(groups.get(field.heading) ?? []), field]);
  }
  const result: Array<{ heading: string | null; fields: SetupField[] }> = [];
  if (unheaded.length) result.push({ heading: null, fields: unheaded });
  for (const [heading, fields] of groups) result.push({ heading, fields });
  return result;
}

function statusLabel(section: SetupSection): string {
  if (section.status === "completed_by_env") return "Completed by .env";
  if (sectionIsComplete(section)) return "Complete";
  if (section.status === "partial") return "Partially configured";
  return "Not configured";
}

function initialize(config: SetupConfiguration) {
  configuration.value = config;
  values.value = {};

  // Required sections and the explicitly defaulted optional sections are
  // selected automatically. OIDC is different: a partial environment
  // configuration must not implicitly enable it or force the user into the
  // provider page. A complete environment configuration may still select it
  // automatically.
  selectedSections.value = config.sections
    .filter(
      (section) =>
        section.required ||
        (!section.required && section.default) ||
        section.status === "completed_by_env" ||
        (
          section.id !== "oidc" &&
          (section.status === "partial" || section.status === "configured" || section.env_configured)
        ),
    )
    .map((section) => section.id);

  for (const section of config.sections) {
    for (const field of visibleFields(section)) {
      if (field.secret) {
        // Secrets are intentionally never returned. A configured secret is
        // represented by an empty input plus configured/locked metadata.
        values.value[field.name] = "";
      } else {
        values.value[field.name] = field.value;
      }
    }
  }

  currentSection.value = "welcome";
}

onMounted(async () => {
  try {
    const [status, config] = await Promise.all([
      fetchSetupStatus(),
      fetchSetupConfiguration(),
    ]);

    if (!status.setup_required && status.startup_mode === "development") {
      await checkAuth();
      await router.replace("/");
      return;
    }

    if (!status.setup_required) {
      await checkAuth();
      if (!currentUser.value) {
        await router.replace("/login");
        return;
      }
    }

    if (route.query.backend_error) {
      const query = { ...route.query };
      delete query.backend_error;
      await router.replace({ path: "/setup", query });
    }

    initialize(config);
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Unable to load setup configuration.";
  } finally {
    loading.value = false;
  }
});

function toggleOptional(section: SetupSection) {
  if (section.required || section.status === "completed_by_env") return;
  const index = selectedSections.value.indexOf(section.id);
  if (index >= 0) {
    selectedSections.value.splice(index, 1);
    if (currentSection.value === section.id) currentSection.value = "welcome";
  } else {
    selectedSections.value.push(section.id);
  }
}

function nextSection() {
  const ids = ["welcome", ...selected.value.map((section) => section.id)];
  const index = ids.indexOf(currentSection.value);
  currentSection.value = ids[Math.min(index + 1, ids.length - 1)];
}

function previousSection() {
  const ids = ["welcome", ...selected.value.map((section) => section.id)];
  const index = ids.indexOf(currentSection.value);
  currentSection.value = ids[Math.max(index - 1, 0)];
}

function inputType(field: SetupField): string {
  if (field.type === "secret") return "password";
  if (field.type === "email") return "email";
  if (field.type === "url") return "url";
  if (field.type === "integer") return "number";
  return "text";
}

function fieldRequired(field: SetupField): boolean {
  if (current.value?.id === "oidc" &&
    ["OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"].includes(field.name)) {
    return true;
  }
  return field.required;
}

function textFieldValue(field: SetupField | undefined): string {
  const value = field ? fieldValue(field) : undefined;
  return value === null || value === undefined ? "" : String(value);
}

function payloadValues(): Record<string, unknown> {
  const result: Record<string, unknown> = {};

  for (const section of selected.value) {
    for (const field of visibleFields(section)) {
      if (field.locked) continue;
      const value = fieldValue(field);

      // Empty secret inputs mean “leave the existing secret alone”.
      if (field.secret && !String(value ?? "").trim()) continue;
      if (value === undefined || value === null) continue;
      result[field.name] = value;
    }
  }

  return result;
}

async function submit() {
  error.value = null;
  saved.value = false;

  for (const section of selected.value) {
    const groupVariants = new Map<string, SetupField[]>();
    for (const field of visibleFields(section)) {
      if (field.required_group) {
        const [group, variant = "default"] = field.required_group.split(":");
        const key = `${group}:${variant}`;
        groupVariants.set(key, [...(groupVariants.get(key) ?? []), field]);
      }
    }

    const groups = new Set(
      [...groupVariants.keys()].map((key) => key.split(":")[0]),
    );
    for (const group of groups) {
      const satisfied = [...groupVariants.entries()]
        .filter(([key]) => key.startsWith(`${group}:`))
        .some(([, fields]) => fields.every((field) => field.configured || hasValue(fieldValue(field))));
      if (!satisfied) {
        currentSection.value = section.id;
        error.value = `A complete configuration is required for one of the “${group}” options.`;
        return;
      }
    }

    for (const field of visibleFields(section)) {
      const required = section.id === "oidc"
        ? ["OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"].includes(field.name)
        : field.required && !field.required_group;
      if (required && !field.configured && !hasValue(fieldValue(field))) {
        currentSection.value = section.id;
        error.value = `“${field.label}” is required before continuing.`;
        return;
      }
    }
  }

  saving.value = true;
  try {
    const submission = {
      sections: selectedSections.value,
      configuration: payloadValues(),
    };

    if (configuration.value && !(await fetchSetupStatus()).setup_required) {
      await saveSetupConfiguration(submission);
      saved.value = true;
      configuration.value = await fetchSetupConfiguration();
      return;
    }

    const admin = sections.value.find((section) => section.id === "first_admin");
    const username = textFieldValue(
      admin?.fields.find((field) => field.name === "PRIMARY_USER_USERNAME"),
    );
    const email = textFieldValue(
      admin?.fields.find((field) => field.name === "PRIMARY_USER_EMAIL"),
    );
    const password = textFieldValue(
      admin?.fields.find((field) => field.name === "PRIMARY_USER_PASSWORD"),
    );

    await createInitialAdmin({
      ...submission,
      username,
      email,
      password,
    });
    await checkAuth();
    await router.replace("/");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Setup failed.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <main class="setup-page">
    <section v-if="loading" class="setup-card">
      <div class="brand"><span>🎮</span><h1>Archive setup</h1></div>
      <p class="subtitle">Loading the configuration registry…</p>
    </section>

    <section v-else class="setup-shell">
      <aside class="setup-nav">
        <div class="brand"><span>🎮</span><strong>Archive setup</strong></div>
        <button
          class="nav-item"
          :class="{ active: currentSection === 'welcome' }"
          @click="currentSection = 'welcome'"
        >
          Welcome
        </button>
        <button
          v-for="section in selected"
          :key="section.id"
          class="nav-item"
          :class="{ active: currentSection === section.id }"
          @click="currentSection = section.id"
        >
          <span>{{ section.title }}</span>
          <small>{{ statusLabel(section) }}</small>
        </button>
      </aside>

      <section class="setup-card content">
        <div v-if="currentSection === 'welcome'">
          <div class="brand"><span>👋</span><h1>Welcome to setup</h1></div>
          <p class="subtitle">
            This page is generated from the backend configuration registry.
            Required sections are kept automatically; optional sections can be
            added or removed without changing this Vue component.
          </p>

          <div class="section-list">
            <article v-for="section in requiredSections" :key="section.id" class="section-choice required">
              <div>
                <strong>{{ section.title }}</strong>
                <p>{{ section.description }}</p>
              </div>
              <span class="badge">{{ statusLabel(section) }}</span>
            </article>

            <article
              v-for="section in optionalSections"
              :key="section.id"
              class="section-choice"
              :class="{ selected: selectedSections.includes(section.id) }"
            >
              <div>
                <strong>{{ section.title }}</strong>
                <p>{{ section.description }}</p>
              </div>
              <button
                type="button"
                class="secondary small"
                :disabled="section.status === 'completed_by_env'"
                @click="toggleOptional(section)"
              >
{{ optionalSectionAction(section) }}
              </button>
            </article>
          </div>

          <div v-for="section in requiredSections.filter((item) => item.blocked)" :key="section.id" class="error env-blocker">
            <strong>{{ section.title }} cannot be configured here.</strong>
            <span>{{ section.blocked_message }}. These deployment-only flags must be changed in .env.</span>
          </div>
          <div v-if="error" class="error">{{ error }}</div>
          <button class="primary" :disabled="welcomeBlocked" @click="nextSection">
            Continue
          </button>
        </div>

        <div v-else-if="current" class="section-editor">
          <header>
            <div>
              <h1>{{ current.title }}</h1>
              <p class="subtitle">{{ current.description }}</p>
            </div>
            <span class="badge">{{ statusLabel(current) }}</span>
          </header>

          <div class="field-groups">
            <section
              v-for="group in fieldGroups(current)"
              :key="group.heading ?? '__unheaded'"
              class="field-group"
            >
              <h3 v-if="group.heading">{{ group.heading }}</h3>
              <div class="fields">
                <label v-for="field in group.fields" :key="field.name">
                  <span>
                    {{ field.label }}
                    <b v-if="fieldRequired(field)" class="required-mark">*</b>
                    <em v-if="field.locked && !field.generated">Managed by .env</em>
                    <em v-if="field.generated">Generated automatically</em>
                  </span>

                  <select
                    v-if="field.type === 'choice'"
                    :value="fieldValue(field) as string"
                    :disabled="field.locked"
                    @change="setField(field, ($event.target as HTMLSelectElement).value)"
                  >
                    <option
                      v-for="choice in field.choices"
                      :key="choice.value"
                      :value="choice.value"
                    >
                      {{ choice.label }}
                    </option>
                  </select>

                  <input
                    v-else-if="field.type === 'boolean'"
                    :checked="Boolean(fieldValue(field))"
                    type="checkbox"
                    :disabled="field.locked"
                    @change="setField(field, ($event.target as HTMLInputElement).checked)"
                  />

                  <input
                    v-else
                    :value="inputValue(field)"
                    :type="inputType(field)"
                    :placeholder="fieldPlaceholder(field)"
                    :required="fieldRequired(field) && !field.configured"
                    :disabled="field.locked || (field.generated && field.configured)"
                    @input="setField(field, ($event.target as HTMLInputElement).value)"
                  />

                  <small v-if="field.description">{{ field.description }}</small>
                  <small v-if="field.hint">{{ field.hint }}</small>
                  <small v-if="field.env_only && !field.configured" class="env-help">
                    This flag must be changed in .env. It is deployment-only.
                  </small>
                  <small v-else-if="field.generated" class="env-help">
                    This value is generated from the address currently used to access the application.
                  </small>
                  <small v-else-if="field.locked" class="env-help">
                    This value comes from the deployment environment and cannot be changed here.
                  </small>
                </label>
              </div>
            </section>
          </div>

          <div v-if="error" class="error">{{ error }}</div>
          <div v-if="saved" class="success">Configuration saved.</div>

          <div class="actions">
            <button class="secondary" @click="previousSection">Back</button>
            <button class="secondary" :disabled="!canAdvance" @click="nextSection">
              Next
            </button>
            <button class="primary" :disabled="saving" @click="submit">
              {{ actionLabel }}
            </button>
          </div>
        </div>
      </section>
    </section>
  </main>
</template>

<style scoped>
.setup-page{min-height:100vh;background:#121212;color:#ccc;font-family:system-ui,sans-serif;padding:24px 16px;display:flex;justify-content:center;align-items:center}
.setup-shell{width:min(1120px,100%);display:grid;grid-template-columns:260px minmax(0,1fr);gap:16px;align-items:start}
.setup-card,.setup-nav{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:14px}
.setup-card{padding:32px}.setup-card.content{min-height:650px}
.setup-nav{padding:18px;display:flex;flex-direction:column;gap:8px;position:sticky;top:16px}
.brand{display:flex;align-items:center;gap:10px;justify-content:center;color:#fff;margin-bottom:12px}.brand h1{font-size:1.4rem;margin:0}.brand strong{font-size:1rem}
.subtitle{color:#999;font-size:13px;line-height:1.5}
.nav-item{border:1px solid transparent;background:transparent;color:#aaa;text-align:left;padding:10px;border-radius:8px;cursor:pointer;display:flex;justify-content:space-between;gap:8px}.nav-item.active{background:#252525;border-color:#3a3a3a;color:#fff}.nav-item small{color:#777;font-size:10px;text-align:right}
.section-list{display:flex;flex-direction:column;gap:10px;margin:24px 0}
.section-choice{border:1px solid #333;border-radius:10px;padding:14px;display:flex;align-items:center;justify-content:space-between;gap:16px;background:#151515}.section-choice.selected{border-color:#57411f}.section-choice p{margin:5px 0 0;color:#888;font-size:12px;line-height:1.4}.section-choice.required{background:#181818}
.badge{white-space:nowrap;border:1px solid #3a3a3a;border-radius:999px;padding:4px 8px;color:#aaa;font-size:11px}.small{padding:7px 10px!important;font-size:12px}
.section-editor header{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.section-editor h1{margin:0;color:#fff;font-size:1.35rem}
.field-groups{display:flex;flex-direction:column;gap:24px;margin:24px 0}.field-group h3{margin:0 0 12px;color:#fff;font-size:1rem}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.fields label{display:flex;flex-direction:column;gap:6px;color:#ccc;font-size:13px}.fields label:has(input[type=checkbox]){flex-direction:row;align-items:center}.fields label>span{display:flex;gap:5px;align-items:center}.fields em{font-style:normal;color:#d8c39a;font-size:10px;margin-left:auto}.fields input,.fields select{background:#111;border:1px solid #3a3a3a;border-radius:8px;color:#fff;padding:10px;font:inherit}.fields input[type=checkbox]{width:18px;height:18px;accent-color:#d68a34}.fields input:focus,.fields select:focus{outline:none;border-color:#d68a34}.fields input:disabled,.fields select:disabled{opacity:.55}.fields small{color:#777;font-size:11px;line-height:1.4}.env-help{color:#d8c39a!important}.required-mark{color:#fca5a5}
.actions{display:flex;gap:10px;margin-top:20px}.actions button{flex:1}
button.primary,.setup-card button.primary{background:#d68a34;color:#111;border:0;border-radius:8px;padding:11px 14px;font-weight:700;cursor:pointer}.secondary{background:#252525!important;color:#ddd!important;border:1px solid #3a3a3a!important;border-radius:8px;padding:11px 14px;cursor:pointer}.setup-card button:disabled{opacity:.6;cursor:not-allowed}
.env-blocker{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}.error{color:#fca5a5;background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.3);border-radius:8px;padding:9px;font-size:13px}.success{color:#86efac;background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.2);border-radius:8px;padding:9px;font-size:13px}
@media(max-width:800px){.setup-page{align-items:flex-start}.setup-shell{grid-template-columns:1fr}.setup-nav{position:static}.fields{grid-template-columns:1fr}.section-choice{align-items:flex-start;flex-direction:column}}
</style>
