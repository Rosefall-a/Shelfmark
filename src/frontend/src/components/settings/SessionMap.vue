<script setup lang="ts">
import { computed, ref } from "vue";
import type { UserSession } from "../../services/sessions";

const props = withDefaults(
  defineProps<{ sessions: UserSession[]; admin?: boolean }>(),
  { admin: false },
);

type Point = {
  session: UserSession;
  x: number;
  y: number;
};

type Cluster = {
  points: Point[];
  x: number;
  y: number;
};

const mapElement = ref<HTMLElement | null>(null);
const selected = ref<UserSession[] | null>(null);
const zoom = ref(2);
const center = ref({ lat: 20, lon: 0 });
const dragging = ref(false);
const dragStart = ref({ x: 0, y: 0, lat: 0, lon: 0 });

const TILE_SIZE = 256;
const MIN_ZOOM = 1;
const MAX_ZOOM = 8;
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

const points = computed<Point[]>(() =>
  props.sessions
    .filter(
      (session) =>
        session.state !== "revoked" &&
        session.location.latitude !== null &&
        session.location.longitude !== null,
    )
    .map((session) => {
      const projected = project(
        session.location.latitude!,
        session.location.longitude!,
        zoom.value,
      );
      return { session, x: projected.x, y: projected.y };
    }),
);

const tiles = computed(() => {
  const viewport = mapElement.value;
  if (!viewport) return [];
  const width = viewport.clientWidth;
  const height = viewport.clientHeight;
  const scale = 2 ** zoom.value;
  const world = TILE_SIZE * scale;
  const projected = project(center.value.lat, center.value.lon, zoom.value);
  const minX = Math.floor((projected.x - width / 2) / TILE_SIZE) - 1;
  const maxX = Math.floor((projected.x + width / 2) / TILE_SIZE) + 1;
  const minY = Math.max(
    0,
    Math.floor((projected.y - height / 2) / TILE_SIZE) - 1,
  );
  const maxY = Math.min(
    scale - 1,
    Math.floor((projected.y + height / 2) / TILE_SIZE) + 1,
  );
  const result: Array<{ key: string; x: number; y: number; url: string }> = [];
  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      const wrappedX = ((x % scale) + scale) % scale;
      result.push({
        key: `${zoom.value}-${wrappedX}-${y}`,
        x,
        y,
        url: TILE_URL.replace("{z}", String(zoom.value))
          .replace("{x}", String(wrappedX))
          .replace("{y}", String(y)),
      });
    }
  }
  return result;
});

