<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  fetchAdminSessions,
  fetchGeoIpStatus,
  revokeAdminSession,
  revokeAdminUserSessions,
  revokeAllAdminSessions,
  uploadGeoIp,
  type UserSession,
} from "../../services/sessions";
import SessionMap from "./SessionMap.vue";

const sessions = ref<UserSession[]>([]);
const q = ref("");
const stateFilter = ref<"active" | "expired" | "revoked">();
const countryFilter = ref("");
const anomalyFilter = ref(false);
const compact = ref(false);
const loading = ref(true);
const error = ref<string | null>(null);
const busy = ref<string | null>(null);
const geo = ref<Awaited<ReturnType<typeof fetchGeoIpStatus>> | null>(null);
const selectedUser = ref("");
const selectedFiles = ref({
  city: "",
  country: "",
  network: "",
});

const fmt = (v: number) => new Date(v * 1000).toLocaleString();
const users = computed(() => {
  const map = new Map<string, string>();
  for (const session of sessions.value) {
    if (session.username) map.set(session.user_id, session.username);
  }
  return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
});

function locationText(session: UserSession): string {
  if (session.location.network_label) return session.location.network_label;
  return (
    [session.location.city, session.location.region, session.location.country]
      .filter(Boolean)
      .join(", ") || "Unavailable"
  );
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    sessions.value = await fetchAdminSessions({
      q: q.value,
      user_id: selectedUser.value || undefined,
      state: stateFilter.value,
      country: countryFilter.value,
      anomaly: anomalyFilter.value || undefined,
    });
    geo.value = await fetchGeoIpStatus();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load sessions";
  } finally {
    loading.value = false;
  }
}

