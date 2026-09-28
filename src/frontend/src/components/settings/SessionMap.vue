<script setup lang="ts">
import { computed, ref } from "vue";
import type { UserSession } from "../../services/sessions";

const props = withDefaults(
  defineProps<{ sessions: UserSession[]; admin?: boolean }>(),
  { admin: false },
);
const selected = ref<UserSession[] | null>(null);

type Point = { session: UserSession; x: number; y: number };
type Cluster = { points: Point[]; x: number; y: number };

const points = computed<Point[]>(() =>
  props.sessions
    .filter(
      (session) =>
        session.state !== "revoked" &&
        session.location.latitude !== null &&
        session.location.longitude !== null,
    )
    .map((session) => ({
      session,
      x: ((session.location.longitude! + 180) / 360) * 100,
      y: ((90 - session.location.latitude!) / 180) * 100,
    })),
);

const clusters = computed<Cluster[]>(() => {
  const result: Cluster[] = [];
  for (const point of points.value) {
    const existing = result.find(
      (cluster) =>
        Math.abs(cluster.x - point.x) < 3 &&
        Math.abs(cluster.y - point.y) < 3,
    );
    if (existing) {
      existing.points.push(point);
      existing.x =
        existing.points.reduce((sum, item) => sum + item.x, 0) /
        existing.points.length;
      existing.y =
        existing.points.reduce((sum, item) => sum + item.y, 0) /
        existing.points.length;
    } else {
      result.push({ points: [point], x: point.x, y: point.y });
    }
  }
  return result;
});

