<script setup lang="ts">
// Every notification in one place, with the detail behind each: which
// title, what happened, and the exact time it happened (the provider's own
// air time, not when the app noticed). The sidebar group shows the latest
// few; this page is the full list with filters and per-item actions.
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import AppTopBar from "../components/AppTopBar.vue";
import SegmentedTabs from "../components/SegmentedTabs.vue";
import type { SegmentOption } from "../components/SegmentedTabs.vue";
import {
  fetchMediaNotifications,
  markNotificationRead,
  markNotificationUnread,
  markAllNotificationsRead,
  deleteMediaNotification,
} from "../services/notifications";
import type {
  MediaNotification,
  MediaNotificationKind,
} from "../services/notifications";
import {
  notifications as bountyNotifications,
  refreshMediaNotifications,
} from "../state/notifications";
import { useKeptAlive } from "../utils/useKeptAlive";
import { useConfirm } from "../state/dialog";

type Filter =
  "all" | "unread" | "episodes" | "seasons" | "releases" | "bounties";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "episodes", label: "Episodes" },
  { key: "seasons", label: "Seasons" },
  { key: "releases", label: "Releases" },
  { key: "bounties", label: "Bounties" },
];

const router = useRouter();
const confirm = useConfirm();
const items = ref<MediaNotification[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const filter = ref<Filter>("all");
const openId = ref<string | null>(null);

async function load() {
  error.value = null;
  try {
    items.value = (await fetchMediaNotifications(200)).items;
  } catch (e) {
    error.value =
      e instanceof Error ? e.message : "Failed to load notifications.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
useKeptAlive(load);

const KIND_META: Record<
  MediaNotificationKind,
  { label: string; tone: string; group: Filter }
> = {
  episode_aired: { label: "Episode aired", tone: "amber", group: "episodes" },
  season_started: { label: "Season started", tone: "green", group: "seasons" },
  sequel_announced: {
    label: "New season listed",
    tone: "blue",
    group: "seasons",
  },
  movie_released: {
    label: "Movie released",
    tone: "violet",
    group: "releases",
  },
};

const unreadCount = computed(() => items.value.filter((n) => !n.read).length);
const counts = computed(() => {
  const c: Record<Filter, number> = {
    all: items.value.length,
    unread: unreadCount.value,
    episodes: 0,
    seasons: 0,
    releases: 0,
    bounties: bountyNotifications.value.length,
  };
  for (const n of items.value) c[KIND_META[n.kind].group] += 1;
  return c;
});
const filterOptions = computed<SegmentOption[]>(() =>
  FILTERS.map((f) => ({
    value: f.key,
    label: f.label,
    count: counts.value[f.key],
  })),
);
const shown = computed(() => {
  if (filter.value === "bounties") return [];
  return items.value.filter((n) => {
    if (filter.value === "all") return true;
    if (filter.value === "unread") return !n.read;
    return KIND_META[n.kind].group === filter.value;
  });
});

function dayKey(unix: number): string {
  const d = new Date(unix * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function dayLabel(key: string): string {
  const now = new Date();
  const today = dayKey(now.getTime() / 1000);
  const yesterday = dayKey(now.getTime() / 1000 - 86400);
  if (key === today) return "Today";
  if (key === yesterday) return "Yesterday";
  return new Date(`${key}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}
const grouped = computed(() => {
  const map = new Map<string, MediaNotification[]>();
  for (const n of shown.value) {
    const k = dayKey(n.eventAt);
    const list = map.get(k);
    if (list) list.push(n);
    else map.set(k, [n]);
  }
  return [...map.entries()].sort((a, b) => b[0].localeCompare(a[0]));
});

function exactTime(unix: number): string {
  return new Date(unix * 1000).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}
function timeOnly(unix: number): string {
  return new Date(unix * 1000).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}
function ago(unix: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - unix));
  if (s < 60) return "just now";
  const unit = (n: number, word: string) =>
    `${n} ${word}${n === 1 ? "" : "s"} ago`;
  if (s < 3600) return unit(Math.floor(s / 60), "minute");
  if (s < 86400) return unit(Math.floor(s / 3600), "hour");
  return unit(Math.floor(s / 86400), "day");
}
function route(n: MediaNotification): string {
  const base =
    n.mediaType === "movie"
      ? "/movies"
      : n.mediaType === "tv"
        ? "/tv"
        : "/anime";
  return `${base}/${n.mediaId}`;
}
const TYPE_LABEL: Record<string, string> = {
  movie: "Movie",
  tv: "TV show",
  anime: "Anime",
};

// ---- actions ----
async function setRead(n: MediaNotification, read: boolean) {
  const before = n.read;
  n.read = read;
  try {
    if (read) await markNotificationRead(n.id);
    else await markNotificationUnread(n.id);
    refreshMediaNotifications();
  } catch (e) {
    n.read = before;
    error.value = e instanceof Error ? e.message : "Failed to update.";
  }
}
async function readAll() {
  const before = items.value.map((n) => n.read);
  items.value.forEach((n) => (n.read = true));
  try {
    await markAllNotificationsRead();
    refreshMediaNotifications();
  } catch (e) {
    items.value.forEach((n, i) => (n.read = before[i]));
    error.value = e instanceof Error ? e.message : "Failed to update.";
  }
}
async function dismiss(n: MediaNotification) {
  const ok = await confirm({
    message: "Remove this notification?",
    confirmLabel: "Remove",
  });
  if (!ok) return;
  try {
    await deleteMediaNotification(n.id);
    items.value = items.value.filter((x) => x.id !== n.id);
    refreshMediaNotifications();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to remove.";
  }
}
async function open(n: MediaNotification) {
  if (!n.read) await setRead(n, true);
  router.push(route(n));
}
function toggleOpen(n: MediaNotification) {
  openId.value = openId.value === n.id ? null : n.id;
}
</script>

<template>
  <main class="ui-page">
    <AppTopBar>
      <SegmentedTabs
        :options="filterOptions"
        :model-value="filter"
        aria-label="Filter notifications"
        @update:model-value="filter = $event as Filter"
      />
      <template #actions>
        <button
          type="button"
          class="ui-btn ui-btn-secondary"
          :disabled="!unreadCount"
          @click="readAll"
        >
          Mark All Read
        </button>
      </template>
    </AppTopBar>

    <div class="ui-content narrow">
      <div class="ui-head">
        <div>
          <h1>Notifications</h1>
          <div class="sub">
            {{ unreadCount ? `${unreadCount} unread` : "All caught up" }}
          </div>
        </div>
      </div>
      <p v-if="error" class="ui-state error">{{ error }}</p>
      <p v-if="loading" class="ui-state">Loading…</p>

      <template v-else-if="filter === 'bounties'">
        <p v-if="!bountyNotifications.length" class="ui-state">
          No bounty deadlines or suggestions right now.
        </p>
        <div v-else class="list">
          <router-link
            v-for="b in bountyNotifications"
            :key="b.id"
            :to="b.to"
            class="card plain"
          >
            <span class="card-main">
              <span class="card-title">{{ b.title }}</span>
              <span class="card-body">{{ b.detail }}</span>
            </span>
            <span
              class="badge"
              :class="b.kind === 'deadline' ? 'red' : 'amber'"
              >{{ b.kind === "deadline" ? "Deadline" : "Suggested" }}</span
            >
          </router-link>
        </div>
      </template>

      <template v-else>
        <div v-if="!grouped.length" class="empty">
          <p class="empty-title">
            {{
              filter === "unread"
                ? "You're all caught up."
                : "Nothing here yet."
            }}
          </p>
          <p class="empty-sub">
            Episodes, season starts, new seasons and movie releases show up here
            as they happen, using the exact time the provider lists. Choose
            which ones you get under Settings, Calendar and Notifications.
          </p>
        </div>

        <section v-for="[key, day] in grouped" :key="key" class="day">
          <h2 class="day-heading">{{ dayLabel(key) }}</h2>
          <div class="list">
            <article
              v-for="n in day"
              :key="n.id"
              class="card"
              :class="{ unread: !n.read, open: openId === n.id }"
            >
              <button type="button" class="card-row" @click="toggleOpen(n)">
                <span
                  class="poster"
                  :style="
                    n.posterUrl
                      ? { backgroundImage: `url(${n.posterUrl})` }
                      : {}
                  "
                >
                  <span v-if="!n.posterUrl" class="poster-initial">{{
                    n.title.slice(0, 1)
                  }}</span>
                </span>
                <span class="card-main">
                  <span class="card-title">{{ n.title }}</span>
                  <span class="card-body">{{ n.body }}</span>
                  <span class="card-time"
                    >{{ timeOnly(n.eventAt) }} · {{ ago(n.eventAt) }}</span
                  >
                </span>
                <span class="badge" :class="KIND_META[n.kind].tone">{{
                  KIND_META[n.kind].label
                }}</span>
                <span v-if="!n.read" class="unread-dot" title="Unread"></span>
              </button>

              <div v-if="openId === n.id" class="detail">
                <dl>
                  <div>
                    <dt>What happened</dt>
                    <dd>{{ KIND_META[n.kind].label }}: {{ n.body }}</dd>
                  </div>
                  <div>
                    <dt>Title</dt>
                    <dd>{{ n.title }} ({{ TYPE_LABEL[n.mediaType] }})</dd>
                  </div>
                  <div>
                    <dt>
                      {{
                        n.kind === "sequel_announced" ? "Noticed" : "Exact time"
                      }}
                    </dt>
                    <dd>{{ exactTime(n.eventAt) }}</dd>
                  </div>
                </dl>
                <div class="detail-actions">
                  <button
                    type="button"
                    class="ui-btn ui-btn-sm ui-btn-primary"
                    @click="open(n)"
                  >
                    Open Title
                  </button>
                  <button
                    type="button"
                    class="ui-btn ui-btn-sm ui-btn-secondary"
                    @click="setRead(n, !n.read)"
                  >
                    {{ n.read ? "Mark Unread" : "Mark Read" }}
                  </button>
                  <button
                    type="button"
                    class="ui-btn ui-btn-sm ui-btn-danger-soft"
                    @click="dismiss(n)"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </article>
          </div>
        </section>
      </template>
    </div>
  </main>
</template>

<style scoped>
.empty {
  text-align: center;
  padding: 56px 16px;
}
.empty-title {
  margin: 0 0 8px;
  font-size: 1.05rem;
  font-weight: 800;
}
.empty-sub {
  margin: 0 auto;
  max-width: 460px;
  color: #9c9c9c;
  font-size: 0.84rem;
  line-height: 1.6;
}
.day {
  margin-bottom: 26px;
}
.day-heading {
  margin: 0 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid #202020;
  font-size: 0.74rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #d68a34;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card {
  background: #1a1a1a;
  border: 1px solid #202020;
  border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.15s ease;
}
.card:hover,
.card.open {
  border-color: rgba(214, 138, 52, 0.4);
}
.card.unread {
  border-left: 3px solid #d68a34;
}
.card.plain {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  text-decoration: none;
  color: inherit;
}
.card-row {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 10px 14px 10px 10px;
  background: none;
  border: none;
  text-align: left;
  color: inherit;
  font-family: inherit;
  cursor: pointer;
}
.poster {
  width: 46px;
  height: 66px;
  flex-shrink: 0;
  border-radius: 6px;
  background: #222 center / cover;
  display: flex;
  align-items: center;
  justify-content: center;
}
.poster-initial {
  font-size: 1.2rem;
  font-weight: 800;
  color: #444;
}
.card-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.card-title {
  font-size: 0.92rem;
  font-weight: 800;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-body {
  font-size: 0.82rem;
  color: #ccc;
}
.card-time {
  font-size: 0.72rem;
  color: #666;
}
.badge {
  flex-shrink: 0;
  font-size: 0.66rem;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 999px;
}
.badge.amber {
  background: rgba(214, 138, 52, 0.16);
  color: #d68a34;
}
.badge.green {
  background: rgba(111, 191, 115, 0.16);
  color: #6fbf73;
}
.badge.blue {
  background: rgba(123, 167, 217, 0.16);
  color: #7ba7d9;
}
.badge.violet {
  background: rgba(157, 140, 217, 0.16);
  color: #9d8cd9;
}
.badge.red {
  background: rgba(217, 111, 111, 0.16);
  color: #d96f6f;
}
.unread-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d68a34;
  flex-shrink: 0;
}
.detail {
  border-top: 1px solid #202020;
  padding: 14px 16px 16px 70px;
  background: #161616;
}
.detail dl {
  margin: 0 0 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.detail dt {
  font-size: 0.66rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #666;
}
.detail dd {
  margin: 2px 0 0;
  font-size: 0.84rem;
  color: #ddd;
}
.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
@media (max-width: 720px) {
  .badge {
    display: none;
  }
  .detail {
    padding-left: 16px;
  }
}
</style>
