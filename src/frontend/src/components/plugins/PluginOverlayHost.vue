<script setup lang="ts">
import {
  activePluginDialog,
  closePluginDialog,
  pluginOverlays,
} from "../../state/pluginExtensions";
import PluginContributionHost from "./PluginContributionHost.vue";
import {
  approvePluginAction,
  dispatchPluginAction,
} from "../../services/pluginUi";

async function runDialogAction(actionId: string) {
  const contribution = activePluginDialog.value;
  const action = contribution?.document.actions.find(
    (item) => item.id === actionId,
  );
  if (!contribution || !action) return;
  if (!approvePluginAction(action, window.confirm)) return;
  await dispatchPluginAction(contribution.pluginId, action.id);
}
</script>

<template>
  <div class="plugin-overlays" aria-live="polite">
    <PluginContributionHost
      v-for="overlay in pluginOverlays"
      :key="`${overlay.pluginId}:${overlay.contributionId}`"
      :plugin-id="overlay.pluginId"
      :document="overlay.document"
      :page-id="overlay.page.id"
      :context="{ host_page: $route.path }"
      embedded
    />
  </div>
  <div
    v-if="activePluginDialog"
    class="plugin-dialog-backdrop"
    role="presentation"
    @click.self="closePluginDialog"
  >
    <section class="plugin-dialog" role="dialog" aria-modal="true">
      <button
        type="button"
        class="plugin-dialog-close"
        aria-label="Close plugin dialog"
        @click="closePluginDialog"
      >
        ×
      </button>
      <h2>{{ activePluginDialog.dialog.title }}</h2>
      <p>{{ activePluginDialog.dialog.body }}</p>
      <div class="plugin-dialog-actions">
        <button
          v-for="actionId in activePluginDialog.dialog.actions"
          :key="actionId"
          type="button"
          @click="runDialogAction(actionId)"
        >
          {{
            activePluginDialog.document.actions.find(
              (item) => item.id === actionId,
            )?.label ?? actionId
          }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.plugin-overlays {
  position: fixed;
  inset: 0;
  z-index: 900;
  pointer-events: none;
}
.plugin-overlays :deep(*) {
  pointer-events: auto;
}
.plugin-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.7);
}
.plugin-dialog {
  position: relative;
  width: min(560px, 100%);
  padding: 24px;
  border: 1px solid #333;
  border-radius: 12px;
  background: #171717;
  color: #fff;
}
.plugin-dialog-close {
  position: absolute;
  top: 8px;
  right: 10px;
  border: 0;
  background: transparent;
  color: inherit;
  font-size: 24px;
  cursor: pointer;
}
.plugin-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
</style>