function userColor(userId: string): string {
  let hash = 0;
  for (const char of userId) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 75% 60%)`;
}

function openCluster(cluster: Cluster) {
  selected.value = cluster.points.map((point) => point.session);
}

function locationText(session: UserSession): string {
  if (session.location.network_label) return session.location.network_label;
  return (
    [session.location.city, session.location.region, session.location.country]
      .filter(Boolean)
      .join(", ") || "Location unavailable"
  );
}

function networkText(session: UserSession): string {
  if (session.location.network_number === null) return "";
  return (
    "Network " +
    session.location.network_number +
    (session.location.network_organization
      ? " · " + session.location.network_organization
      : "")
  );
}

function label(cluster: Cluster): string {
  if (cluster.points.length === 1) {
    const session = cluster.points[0].session;
    return [
      session.username,
      session.location.city,
      session.location.region,
      session.location.country,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  return `${cluster.points.length} sessions`;
}
</script>

<template>
  <section class="map-card" aria-label="Session world map">
    <header>
      <div>
        <h3>Session locations</h3>
        <p>
          Approximate GeoIP positions only. Private/local addresses are not
          plotted.
        </p>
      </div>
      <span>
        {{ points.length }} mapped session{{ points.length === 1 ? "" : "s" }}
      </span>
    </header>

    <div class="map">
      <svg class="continents" viewBox="0 0 1000 500" aria-hidden="true">
        <rect width="1000" height="500" rx="18" />
        <path d="M48 109l18-27 35-13 31 7 20 22 38 5 31 18 27 30-9 22-27 10-18 28-30 1-21-19-32-5-10-27-28-18z" />
        <path d="M68 85l28-10 25 7 14 17-31 5-23-7z" />
        <path d="M105 153l34 2 25 20-13 23-27-4-21-17z" />
        <path d="M202 226l25 12 20 29 17 16 2 31-17 41-14 48-19 29-16-5-7-33 9-39-8-36 7-38z" />
        <path d="M279 62l23-16 25 4 20 16-4 21-24 9-28-10-17-13z" />
        <path d="M424 91l31-23 39-5 35 16 29 26-3 21-27 15-17 29-36 8-31-14-29 3-19-18 10-25z" />
        <path d="M454 91l15-14 20 3 9 14-17 10-19-3z" />
        <path d="M479 172l28-10 31 9 13 23-8 23 14 23-8 37-20 33-9 43-25 34-19-10-2-36 12-30-7-30 11-31-12-31z" />
        <path d="M506 215l24 4 13 25-12 20-21-7-10-21z" />
        <path d="M571 198l40-16 42 5 35 18 34 4 38 28-5 25-31 12-19 26-38-2-20-17-34 4-22-21-31-11 7-28z" />
        <path d="M606 186l24-7 20 8-3 16-25 4-18-9z" />
        <path d="M695 91l36-20 41 7 28 19 24 9 18 22-8 20-30 2-18 18-34-8-25-20-28-5-14-19z" />
        <path d="M720 92l31-7 22 12-7 16-27 3-20-10z" />
        <path d="M790 218l30-8 32 13 23 24 28 15 8 27-25 18-35-8-22-20-29-10-11-27z" />
        <path d="M873 352l22-7 18 12 7 22-17 15-24-6-12-18z" />
        <path d="M746 367l18-5 13 14-5 20-17 7-15-13z" />
        <path d="M408 279l12-8 11 9-2 16-12 5-11-9z" />
        <path d="M365 299l13-7 11 10-5 14-13 3-10-8z" />
      </svg>
      <div v-for="cluster in clusters"
        :key="`${cluster.x}-${cluster.y}-${cluster.points.map((p) => p.session.id).join(',')}`" class="pin"
        :class="{ cluster: cluster.points.length > 1 }" :style="{
          left: `${cluster.x}%`,
          top: `${cluster.y}%`,
          background: admin && cluster.points.length === 1
            ? userColor(cluster.points[0].session.user_id)
            : undefined,
        }" :title="label(cluster)" @click="openCluster(cluster)">
        {{ cluster.points.length > 1 ? cluster.points.length : "" }}
      </div>
    </div>

    <div v-if="admin && points.length" class="legend">
      <span>
        Each colour represents a user; nearby sessions are clustered. Click a
        pin or bubble for details.
      </span>
    </div>
    <div v-if="selected" class="pin-details">
      <header>
        <strong>
          {{ selected.length }} session{{ selected.length === 1 ? "" : "s" }}
          at this location
        </strong>
        <button type="button" @click="selected = null">Close</button>
      </header>
      <article v-for="session in selected" :key="session.id">
        <strong>
          {{ session.username || (session.is_current ? "Current session" : "Session") }}
        </strong>
        <span>{{ locationText(session) }}</span>
        <span>{{ session.ip_address || "IP unavailable" }}</span>
        <span>{{ networkText(session) }}</span>
        <span>{{ session.user_agent || "Device unavailable" }}</span>
      </article>
    </div>
    <p v-if="!points.length" class="empty">
      No active sessions have usable GeoIP coordinates.
    </p>
  </section>
</template>

<style scoped>
.map-card {
  margin: 16px 0;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 16px;
  background: #111;
}

.map-card header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.map-card h3 {
  margin: 0 0 4px;
}

.map-card p,
.legend {
  color: #888;
  font-size: 12px;
  margin: 0;
}

.map-card header>span {
  color: #aaa;
  white-space: nowrap;
}

.map {
  position: relative;
  aspect-ratio: 2 / 1;
  overflow: hidden;
  border-radius: 10px;
  background: #08121c;
}

.continents {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.continents rect {
  fill: #081b2b;
}

.continents path {
  fill: #213a46;
  stroke: #31525d;
  stroke-width: 2;
}

.pin {
  position: absolute;
  width: 13px;
  height: 13px;
  transform: translate(-50%, -50%);
  border-radius: 50% 50% 50% 0;
  rotate: -45deg;
  background: #ef4444;
  border: 2px solid white;
  box-shadow: 0 2px 8px #000a;
}

.pin::after {
  content: "";
  position: absolute;
  inset: 3px;
  border-radius: 50%;
  background: white;
}

.pin.cluster {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  rotate: 0deg;
  display: grid;
  place-items: center;
  color: white;
  font-size: 11px;
  font-weight: 700;
  background: #475569;
}

.pin.cluster::after {
  display: none;
}

.legend {
  margin-top: 8px;
}

.empty {
  margin: 12px 0 0;
  color: #888;
}

.pin-details {
  margin-top: 12px;
  border: 1px solid #333;
  border-radius: 9px;
  padding: 10px;
  background: #161616;
}

.pin-details header {
  margin: 0 0 8px;
  align-items: center;
}

.pin-details article {
  display: grid;
  gap: 2px;
  padding: 8px 0;
  border-top: 1px solid #292929;
  font-size: 12px;
}

.pin-details article span {
  color: #aaa;
}

.pin-details button {
  background: #252525;
  color: #ddd;
  border: 0;
  border-radius: 6px;
  padding: 5px 8px;
}
</style>
