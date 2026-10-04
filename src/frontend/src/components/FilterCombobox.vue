<script setup lang="ts">
import { ref, computed, watch } from "vue";

const props = defineProps<{
  modelValue: string;
  options: string[];
  placeholder: string;
  allLabel?: string;
  // A second, larger pool only searched once the user starts typing, keeps
  // the default dropdown short while still making everything findable.
  extraOptions?: string[];
  extraLabel?: string;
}>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const query = ref("");
const open = ref(false);
const inputRef = ref<HTMLInputElement | null>(null);

const displayLabel = computed(() =>
  props.modelValue === "all" ? (props.allLabel ?? "All") : props.modelValue,
);

watch(
  () => props.modelValue,
  () => {
    query.value = "";
  },
);

const filteredOptions = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return props.options;
  return props.options.filter((o) => o.toLowerCase().includes(q));
});

const filteredExtraOptions = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q || !props.extraOptions) return [];
  return props.extraOptions.filter((o) => o.toLowerCase().includes(q));
});

function select(value: string) {
  emit("update:modelValue", value);
  query.value = "";
  open.value = false;
  inputRef.value?.blur();
}

function onFocus() {
  open.value = true;
  query.value = "";
}

function onBlur() {
  setTimeout(() => {
    open.value = false;
    query.value = "";
  }, 150);
}
</script>

<template>
  <div class="combobox">
    <input
      ref="inputRef"
      type="text"
      class="combobox-input"
      :placeholder="placeholder"
      :aria-label="placeholder"
      :value="open ? query : displayLabel"
      @input="query = ($event.target as HTMLInputElement).value"
      @focus="onFocus"
      @blur="onBlur"
    />
    <div v-if="open" class="combobox-menu">
      <button
        type="button"
        class="combobox-option"
        @mousedown.prevent="select('all')"
      >
        {{ allLabel ?? "All" }}
      </button>
      <button
        v-for="opt in filteredOptions"
        :key="opt"
        type="button"
        class="combobox-option"
        :class="{ active: opt === modelValue }"
        @mousedown.prevent="select(opt)"
      >
        {{ opt }}
      </button>
      <div v-if="filteredExtraOptions.length" class="combobox-group-label">
        {{ extraLabel ?? "More" }}
      </div>
      <button
        v-for="opt in filteredExtraOptions"
        :key="opt"
        type="button"
        class="combobox-option"
        :class="{ active: opt === modelValue }"
        @mousedown.prevent="select(opt)"
      >
        {{ opt }}
      </button>
      <div
        v-if="!filteredOptions.length && !filteredExtraOptions.length"
        class="combobox-empty"
      >
        No matches
      </div>
    </div>
  </div>
</template>

<style scoped>
.combobox {
  position: relative;
}
.combobox-input {
  height: 40px;
  box-sizing: border-box;
  width: 160px;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 0 14px;
  font: inherit;
  font-size: 13px;
}
.combobox-input::placeholder {
  color: #777;
}
.combobox-input:focus {
  outline: none;
  border-color: #d68a34;
}
.combobox-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  width: 200px;
  max-height: 240px;
  overflow-y: auto;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 8px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
  z-index: 50;
  display: flex;
  flex-direction: column;
  padding: 4px;
}
.combobox-option {
  background: none;
  border: none;
  color: #ccc;
  text-align: left;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  text-transform: capitalize;
}
.combobox-option:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.combobox-option.active {
  background: rgba(214, 138, 52, 0.18);
  color: #d68a34;
}
.combobox-empty {
  color: #666;
  font-size: 12px;
  padding: 8px 10px;
}
.combobox-group-label {
  color: #666;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
  padding: 8px 10px 4px;
}
</style>