async function revoke(id: string) {
  busy.value = id;
  try {
    await revokeAdminSession(id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to revoke session";
  } finally {
    busy.value = null;
  }
}

async function revokeUser() {
  if (!selectedUser.value) return;
  const username =
    users.value.find(([id]) => id === selectedUser.value)?.[1] || "this user";
  if (!window.confirm(`Revoke every active session for ${username}?`)) return;
  busy.value = "user";
  try {
    await revokeAdminUserSessions(selectedUser.value);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to revoke user sessions";
  } finally {
    busy.value = null;
  }
}

async function revokeServer() {
  if (
    !window.confirm(
      "Revoke every active browser session for every user on this server?",
    )
  )
    return;
  busy.value = "server";
  try {
    await revokeAllAdminSessions();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to revoke server sessions";
  } finally {
    busy.value = null;
  }
}

function databaseName(status: { path: string } | undefined): string {
  if (!status?.path) return "Not configured";
  return status.path.split(/[\\/]/).pop() || status.path;
}

async function upload(kind: "city" | "country" | "network", e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  selectedFiles.value[kind] = file.name;
  try {
    await uploadGeoIp(file, kind);
    await load();
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Failed to upload GeoIP database";
  } finally {
    input.value = "";
  }
}

onMounted(load);
</script>

<template>
  <section class="settings-section">
    <header>
      <h2>Session Manager</h2>
      <p class="section-hint">
        Inspect browser sessions across all users. Raw session tokens are never
        returned.
      </p>
    </header>

    <div class="actions">
      <button class="danger" :disabled="busy !== null" @click="revokeServer">
        {{ busy === "server" ? "Revoking…" : "Revoke all server sessions" }}
      </button>
      <select v-model="selectedUser">
        <option value="">Select a user…</option>
        <option v-for="[id, name] in users" :key="id" :value="id">
          {{ name }}
        </option>
      </select>
      <button class="danger" :disabled="!selectedUser || busy !== null" @click="revokeUser">
        {{ busy === "user" ? "Revoking…" : "Revoke all for user" }}
      </button>
    </div>

    <details class="geo-config">
      <summary>Configure GeoIP databases</summary>
      <div class="geo">
        <div>
          <strong>GeoIP databases</strong>
          <p>
            City adds coordinates, Country adds country fallback data, and Network
            adds network number/owner data. Each file is optional and persisted
            under the application data directory.
          </p>
          <small>
            City: {{ databaseName(geo?.city) }} ·
            Country: {{ databaseName(geo?.country) }} ·
            Network: {{ databaseName(geo?.network) }}
          </small>
        </div>
        <div class="uploads">
          <label class="file-picker">
            <span>City database</span>
            <strong>{{ selectedFiles.city || databaseName(geo?.city) }}</strong>
            <input type="file" accept=".mmdb" @change="upload('city', $event)" />
          </label>
          <label class="file-picker">
            <span>Country database</span>
            <strong>{{ selectedFiles.country || databaseName(geo?.country) }}</strong>
            <input type="file" accept=".mmdb" @change="upload('country', $event)" />
          </label>
          <label class="file-picker">
            <span>Network / ASN database</span>
            <strong>{{ selectedFiles.network || databaseName(geo?.network) }}</strong>
            <input type="file" accept=".mmdb" @change="upload('network', $event)" />
          </label>
        </div>
      </div>
    </details>

    <SessionMap v-if="!loading && !error && geo?.city.configured" :sessions="sessions" admin />

    <div class="toolbar">
      <input v-model="q" placeholder="Search user, IP, device or location" @keyup.enter="load" />
      <select v-model="stateFilter" @change="load">
        <option :value="undefined">All states</option>
        <option value="active">Active</option>
        <option value="expired">Expired</option>
        <option value="revoked">Revoked</option>
      </select>
      <input v-model="countryFilter" placeholder="Country" @keyup.enter="load" />
      <label class="check">
        <input v-model="anomalyFilter" type="checkbox" @change="load" /> Anomalies
      </label>
      <button @click="load">Apply</button>
      <button type="button" @click="compact = !compact">
        {{ compact ? "Normal table" : "Compact table" }}
      </button>
    </div>

    <p v-if="loading">Loading…</p>
    <p v-else-if="error" class="form-error">{{ error }}</p>
    <div v-else class="table-wrap" :class="{ compact }">
      <table>
        <thead>
          <tr>
            <th>User</th>
            <th>State</th>
            <th>Location</th>
            <th>IP</th>
            <th>Device</th>
            <th>Network</th>
            <th>Created</th>
            <th>Last activity</th>
            <th>Expires</th>
            <th>Anomaly</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sessions" :key="s.id">
            <td>{{ s.username }}</td>
            <td>{{ s.state }}</td>
            <td>{{ locationText(s) }}</td>
            <td>{{ s.ip_address || "Unavailable" }}</td>
            <td>{{ s.user_agent || "Unavailable" }}</td>
            <td>
              {{ s.location.network_number ?? "—" }}
              {{
                s.location.network_organization
                  ? "· " + s.location.network_organization
                  : ""
              }}
            </td>
            <td>{{ fmt(s.created_at) }}</td>
            <td>{{ fmt(s.last_seen_at) }}</td>
            <td>{{ fmt(s.expires_at) }}</td>
            <td>{{ s.anomaly.reason || "—" }}</td>
            <td>
              <button v-if="s.state === 'active'" class="danger" :disabled="busy !== null" @click="revoke(s.id)">
                {{ busy === s.id ? "Revoking…" : "Revoke" }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.actions,
.toolbar,
.geo {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.actions select,
.toolbar input {
  flex: 1;
  background: #111;
  color: #fff;
  border: 1px solid #333;
  padding: 8px;
  border-radius: 7px;
}

.geo-config {
  margin-bottom: 12px;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 12px;
  background: #111;
}

.geo-config summary {
  cursor: pointer;
  color: #ddd;
  font-weight: 600;
}

.geo {
  justify-content: space-between;
  align-items: flex-start;
  color: #999;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 12px;
}

.geo p {
  max-width: 720px;
  margin: 6px 0 0;
  font-size: 12px;
}

.table-wrap {
  overflow: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  table-layout: auto;
}

th,
td {
  text-align: left;
  padding: 8px;
  border-bottom: 1px solid #252525;
  white-space: nowrap;
}

th {
  color: #777;
}

.table-wrap.compact table {
  font-size: 10px;
}

.table-wrap.compact th,
.table-wrap.compact td {
  padding: 4px 5px;
}

.table-wrap.compact td {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.uploads {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.file-picker {
  position: relative;
  display: grid;
  min-width: 190px;
  gap: 4px;
  padding: 9px 11px;
  border: 1px solid #333;
  border-radius: 7px;
  background: #181818;
  color: #aaa;
  cursor: pointer;
}

.file-picker strong {
  color: #ddd;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-picker input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.check {
  white-space: nowrap;
  color: #aaa;
}

.danger {
  border: 0;
  background: #333;
  color: #fca5a5;
  padding: 7px 10px;
  border-radius: 6px;
}

.form-error {
  color: #fca5a5;
}

code {
  color: #ddd;
}
</style>
