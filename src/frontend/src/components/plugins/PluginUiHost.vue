<script setup lang="ts">
import { computed, ref } from "vue";
import {
  buildInitialValues,
  validateField,
  type PluginUiDocument,
  type UiAction,
  type UiField,
  type UiValues,
} from "../../services/pluginUi";

const props = defineProps<{ document: PluginUiDocument }>();
const emit = defineEmits<{
  action: [action: UiAction, values: UiValues];
  save: [values: UiValues];
}>();

const activePage = ref(props.document.pages[0]?.id ?? "");
const values = ref<UiValues>(buildInitialValues(props.document));
const submitted = ref(false);

const pages = computed(() => props.document.pages);
const page = computed(() => pages.value.find((item) => item.id === activePage.value) ?? pages.value[0]);
const settings = computed(() => props.document.settings.filter((item) => page.value?.settings.includes(item.id)));
const actions = computed(() => props.document.actions.filter((item) => page.value?.actions.includes(item.id)));
const errors = computed(() => {
  if (!submitted.value) return [];
  return settings.value.flatMap((section) =>
    section.fields.map((field) => ({ field: field.id, message: validateField(field, values.value[field.id]) }))
      .filter((item): item is { field: string; message: string } => item.message !== null),
  );
});

function errorFor(field: UiField): string | undefined {
  return errors.value.find((item) => item.field === field.id)?.message;
}
function submit() {
  submitted.value = true;
  if (errors.value.length) return;
  emit("save", values.value);
}
function runAction(action: UiAction) {
  if (action.confirmation && !window.confirm(action.confirmation)) return;
  emit("action", action, values.value);
}
</script>

<template>
  <section class="plugin-ui-host" :aria-label="document.title">
    <header>
      <h2>{{ document.title }}</h2>
      <nav v-if="pages.length > 1" aria-label="Plugin pages">
        <button v-for="item in pages" :key="item.id" type="button" :class="{ active: item.id === page?.id }" @click="activePage = item.id">
          {{ item.title }}
        </button>
      </nav>
      <p v-if="page?.description" class="muted">{{ page.description }}</p>
    </header>

    <p v-if="!page" class="empty">This plugin has no native pages.</p>

    <form v-else @submit.prevent="submit">
      <fieldset v-for="section in settings" :key="section.id">
        <legend>{{ section.title }}</legend>
        <p v-if="section.description" class="muted">{{ section.description }}</p>
        <label v-for="field in section.fields" :key="field.id">
          <span>{{ field.label }}<b v-if="field.required"> *</b></span>
          <small v-if="field.description">{{ field.description }}</small>
          <select v-if="field.type === 'select'" v-model="values[field.id]">
            <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <select v-else-if="field.type === 'multiselect'" v-model="values[field.id]" multiple>
            <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <textarea v-else-if="field.type === 'textarea'" v-model="values[field.id] as string" />
          <input v-else-if="field.type === 'boolean'" v-model="values[field.id]" type="checkbox" />
          <input v-else v-model="values[field.id]" :type="field.type === 'password' ? 'password' : field.type" :autocomplete="field.secret ? 'new-password' : 'off'" />
          <em v-if="errorFor(field)" class="error">{{ errorFor(field) }}</em>
        </label>
      </fieldset>

      <div class="actions">
        <button type="submit">Save</button>
        <button v-for="action in actions" :key="action.id" type="button" @click="runAction(action)">{{ action.label }}</button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.plugin-ui-host { display:grid; gap:24px; } header { display:grid; gap:8px; }
nav,.actions { display:flex; flex-wrap:wrap; gap:8px; } button { cursor:pointer; } nav button.active { font-weight:700; }
fieldset { display:grid; gap:16px; border:1px solid #2a2a2a; border-radius:10px; padding:16px; }
legend { padding:0 6px; font-weight:700; } label { display:grid; gap:5px; } label > span { font-weight:600; }
small,.muted { color:#999; } .error { color:#e66; font-style:normal; } .empty { color:#999; }
</style>
