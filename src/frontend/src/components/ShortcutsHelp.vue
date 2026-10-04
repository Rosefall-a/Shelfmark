<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { SHORTCUT_GROUPS } from "../utils/shortcuts";

const open = ref(false);

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) {
    open.value = false;
    return;
  }
  if (isTypingTarget(e.target)) return;
  if (e.key === "?") {
    e.preventDefault();
    open.value = !open.value;
  }
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));

const GROUPS = SHORTCUT_GROUPS;
</script>

<template>
  <div v-if="open" class="shortcuts-backdrop" @click.self="open = false">
    <div class="shortcuts-dialog">
      <div class="shortcuts-header">
        <h2>Keyboard shortcuts</h2>
        <button type="button" class="close-button" @click="open = false">
          ✕
        </button>
      </div>
      <div v-for="group in GROUPS" :key="group.title" class="shortcuts-group">
        <h3>{{ group.title }}</h3>
        <div v-for="s in group.shortcuts" :key="s.label" class="shortcut-row">
          <span>{{ s.label }}</span>
          <kbd>{{ s.keys }}</kbd>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shortcuts-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}
.shortcuts-dialog {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 22px 24px;
  width: 440px;
  max-width: calc(100vw - 40px);
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
  box-sizing: border-box;
}
.shortcuts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.shortcuts-header h2 {
  margin: 0;
  font-size: 16px;
  color: #fff;
}
.close-button {
  background: none;
  border: none;
  color: #999;
  font-size: 14px;
  cursor: pointer;
  padding: 4px;
}
.close-button:hover {
  color: #fff;
}
.shortcuts-group {
  margin-bottom: 16px;
}
.shortcuts-group:last-child {
  margin-bottom: 0;
}
.shortcuts-group h3 {
  margin: 0 0 8px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #777;
}
.shortcut-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 14px;
  padding: 7px 0;
  font-size: 13px;
  color: #ccc;
}
.shortcut-row kbd {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  padding: 3px 8px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: #d68a34;
  white-space: normal;
  flex-shrink: 0;
  max-width: 200px;
  text-align: right;
  box-sizing: border-box;
}
</style>
