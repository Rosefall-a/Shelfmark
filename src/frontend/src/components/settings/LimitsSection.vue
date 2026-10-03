<script setup lang="ts">
import { ref, onMounted } from "vue";
import { fetchUploadLimits, updateUploadLimit } from "../../services/settings";

const loading = ref(true);
const loadError = ref<string | null>(null);
const effectiveMb = ref<number | null>(null);
// what the admin's typing — separate from effectiveMb so a bad value being
// edited doesn't flash the wrong number elsewhere while it's mid-edit
const draftMb = ref("");

const saving = ref(false);
const saveError = ref<string | null>(null);
const saveSuccess = ref(false);

async function load() {
  loading.value = true;
  loadError.value = null;
  try {
    const r = await fetchUploadLimits();
    effectiveMb.value = r.max_upload_size_mb;
    draftMb.value = String(r.max_upload_size_mb);
  } catch (e) {
    loadError.value =
      e instanceof Error ? e.message : "Failed to load the current limit.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function save() {
  const n = Number(draftMb.value);
  saveError.value = null;
  saveSuccess.value = false;
  if (!Number.isFinite(n) || n < 1) {
    saveError.value = "Enter a whole number of at least 1 MB.";
    return;
  }
  saving.value = true;
  try {
    const r = await updateUploadLimit(Math.round(n));
    effectiveMb.value = r.max_upload_size_mb;
    saveSuccess.value = true;
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : "Failed to save.";
  } finally {
    saving.value = false;
  }
}

async function resetToDefault() {
  saving.value = true;
  saveError.value = null;
  saveSuccess.value = false;
  try {
    const r = await updateUploadLimit(null);
    effectiveMb.value = r.max_upload_size_mb;
    draftMb.value = String(r.max_upload_size_mb);
    saveSuccess.value = true;
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : "Failed to reset.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="settings-section">
    <h2>Limits</h2>
    <p class="hint">
      Server-wide caps, admin-only. Currently just the image/media upload size —
      video clips and world saves keep their own larger caps and aren't editable
      here yet.
    </p>

    <p v-if="loading" class="hint">Loading…</p>
    <template v-else>
      <p v-if="loadError" class="form-error">{{ loadError }}</p>
      <template v-else>
        <label class="field">
          <span>Max upload size (MB)</span>
          <div class="row">
            <input
              v-model="draftMb"
              type="number"
              min="1"
              step="1"
              inputmode="numeric"
            />
            <button
              type="button"
              class="primary-button"
              :disabled="saving"
              @click="save"
            >
              {{ saving ? "Saving…" : "Save" }}
            </button>
          </div>
          <span class="field-hint">
            Applies to cover art, banners, and general file uploads —
            screenshots, docs, that sort of thing.
          </span>
        </label>

        <button
          type="button"
          class="text-button"
          :disabled="saving"
          @click="resetToDefault"
        >
          Reset to the server's .env default
        </button>

        <div v-if="saveError" class="form-error">{{ saveError }}</div>
        <div v-if="saveSuccess" class="form-success">
          Saved. New uploads use this limit right away — nothing to restart.
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.settings-section {
  max-width: 480px;
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
  margin: 0 0 18px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.85rem;
  color: #ccc;
  margin-bottom: 12px;
}
.row {
  display: flex;
  gap: 10px;
}
.field input {
  flex: 1;
  min-width: 0;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 10px 12px;
  font: inherit;
}
.field input:focus {
  outline: none;
  border-color: #d68a34;
}
.field-hint {
  color: #777;
  font-size: 0.78rem;
}
.primary-button {
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 8px;
  padding: 0 18px;
  font-weight: 600;
  cursor: pointer;
}
.primary-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.text-button {
  background: none;
  border: none;
  padding: 0;
  color: #d68a34;
  font-size: 0.82rem;
  cursor: pointer;
}
.text-button:hover {
  text-decoration: underline;
}
.text-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  text-decoration: none;
}
.form-error {
  margin-top: 12px;
  color: #fca5a5;
  font-size: 13px;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
}
.form-success {
  margin-top: 12px;
  color: #86efac;
  font-size: 13px;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
}
</style>
