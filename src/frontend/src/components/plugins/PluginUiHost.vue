<script setup lang="ts">
import { computed, ref } from "vue";
import { buildInitialValues, validateField, type PluginUiDocument, type UiAction, type UiField, type UiValues } from "../../services/pluginUi";

const props = defineProps<{
  document: PluginUiDocument;
  tableData?: Record<string, Record<string, string | number | boolean>[]>;
}>();
const emit = defineEmits<{
  action: [action: UiAction, values: UiValues];
  save: [values: UiValues];
  navigate: [pageId: string];
}>();
const activePage = ref(props.document.pages[0]?.id ?? "");
const values = ref<UiValues>(buildInitialValues(props.document));
const submitted = ref(false);
const pages = computed(() => props.document.pages);
const page = computed(() => pages.value.find((item) => item.id === activePage.value) ?? pages.value[0]);
const settings = computed(() => props.document.settings.filter((item) => page.value?.settings.includes(item.id)));
const actions = computed(() => props.document.actions.filter((item) => page.value?.actions.includes(item.id)));
const tables = computed(() => props.document.tables.filter((item) => page.value?.tables.includes(item.id)));
const dialogs = computed(() => props.document.dialogs.filter((item) => page.value?.dialogs.includes(item.id)));
const errors = computed(() => {
  if (!submitted.value) return [];
  return settings.value.flatMap((section) => section.fields.map((field) => ({field: field.id, message: validateField(field, values.value[field.id])})).filter((item): item is {field:string;message:string} => item.message !== null));
});
function errorFor(field: UiField): string | undefined { return errors.value.find((item) => item.field === field.id)?.message; }
function submit() { submitted.value = true; if (!errors.value.length) { const saved = Object.fromEntries(settings.value.flatMap((section) => section.fields.filter((field) => !field.secret).map((field) => [field.id, values.value[field.id]]))); emit("save", saved); } }
function runAction(action: UiAction) { if (action.confirmation && !window.confirm(action.confirmation)) return; emit("action", action, { ...values.value, _plugin_context: { page_id: page.value?.id ?? "", page_title: page.value?.title ?? "", path: window.location.pathname } }); }
function goTo(pageId: string) { activePage.value = pageId; emit("navigate", pageId); }
</script>

<template>
<section class="plugin-ui-host" :aria-label="document.title">
<header>
<h2>{{ document.title }}</h2>
<nav v-if="document.menus.length || pages.length > 1" aria-label="Plugin navigation">
<button v-for="menu in document.menus" :key="menu.id" type="button" @click="menu.page_id ? goTo(menu.page_id) : menu.action_id && runAction(document.actions.find((item) => item.id === menu.action_id)!)">{{ menu.label }}</button>
<button v-for="item in pages" :key="'page-' + item.id" type="button" :class="{active:item.id===page?.id}" @click="goTo(item.id)">{{ item.title }}</button>
</nav>
<p v-if="page?.description" class="muted">{{ page.description }}</p>
</header>
<p v-if="!page" class="empty">This plugin has no native pages.</p>
<template v-else>
<form @submit.prevent="submit">
<fieldset v-for="section in settings" :key="section.id">
<legend>{{ section.title }}</legend><p v-if="section.description" class="muted">{{ section.description }}</p>
<label v-for="field in section.fields" :key="field.id">
<span>{{ field.label }}<b v-if="field.required"> *</b></span><small v-if="field.description">{{ field.description }}</small>
<select v-if="field.type==='select'" v-model="values[field.id]"><option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option></select>
<select v-else-if="field.type==='multiselect'" v-model="values[field.id]" multiple><option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option></select>
<textarea v-else-if="field.type==='textarea'" v-model="values[field.id] as string" />
<input v-else-if="field.type==='boolean'" v-model="values[field.id]" type="checkbox" />
<input v-else-if="field.type==='number'" v-model.number="values[field.id]" type="number" :autocomplete="field.secret?'new-password':'off'" />
<input v-else v-model="values[field.id]" :type="field.type==='password'?'password':field.type" :autocomplete="field.secret?'new-password':'off'" />
<em v-if="errorFor(field)" class="error">{{ errorFor(field) }}</em>
</label>
</fieldset>
<div v-for="table in tables" :key="table.id" class="table-block"><h3>{{ table.title }}</h3><table v-if="props.tableData?.[table.id]?.length"><thead><tr><th v-for="column in table.columns" :key="column.id">{{ column.label }}</th></tr></thead><tbody><tr v-for="(row,index) in props.tableData[table.id]" :key="index"><td v-for="column in table.columns" :key="column.id">{{ row[column.id] }}</td></tr></tbody></table><p v-else class="muted">{{ table.empty_message }}</p></div>
<div v-for="dialog in dialogs" :key="dialog.id" class="dialog"><h3>{{ dialog.title }}</h3><p>{{ dialog.body }}</p><div class="actions"><button v-for="id in dialog.actions" :key="id" type="button" @click="document.actions.find((item) => item.id === id) && runAction(document.actions.find((item) => item.id === id)!)">{{ document.actions.find((item) => item.id === id)?.label || id }}</button></div></div>
<div class="actions"><button type="submit">Save</button><button v-for="action in actions" :key="action.id" type="button" @click="runAction(action)">{{ action.label }}</button></div>
</form>
</template>
</section>
</template>
<style scoped>
.plugin-ui-host{display:grid;gap:24px}header{display:grid;gap:8px}nav,.actions{display:flex;flex-wrap:wrap;gap:8px}button{cursor:pointer}nav button.active{font-weight:700}fieldset,.dialog,.table-block{display:grid;gap:12px;border:1px solid #2a2a2a;border-radius:10px;padding:16px}legend{padding:0 6px;font-weight:700}label{display:grid;gap:5px}label>span{font-weight:600}small,.muted{color:#999}.error{color:#e66;font-style:normal}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid #2a2a2a}.empty{color:#999}
</style>