<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  fetchMySessions,
  revokeAllMySessions,
  revokeMySession,
  type UserSession,
} from "../../services/sessions";
import SessionMap from "./SessionMap.vue";

const router = useRouter();
const sessions = ref<UserSession[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const busy = ref<string | null>(null);
const hasMapData = () =>
  sessions.value.some(
    (s) => s.location.latitude !== null && s.location.longitude !== null,
  );

const fmt = (v: number) => new Date(v * 1000).toLocaleString();

function locationText(session: UserSession): string {
  if (session.location.network_label) return session.location.network_label;
  return (
    [session.location.city, session.location.region, session.location.country]
      .filter(Boolean)
      .join(", ") || "Location unavailable"
  );
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    sessions.value = await fetchMySessions();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load sessions";
  } finally {
    loading.value = false;
  }
}

async function revoke(id: string) {
  busy.value = id;
  try {
    await revokeMySession(id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to revoke session";
  } finally {
    busy.value = null;
  }
}

async function revokeAll() {
  if (
    !window.confirm(
      "Revoke every browser session on this account, including this current session?",
    )
  )
    return;
  busy.value = "all";
  try {
    await revokeAllMySessions();
    await router.replace("/login");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to revoke sessions";
  } finally {
    busy.value = null;
  }
}

onMounted(load);
</script>

<template>
  <section class="settings-section">
    <header class="section-header">
      <div>
        <h2>Sessions</h2>
        <p class="section-hint">
          Manage browser sessions for this account. API keys are separate and
          are not listed here.
        </p>
      </div>
      <button class="danger" :disabled="busy !== null" @click="revokeAll">
        {{ busy === "all" ? "Revoking…" : "Revoke all sessions" }}
      </button>
    </header>

    <SessionMap v-if="!loading && !error && hasMapData()" :sessions="sessions" />

    <p v-if="loading">Loading…</p>
    <p v-else-if="error" class="form-error">{{ error }}</p>
    <div v-else class="list">
      <article v-for="s in sessions" :key="s.id" class="session">
        <header>
          <strong>{{ s.is_current ? "Current session" : s.state }}</strong>
          <button v-if="s.state === 'active' && !s.is_current" class="danger" :disabled="busy !== null"
            @click="revoke(s.id)">
            {{ busy === s.id ? "Revoking…" : "Revoke" }}
          </button>
        </header>
        <p>{{ locationText(s) }} · {{ s.ip_address || "IP unavailable" }}</p>
        <p v-if="s.location.network_number !== null">
          Network {{ s.location.network_number }}{{
            s.location.network_organization
              ? " · " + s.location.network_organization
              : ""
          }}
        </p>
        <p>{{ s.user_agent || "Device unavailable" }}</p>
        <small>
          Created {{ fmt(s.created_at) }} · Last activity
          {{ fmt(s.last_seen_at) }} · Expires {{ fmt(s.expires_at) }}
        </small>
        <p v-if="s.anomaly.reason" class="anomaly">
          {{ s.anomaly.reason }} Location is approximate.
        </p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.section-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.list {
  display: grid;
  gap: 12px;
}

.session {
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 14px;
  background: #141414;
}

.session header {
  display: flex;
  justify-content: space-between;
}

.session p {
  color: #bbb;
  font-size: 13px;
}

.session small {
  color: #777;
}

.danger {
  border: 0;
  background: #333;
  color: #fca5a5;
  padding: 7px 10px;
  border-radius: 6px;
}

.anomaly {
  color: #fca5a5 !important;
}

.form-error {
  color: #fca5a5;
}
</style>