const clusters = computed<Cluster[]>(() => {
  const result: Cluster[] = [];
  const threshold = Math.max(18, 48 - zoom.value * 3);
  for (const point of points.value) {
    const existing = result.find(
      (cluster) =>
        Math.abs(cluster.x - point.x) < threshold &&
        Math.abs(cluster.y - point.y) < threshold,
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

function project(lat: number, lon: number, level: number) {
  const scale = TILE_SIZE * 2 ** level;
  const safeLat = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const radians = (safeLat * Math.PI) / 180;
  return {
    x: ((lon + 180) / 360) * scale,
    y:
      ((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2) *
      scale,
  };
}

function unproject(x: number, y: number, level: number) {
  const scale = TILE_SIZE * 2 ** level;
  const lon = (x / scale) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / scale;
  const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
  return { lat, lon };
}

function markerStyle(point: Point) {
  const projectedCenter = project(
    center.value.lat,
    center.value.lon,
    zoom.value,
  );
  let x = point.x - projectedCenter.x + (mapElement.value?.clientWidth ?? 0) / 2;
  const world = TILE_SIZE * 2 ** zoom.value;
  if (x < -world / 2) x += world;
  if (x > world / 2) x -= world;
  return {
    left: `${x}px`,
    top: `${point.y - projectedCenter.y + (mapElement.value?.clientHeight ?? 0) / 2}px`,
  };
}

function clusterStyle(cluster: Cluster) {
  const projectedCenter = project(
    center.value.lat,
    center.value.lon,
    zoom.value,
  );
  let x = cluster.x - projectedCenter.x + (mapElement.value?.clientWidth ?? 0) / 2;
  const world = TILE_SIZE * 2 ** zoom.value;
  if (x < -world / 2) x += world;
  if (x > world / 2) x -= world;
  return {
    left: `${x}px`,
    top: `${cluster.y - projectedCenter.y + (mapElement.value?.clientHeight ?? 0) / 2}px`,
  };
}

function userColor(userId: string): string {
  let hash = 0;
  for (const char of userId) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return `hsl(${Math.abs(hash) % 360} 75% 60%)`;
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

function clampLat(lat: number) {
  return Math.max(-85, Math.min(85, lat));
}

function wrapLon(lon: number) {
  return ((lon + 180) % 360 + 360) % 360 - 180;
}

function setZoom(nextZoom: number, focusX?: number, focusY?: number) {
  const oldZoom = zoom.value;
  const target = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, nextZoom));
  if (target === oldZoom) return;
  const element = mapElement.value;
  if (!element) {
    zoom.value = target;
    return;
  }
  const rect = element.getBoundingClientRect();
  const focus = {
    x: focusX ?? rect.width / 2,
    y: focusY ?? rect.height / 2,
  };
  const before = unproject(
    project(center.value.lat, center.value.lon, oldZoom).x +
      focus.x -
      rect.width / 2,
    project(center.value.lat, center.value.lon, oldZoom).y +
      focus.y -
      rect.height / 2,
    oldZoom,
  );
  zoom.value = target;
  const projected = project(before.lat, before.lon, target);
  const focusCenter = project(
    center.value.lat,
    center.value.lon,
    target,
  );
  const next = unproject(
    projected.x - focus.x + rect.width / 2,
    projected.y - focus.y + rect.height / 2,
    target,
  );
  center.value = { lat: clampLat(next.lat), lon: wrapLon(next.lon) };
}

function onWheel(event: WheelEvent) {
  event.preventDefault();
  setZoom(zoom.value + (event.deltaY < 0 ? 1 : -1), event.offsetX, event.offsetY);
}

function onPointerDown(event: PointerEvent) {
  const element = mapElement.value;
  if (!element) return;
  element.setPointerCapture(event.pointerId);
  dragging.value = true;
  dragStart.value = {
    x: event.clientX,
    y: event.clientY,
    lat: center.value.lat,
    lon: center.value.lon,
  };
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return;
  const dx = event.clientX - dragStart.value.x;
  const dy = event.clientY - dragStart.value.y;
  const projected = project(dragStart.value.lat, dragStart.value.lon, zoom.value);
  const next = unproject(projected.x - dx, projected.y - dy, zoom.value);
  center.value = { lat: clampLat(next.lat), lon: wrapLon(next.lon) };
}

function stopDragging() {
  dragging.value = false;
}

function resetView() {
  center.value = { lat: 20, lon: 0 };
  zoom.value = 2;
}

</script>

<template>
  <section class="map-card" aria-label="Session GIS map">
    <header>
      <div>
        <h3>Session locations</h3>
        <p>
          Interactive GIS basemap using OpenStreetMap. GeoIP positions are
          approximate and private/local addresses are not plotted.
        </p>
      </div>
      <div class="map-controls">
        <button type="button" @click="setZoom(zoom + 1)">+</button>
        <button type="button" @click="setZoom(zoom - 1)">−</button>
        <button type="button" @click="resetView">Reset</button>
        <span>{{ points.length }} mapped</span>
      </div>
    </header>

    <div
      ref="mapElement"
      class="map"
      :class="{ dragging }"
      @wheel="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="stopDragging"
      @pointercancel="stopDragging"
    >
      <img
        v-for="tile in tiles"
        :key="tile.key"
        class="tile"
        :src="tile.url"
        :style="{
          left: `${tile.x * TILE_SIZE - project(center.lat, center.lon, zoom).x + mapElement!.clientWidth / 2}px`,
          top: `${tile.y * TILE_SIZE - project(center.lat, center.lon, zoom).y + mapElement!.clientHeight / 2}px`,
        }"
        alt=""
        draggable="false"
      />

      <button
        v-for="cluster in clusters"
        :key="cluster.points.map((p) => p.session.id).join(',')"
        type="button"
        class="pin"
        :class="{ cluster: cluster.points.length > 1 }"
        :style="{
          ...clusterStyle(cluster),
          background:
            admin && cluster.points.length === 1
              ? userColor(cluster.points[0].session.user_id)
              : undefined,
        }"
        :title="label(cluster)"
        @pointerdown.stop
        @click.stop="openCluster(cluster)"
      >
        {{ cluster.points.length > 1 ? cluster.points.length : "" }}
      </button>

      <div class="attribution">
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          © OpenStreetMap contributors
        </a>
      </div>
    </div>

    <div v-if="admin && points.length" class="legend">
      Each colour represents a user; nearby sessions are clustered. Click a pin
      or bubble for details.
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

.map-controls {
  display: flex;
  gap: 5px;
  align-items: center;
  white-space: nowrap;
}

.map-controls button {
  border: 1px solid #444;
  background: #202020;
  color: #ddd;
  border-radius: 6px;
  padding: 5px 9px;
}

.map-controls span {
  color: #aaa;
  margin-left: 4px;
}

.map {
  position: relative;
  height: min(62vh, 620px);
  min-height: 320px;
  overflow: hidden;
  border-radius: 10px;
  background: #d8dee3;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.map.dragging {
  cursor: grabbing;
}

.tile {
  position: absolute;
  width: 256px;
  height: 256px;
  pointer-events: none;
  max-width: none;
}

.pin {
  position: absolute;
  z-index: 5;
  width: 16px;
  height: 16px;
  transform: translate(-50%, -100%) rotate(-45deg);
  border-radius: 50% 50% 50% 0;
  border: 2px solid white;
  box-shadow: 0 2px 8px #000a;
  background: #ef4444;
  padding: 0;
}

.pin::after {
  content: "";
  position: absolute;
  inset: 4px;
  border-radius: 50%;
  background: white;
}

.pin.cluster {
  width: 32px;
  height: 32px;
  transform: translate(-50%, -50%);
  rotate: 0deg;
  display: grid;
  place-items: center;
  color: white;
  font-size: 11px;
  font-weight: 700;
  background: #475569;
  border-radius: 50%;
}

.pin.cluster::after {
  display: none;
}

.attribution {
  position: absolute;
  z-index: 6;
  right: 4px;
  bottom: 3px;
  padding: 2px 5px;
  background: rgb(255 255 255 / 85%);
  font-size: 10px;
}

.attribution a {
  color: #333;
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
