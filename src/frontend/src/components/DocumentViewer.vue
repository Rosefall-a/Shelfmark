<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import {
  DocumentViewError,
  fetchDocumentView,
} from "../services/documentViewer";

const props = defineProps<{
  gameId: string;
  filename: string;
  open: boolean;
}>();

const emit = defineEmits<{ (e: "close"): void }>();

const loading = ref(false);
const error = ref<DocumentViewError | null>(null);
const result = ref<Awaited<ReturnType<typeof fetchDocumentView>> | null>(null);

function cleanup() {
  if (result.value?.type === "pdf" && result.value.url)
    URL.revokeObjectURL(result.value.url);
  result.value = null;
}

async function load() {
  cleanup();
  error.value = null;
  if (!props.open) return;
  loading.value = true;
  try {
    result.value = await fetchDocumentView(props.gameId, props.filename);
  } catch (err) {
    error.value =
      err instanceof DocumentViewError
        ? err
        : new DocumentViewError("network", "Could not load this document.");
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.open, props.gameId, props.filename],
  () => void load(),
  { immediate: true },
);

onBeforeUnmount(cleanup);
</script>

<template>
  <div v-if="open" class="document-viewer-overlay" @click.self="emit('close')">
    <section
      class="document-viewer"
      role="dialog"
      aria-modal="true"
      :aria-label="filename"
    >
      <header class="document-viewer-header">
        <h2>{{ filename }}</h2>
        <button type="button" title="Close" @click="emit('close')">×</button>
      </header>

      <div v-if="loading" class="document-viewer-state">Loading document…</div>
      <div v-else-if="error" class="document-viewer-state error">
        <strong>{{
          error.kind === "missing"
            ? "Document not found"
            : error.kind === "forbidden"
              ? "Access denied"
              : error.kind === "unsupported"
                ? "Unsupported document"
                : error.kind === "server"
                  ? "Server error"
                  : "Unable to load document"
        }}</strong>
        <span>{{ error.message }}</span>
      </div>

      <iframe
        v-else-if="result?.type === 'pdf'"
        class="document-pdf"
        :src="result.url"
        :title="filename"
      ></iframe>

      <pre v-else-if="result?.type === 'text'" class="document-text">
        {{ result.content }}
      </pre>

      <div v-else class="document-viewer-state">
        This document cannot be displayed.
      </div>
    </section>
  </div>
</template>

<style scoped>
.document-viewer-overlay {
  position: fixed;
  inset: 0;
  z-index: 400;
  padding: 24px;
  background: rgba(0, 0, 0, 0.78);
  display: flex;
  align-items: center;
  justify-content: center;
}
.document-viewer {
  width: min(1100px, 100%);
  height: min(900px, 100%);
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #171717;
  border: 1px solid #2b2b2b;
  border-radius: 12px;
  overflow: hidden;
}
.document-viewer-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid #2b2b2b;
}
.document-viewer-header h2 {
  flex: 1;
  min-width: 0;
  margin: 0;
  font-size: 0.9rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.document-viewer-header button {
  background: none;
  border: 0;
  color: #aaa;
  font-size: 1.4rem;
  cursor: pointer;
}
.document-viewer-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  color: #aaa;
  padding: 24px;
  text-align: center;
}
.document-viewer-state.error {
  color: #fca5a5;
}
.document-pdf {
  flex: 1;
  width: 100%;
  border: 0;
  background: #fff;
}
.document-text {
  flex: 1;
  margin: 0;
  padding: 18px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: 0.82rem/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #ddd;
}
</style>
