<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  createTestNotification,
  regenerateNotifications,
} from "../../services/notifications";
import { refreshMediaNotifications } from "../../state/notifications";
import type { MediaNotificationKind } from "../../services/notifications";
import { fetchSystemInfo } from "../../services/settings";
import type { SystemInfo } from "../../services/settings";

const kindOptions: { value: MediaNotificationKind; label: string }[] = [
  { value: "episode_aired", label: "Episode aired" },
  { value: "season_started", label: "Season started" },
  { value: "sequel_announced", label: "Sequel announced" },
  { value: "movie_released", label: "Movie released" },
];
const mediaTypeOptions: { value: "movie" | "tv" | "anime"; label: string }[] = [
  { value: "movie", label: "Movie" },
  { value: "tv", label: "TV" },
  { value: "anime", label: "Anime" },
];

const kind = ref<MediaNotificationKind>("episode_aired");
const mediaType = ref<"movie" | "tv" | "anime">("tv");
const title = ref("Test notification");
const body = ref("Sent from Settings > Administration > Dev Tools.");

const sending = ref(false);
const sendError = ref<string | null>(null);
const sendSuccess = ref(false);

async function send() {
  sendError.value = null;
  sendSuccess.value = false;
  if (!title.value.trim()) {
    sendError.value = "Enter a title.";
    return;
  }
  sending.value = true;
  try {
    await createTestNotification({
      kind: kind.value,
      mediaType: mediaType.value,
      title: title.value.trim(),
      body: body.value.trim(),
    });
    sendSuccess.value = true;
    await refreshMediaNotifications();
  } catch (e) {
    sendError.value = e instanceof Error ? e.message : "Failed to send.";
  } finally {
    sending.value = false;
  }
}

// Regenerate notifications now, instead of waiting on the bell's next poll
const regenerating = ref(false);
const regenerateError = ref<string | null>(null);
const regenerateResult = ref<number | null>(null);

async function regenerate() {
  regenerateError.value = null;
  regenerateResult.value = null;
  regenerating.value = true;
  try {
    const r = await regenerateNotifications();
    regenerateResult.value = r.created;
    await refreshMediaNotifications();
  } catch (e) {
    regenerateError.value = e instanceof Error ? e.message : "Failed to run.";
  } finally {
    regenerating.value = false;
  }
}

// System info
const info = ref<SystemInfo | null>(null);
const infoLoading = ref(true);
const infoError = ref<string | null>(null);

async function loadInfo() {
  infoLoading.value = true;
  infoError.value = null;
  try {
    info.value = await fetchSystemInfo();
  } catch (e) {
    infoError.value = e instanceof Error ? e.message : "Failed to load.";
  } finally {
    infoLoading.value = false;
  }
}
onMounted(loadInfo);

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(" ");
}

// Raw API request tester
const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
type Method = (typeof METHODS)[number];
const method = ref<Method>("GET");
const path = ref("/api/auth/me");
const reqBody = ref("");
const hasBody = computed(
  () => method.value !== "GET" && method.value !== "DELETE",
);

const sendingReq = ref(false);
const reqStatus = ref<number | null>(null);
const reqOk = ref(true);
const reqResponse = ref("");
const reqError = ref<string | null>(null);

async function sendRequest() {
  reqError.value = null;
  reqResponse.value = "";
  reqStatus.value = null;
  if (!path.value.startsWith("/api/")) {
    reqError.value =
      "Path must start with /api/ — this only talks to this server's own API.";
    return;
  }
  let parsedBody: string | undefined;
  if (hasBody.value && reqBody.value.trim()) {
    try {
      JSON.parse(reqBody.value);
      parsedBody = reqBody.value;
    } catch {
      reqError.value = "Body isn't valid JSON.";
      return;
    }
  }
  sendingReq.value = true;
  try {
    const response = await fetch(path.value, {
      method: method.value,
      credentials: "include",
      headers: parsedBody ? { "Content-Type": "application/json" } : undefined,
      body: parsedBody,
    });
    reqStatus.value = response.status;
    reqOk.value = response.ok;
    const text = await response.text();
    try {
      reqResponse.value = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      reqResponse.value = text;
    }
  } catch (e) {
    reqError.value = e instanceof Error ? e.message : "Request failed.";
  } finally {
    sendingReq.value = false;
  }
}
</script>

