<script setup lang="ts">
import { SHORTCUT_GROUPS } from "../../utils/shortcuts";
</script>

<template>
  <section class="settings-section">
    <h2>Keyboard Shortcuts</h2>
    <p class="hint">
      Press <kbd>?</kbd> anywhere in the app to open this list as an overlay.
      Every shortcut below only works on the page it's grouped under.
    </p>
    <div v-for="group in SHORTCUT_GROUPS" :key="group.title" class="group">
      <h3>{{ group.title }}</h3>
      <div v-for="s in group.shortcuts" :key="s.label" class="shortcut">
        <span class="label">{{ s.label }}</span>
        <kbd>{{ s.keys }}</kbd>
      </div>
    </div>
  </section>
</template>

<style scoped>
.settings-section {
  max-width: 560px;
}
.settings-section h2 {
  margin: 0 0 8px;
  padding-left: 12px;
  border-left: 3px solid #d68a34;
  font-size: 1rem;
  color: #fff;
}
.hint {
  color: #888;
  font-size: 0.85rem;
  line-height: 1.5;
  margin: 0 0 12px;
}
.group {
  margin-top: 22px;
}
.group:first-of-type {
  margin-top: 18px;
}
h3 {
  margin: 0 0 4px;
  font-size: 0.8rem;
  font-weight: 700;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.shortcut {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 9px 4px;
  border-bottom: 1px solid #212121;
}
.label {
  color: #ddd;
  font-size: 0.88rem;
  line-height: 1.4;
}
.shortcut kbd {
  flex-shrink: 0;
  max-width: 220px;
  text-align: right;
  white-space: normal;
}
kbd {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid #3a3a3a;
  border-bottom-width: 2px;
  background: #111;
  color: #eee;
  font: inherit;
  font-family: ui-monospace, "SF Mono", monospace;
  font-size: 0.76rem;
  font-weight: 600;
  line-height: 1.5;
}
</style>