<template>
  <div class="dev-tools">
    <section class="settings-section">
      <h2>Test notification</h2>
      <p class="hint">
        Fires a real notification for your own account, for testing the bell,
        the list, and the notifications API without waiting on a real episode or
        release. Its media id is a random placeholder, so it won't link
        anywhere.
      </p>

      <label class="field">
        <span>Kind</span>
        <select v-model="kind">
          <option v-for="o in kindOptions" :key="o.value" :value="o.value">
            {{ o.label }}
          </option>
        </select>
      </label>

      <label class="field">
        <span>Media type</span>
        <select v-model="mediaType">
          <option v-for="o in mediaTypeOptions" :key="o.value" :value="o.value">
            {{ o.label }}
          </option>
        </select>
      </label>

      <label class="field">
        <span>Title</span>
        <input v-model="title" type="text" maxlength="500" />
      </label>

      <label class="field">
        <span>Body</span>
        <textarea v-model="body" rows="2"></textarea>
      </label>

      <button
        type="button"
        class="primary-button"
        :disabled="sending"
        @click="send"
      >
        {{ sending ? "Sending…" : "Send test notification" }}
      </button>

      <div v-if="sendError" class="form-error">{{ sendError }}</div>
      <div v-if="sendSuccess" class="form-success">
        Sent. Check the bell in the top corner.
      </div>
    </section>

    <section class="settings-section">
      <h2>Regenerate notifications</h2>
      <p class="hint">
        Runs the same real-data check the bell's poll triggers, right now —
        useful right after editing an air date or release date instead of
        waiting for the next poll.
      </p>

      <button
        type="button"
        class="primary-button"
        :disabled="regenerating"
        @click="regenerate"
      >
        {{ regenerating ? "Running…" : "Run now" }}
      </button>

      <div v-if="regenerateError" class="form-error">{{ regenerateError }}</div>
      <div v-if="regenerateResult !== null" class="form-success">
        {{ regenerateResult }}
        new notification{{ regenerateResult === 1 ? "" : "s" }} created.
      </div>
    </section>

    <section class="settings-section">
      <h2>System info</h2>
      <p class="hint">
        No secrets or connection strings, just enough to sanity-check which
        server you're talking to.
      </p>

      <p v-if="infoLoading" class="hint">Loading…</p>
      <p v-else-if="infoError" class="form-error">{{ infoError }}</p>
      <dl v-else-if="info" class="info-list">
        <div class="info-row">
          <dt>Server time</dt>
          <dd>{{ new Date(info.server_time * 1000).toLocaleString() }}</dd>
        </div>
        <div class="info-row">
          <dt>Uptime</dt>
          <dd>{{ formatUptime(info.uptime_seconds) }}</dd>
        </div>
        <div class="info-row">
          <dt>Debug mode</dt>
          <dd>{{ info.debug ? "On" : "Off" }}</dd>
        </div>
        <div class="info-row">
          <dt>Python</dt>
          <dd>{{ info.python_version }}</dd>
        </div>
        <div class="info-row">
          <dt>Platform</dt>
          <dd>{{ info.platform }}</dd>
        </div>
      </dl>
      <button type="button" class="text-button" @click="loadInfo">
        Refresh
      </button>
    </section>

    <section class="settings-section wide">
      <h2>API request</h2>
      <p class="hint">
        Sends a request to this server's own API, using your current login — for
        poking at an endpoint without opening the browser's dev tools. Only
        paths starting with /api/ are allowed.
      </p>

      <div class="req-row">
        <select v-model="method" class="method-select">
          <option v-for="m in METHODS" :key="m" :value="m">{{ m }}</option>
        </select>
        <input
          v-model="path"
          type="text"
          class="path-input"
          placeholder="/api/auth/me"
        />
        <button
          type="button"
          class="primary-button"
          :disabled="sendingReq"
          @click="sendRequest"
        >
          {{ sendingReq ? "Sending…" : "Send" }}
        </button>
      </div>

      <label v-if="hasBody" class="field">
        <span>Body (JSON, optional)</span>
        <textarea
          v-model="reqBody"
          rows="4"
          placeholder='{"key": "value"}'
        ></textarea>
      </label>

      <div v-if="reqError" class="form-error">{{ reqError }}</div>
      <div v-if="reqStatus !== null" class="response">
        <div class="response-status" :class="{ ok: reqOk, err: !reqOk }">
          {{ reqStatus }}
        </div>
        <pre class="response-body">{{ reqResponse }}</pre>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dev-tools {
  display: flex;
  flex-direction: column;
  gap: 28px;
}
.settings-section {
  max-width: 480px;
}
.settings-section.wide {
  max-width: 680px;
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
.field select,
.field input,
.field textarea {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 10px 12px;
  font: inherit;
  resize: vertical;
}
.field select:focus,
.field input:focus,
.field textarea:focus {
  outline: none;
  border-color: #d68a34;
}
.primary-button {
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.primary-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.text-button {
  background: none;
  border: none;
  padding: 0;
  margin-top: 12px;
  color: #d68a34;
  font-size: 0.82rem;
  cursor: pointer;
}
.text-button:hover {
  text-decoration: underline;
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
.info-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 6px;
}
.info-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.85rem;
  padding: 8px 12px;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
}
.info-row dt {
  color: #888;
}
.info-row dd {
  margin: 0;
  color: #eee;
  font-weight: 600;
  text-align: right;
}
.req-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.method-select {
  flex-shrink: 0;
  width: 100px;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 10px 12px;
  font: inherit;
}
.path-input {
  flex: 1;
  min-width: 0;
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 10px 12px;
  font: inherit;
  font-family: ui-monospace, monospace;
}
.response {
  margin-top: 12px;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  overflow: hidden;
}
.response-status {
  padding: 6px 12px;
  font-size: 0.78rem;
  font-weight: 700;
  font-family: ui-monospace, monospace;
}
.response-status.ok {
  background: rgba(34, 197, 94, 0.12);
  color: #86efac;
}
.response-status.err {
  background: rgba(220, 38, 38, 0.12);
  color: #fca5a5;
}
.response-body {
  margin: 0;
  padding: 12px;
  background: #0c0c0c;
  color: #ddd;
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  line-height: 1.5;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
