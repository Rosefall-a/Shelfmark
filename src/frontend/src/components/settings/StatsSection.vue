<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { fetchStatsOverview } from "../../services/stats";
import type { StatsOverview } from "../../services/stats";
import { fetchGames } from "../../services/games";
import type { Game } from "../../types/game";
import SegmentedControl from "./SegmentedControl.vue";

const stats = ref<StatsOverview | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    stats.value = await fetchStatsOverview();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load stats";
  } finally {
    loading.value = false;
  }
});

// backlog burn-down, the aggregate stats endpoint has no month-by-month
// completion history, so this pulls the raw game list once and estimates
// pace from completionDate (set when a game first hits Mastered, the
// only "finished" timestamp that exists on a game, so a library that
// finishes games via "Beaten" without ever hitting 100% won't show a rate)
const libraryForBurnDown = ref<Game[]>([]);
onMounted(async () => {
  try {
    libraryForBurnDown.value = await fetchGames();
  } catch {
    libraryForBurnDown.value = [];
  }
});
const burnDown = computed(() => {
  const backlogCount = libraryForBurnDown.value.filter(
    (g) => g.status === "backlog",
  ).length;
  if (!backlogCount) return null;
  const sixMonthsAgo = Date.now() - 180 * 86_400_000;
  const recentCompletions = libraryForBurnDown.value.filter(
    (g) =>
      g.completionDate && new Date(g.completionDate).getTime() >= sixMonthsAgo,
  ).length;
  const perMonth = recentCompletions / 6;
  return {
    backlogCount,
    monthsEstimate: perMonth > 0 ? Math.ceil(backlogCount / perMonth) : null,
  };
});

const statusView = ref("chart");
const sourceView = ref("chart");
const timelineView = ref("chart");
const ratingView = ref("chart");
const tagsView = ref("chart");
const yearView = ref("chart");
const formatView = ref("chart");
const viewOptions = [
  { value: "chart", label: "Chart" },
  { value: "list", label: "List" },
];

// purchase_price isn't currency-tagged on the backend (it's summed across
// whatever currencies were entered per-game), so this is a plain number,
// not a localized currency string that would imply a single currency
function formatSpent(amount: number): string {
  return amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatPlaytime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  if (hours < 1) return `${Math.round(seconds / 60)}m`;
  return `${hours.toLocaleString()}h`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = -1;
  do {
    value /= 1024;
    unitIndex++;
  } while (value >= 1024 && unitIndex < units.length - 1);
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

function maxCount(entries: { count: number }[]): number {
  return Math.max(1, ...entries.map((e) => e.count));
}

// "completed" is deliberately narrow (beaten/mastered only, not "played",
// too ambiguous whether that means finished or just started) so this
// number stays defensible rather than a vibes-based guess
const completionRate = computed(() => {
  if (!stats.value || !stats.value.total_games) return null;
  const completed = (stats.value.status_breakdown ?? [])
    .filter(
      (e) =>
        e.label.toLowerCase() === "beaten" ||
        e.label.toLowerCase() === "mastered",
    )
    .reduce((sum, e) => sum + e.count, 0);
  return Math.round((completed / stats.value.total_games) * 100);
});

// only meaningful once there's both real spend and real playtime behind
// it, otherwise a library that's mostly free games would show a
// misleadingly tiny (or divide-by-zero) number
const costPerHour = computed(() => {
  if (
    !stats.value ||
    stats.value.total_spent <= 0 ||
    stats.value.total_playtime_seconds < 3600
  )
    return null;
  const hours = stats.value.total_playtime_seconds / 3600;
  return stats.value.total_spent / hours;
});

const statusBreakdown = computed(() => stats.value?.status_breakdown ?? []);
const sourceBreakdown = computed(() => stats.value?.source_breakdown ?? []);
const timeline = computed(() => stats.value?.recently_added ?? []);
const ratingHistogram = computed(() => stats.value?.rating_histogram ?? []);
const topTags = computed(() => stats.value?.top_tags ?? []);
const releaseYearBreakdown = computed(
  () => stats.value?.release_year_breakdown ?? [],
);
const formatBreakdown = computed(() => stats.value?.format_breakdown ?? []);
</script>

<template>
  <section class="settings-section">
    <h2>Server Stats</h2>
    <p class="section-hint">
      A live snapshot of your library: computed on every visit, nothing cached.
    </p>

    <p v-if="loading">Loading…</p>
    <p v-else-if="error" class="form-error">{{ error }}</p>
    <template v-else-if="stats">
      <div class="tiles">
        <div class="tile">
          <span class="tile-value">{{ stats.total_games }}</span>
          <span class="tile-label">Games</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{ stats.favorite_count }}</span>
          <span class="tile-label">Favorites</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{
            formatPlaytime(stats.total_playtime_seconds)
          }}</span>
          <span class="tile-label">Total playtime</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{
            formatBytes(stats.storage_used_bytes)
          }}</span>
          <span class="tile-label">Storage used</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{ formatSpent(stats.total_spent) }}</span>
          <span class="tile-label">Total spent</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{
            stats.average_rating != null
              ? stats.average_rating.toFixed(1)
              : "N/A"
          }}</span>
          <span class="tile-label">Average rating</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{
            costPerHour != null ? formatSpent(costPerHour) : "N/A"
          }}</span>
          <span class="tile-label">Cost per hour played</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{
            completionRate != null ? `${completionRate}%` : "N/A"
          }}</span>
          <span class="tile-label">Completed (beaten/mastered)</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{ stats.bounties_completed }}</span>
          <span class="tile-label">Bounties completed</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{ stats.bounty_points_total }}</span>
          <span class="tile-label">Bounty points earned</span>
        </div>
        <div class="tile">
          <span class="tile-value">{{ stats.bounties_hard_completed }}</span>
          <span class="tile-label">Hard+ challenges completed</span>
        </div>
      </div>

      <div v-if="burnDown" class="burn-down-card">
        <span class="burn-down-count">{{ burnDown.backlogCount }}</span>
        <div class="burn-down-body">
          <span class="burn-down-title"
            >game{{ burnDown.backlogCount === 1 ? "" : "s" }} in your
            backlog</span
          >
          <span class="burn-down-estimate">
            <template v-if="burnDown.monthsEstimate">
              At your last 6 months' pace, roughly
              {{ burnDown.monthsEstimate }} month{{
                burnDown.monthsEstimate === 1 ? "" : "s"
              }}
              to clear it
            </template>
            <template v-else
              >No games marked Mastered in the last 6 months, not enough data
              for a pace estimate</template
            >
          </span>
        </div>
      </div>

      <div class="breakdown-block">
        <div class="breakdown-header">
          <h3>Status</h3>
          <SegmentedControl v-model="statusView" :options="viewOptions" />
        </div>
        <div v-if="!statusBreakdown.length" class="empty-hint">
          No games yet.
        </div>
        <div v-else-if="statusView === 'chart'" class="bar-chart">
          <div
            v-for="entry in statusBreakdown"
            :key="entry.label"
            class="bar-row"
          >
            <span class="bar-label">{{ entry.label }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width: (entry.count / maxCount(statusBreakdown)) * 100 + '%',
                }"
              ></div>
            </div>
            <span class="bar-count">{{ entry.count }}</span>
          </div>
        </div>
        <ul v-else class="plain-list">
          <li v-for="entry in statusBreakdown" :key="entry.label">
            <span>{{ entry.label }}</span
            ><span>{{ entry.count }}</span>
          </li>
        </ul>
      </div>

      <div class="breakdown-block">
        <div class="breakdown-header">
          <h3>Source</h3>
          <SegmentedControl v-model="sourceView" :options="viewOptions" />
        </div>
        <div v-if="!sourceBreakdown.length" class="empty-hint">
          No games yet.
        </div>
        <div v-else-if="sourceView === 'chart'" class="bar-chart">
          <div
            v-for="entry in sourceBreakdown"
            :key="entry.label"
            class="bar-row"
          >
            <span class="bar-label">{{ entry.label }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width: (entry.count / maxCount(sourceBreakdown)) * 100 + '%',
                }"
              ></div>
            </div>
            <span class="bar-count">{{ entry.count }}</span>
          </div>
        </div>
        <ul v-else class="plain-list">
          <li v-for="entry in sourceBreakdown" :key="entry.label">
            <span>{{ entry.label }}</span
            ><span>{{ entry.count }}</span>
          </li>
        </ul>
      </div>

      <div class="breakdown-block">
        <div class="breakdown-header">
          <h3>Recently added</h3>
          <SegmentedControl v-model="timelineView" :options="viewOptions" />
        </div>
        <div v-if="!timeline.length" class="empty-hint">No games yet.</div>
        <div v-else-if="timelineView === 'chart'" class="bar-chart">
          <div v-for="entry in timeline" :key="entry.month" class="bar-row">
            <span class="bar-label">{{ entry.month }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width: (entry.count / maxCount(timeline)) * 100 + '%',
                }"
              ></div>
            </div>
            <span class="bar-count">{{ entry.count }}</span>
          </div>
        </div>
        <ul v-else class="plain-list">
          <li v-for="entry in timeline" :key="entry.month">
            <span>{{ entry.month }}</span
            ><span>{{ entry.count }}</span>
          </li>
        </ul>
      </div>

      <div class="breakdown-block">
        <h3>Most played</h3>
        <div v-if="!stats.most_played.length" class="empty-hint">
          No playtime tracked yet.
        </div>
        <ol v-else class="ranked-list">
          <li v-for="entry in stats.most_played" :key="entry.id">
            <span>{{ entry.title }}</span>
            <span class="ranked-value">{{
              formatPlaytime(entry.playtime_seconds)
            }}</span>
          </li>
        </ol>
      </div>

      <div class="breakdown-block">
        <div class="breakdown-header">
          <h3>Rating distribution</h3>
          <SegmentedControl v-model="ratingView" :options="viewOptions" />
        </div>
        <div v-if="!ratingHistogram.length" class="empty-hint">
          No ratings yet.
        </div>
        <div v-else-if="ratingView === 'chart'" class="bar-chart">
          <div
            v-for="entry in ratingHistogram"
            :key="entry.label"
            class="bar-row"
          >
            <span class="bar-label">{{ entry.label }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width: (entry.count / maxCount(ratingHistogram)) * 100 + '%',
                }"
              ></div>
            </div>
            <span class="bar-count">{{ entry.count }}</span>
          </div>
        </div>
        <ul v-else class="plain-list">
          <li v-for="entry in ratingHistogram" :key="entry.label">
            <span>{{ entry.label }}</span
            ><span>{{ entry.count }}</span>
          </li>
        </ul>
      </div>

      <div class="breakdown-block">
        <div class="breakdown-header">
          <h3>Top tags</h3>
          <SegmentedControl v-model="tagsView" :options="viewOptions" />
        </div>
        <div v-if="!topTags.length" class="empty-hint">No tags yet.</div>
        <div v-else-if="tagsView === 'chart'" class="bar-chart">
          <router-link
            v-for="entry in topTags"
            :key="entry.label"
            :to="`/games?tag=${encodeURIComponent(entry.label)}`"
            class="bar-row bar-row-link"
            :title="`View ${entry.label} games in your library`"
          >
            <span class="bar-label">{{ entry.label }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width: (entry.count / maxCount(topTags)) * 100 + '%',
                }"
              ></div>
            </div>
            <span class="bar-count">{{ entry.count }}</span>
          </router-link>
        </div>
        <ul v-else class="plain-list">
          <li v-for="entry in topTags" :key="entry.label">
            <router-link
              :to="`/games?tag=${encodeURIComponent(entry.label)}`"
              class="plain-list-link"
            >
              <span>{{ entry.label }}</span
              ><span>{{ entry.count }}</span>
            </router-link>
          </li>
        </ul>
      </div>

      <div class="breakdown-block">
        <div class="breakdown-header">
          <h3>Release year</h3>
          <SegmentedControl v-model="yearView" :options="viewOptions" />
        </div>
        <div v-if="!releaseYearBreakdown.length" class="empty-hint">
          No release dates yet.
        </div>
        <div v-else-if="yearView === 'chart'" class="bar-chart">
          <div
            v-for="entry in releaseYearBreakdown"
            :key="entry.label"
            class="bar-row"
          >
            <span class="bar-label">{{ entry.label }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width:
                    (entry.count / maxCount(releaseYearBreakdown)) * 100 + '%',
                }"
              ></div>
            </div>
            <span class="bar-count">{{ entry.count }}</span>
          </div>
        </div>
        <ul v-else class="plain-list">
          <li v-for="entry in releaseYearBreakdown" :key="entry.label">
            <span>{{ entry.label }}</span
            ><span>{{ entry.count }}</span>
          </li>
        </ul>
      </div>

      <div class="breakdown-block">
        <div class="breakdown-header">
          <h3>Physical / digital</h3>
          <SegmentedControl v-model="formatView" :options="viewOptions" />
        </div>
        <div v-if="!formatBreakdown.length" class="empty-hint">
          No games yet.
        </div>
        <div v-else-if="formatView === 'chart'" class="bar-chart">
          <div
            v-for="entry in formatBreakdown"
            :key="entry.label"
            class="bar-row"
          >
            <span class="bar-label">{{ entry.label }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width: (entry.count / maxCount(formatBreakdown)) * 100 + '%',
                }"
              ></div>
            </div>
            <span class="bar-count">{{ entry.count }}</span>
          </div>
        </div>
        <ul v-else class="plain-list">
          <li v-for="entry in formatBreakdown" :key="entry.label">
            <span>{{ entry.label }}</span
            ><span>{{ entry.count }}</span>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.settings-section h2 {
  margin: 0 0 8px;
  padding-left: 12px;
  border-left: 3px solid #d68a34;
  font-size: 1rem;
  color: #fff;
}
.section-hint {
  color: #999;
  font-size: 0.82rem;
  line-height: 1.6;
  margin: 0 0 20px;
}
.form-error {
  color: #fca5a5;
  font-size: 13px;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 28px;
}
.tile {
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.burn-down-card {
  display: flex;
  align-items: center;
  gap: 18px;
  background: rgba(214, 138, 52, 0.06);
  border: 1px solid rgba(214, 138, 52, 0.25);
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 28px;
}
.burn-down-count {
  font-size: 2.2rem;
  font-weight: 700;
  color: #d68a34;
  flex-shrink: 0;
}
.burn-down-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.burn-down-title {
  color: #fff;
  font-size: 13.5px;
  font-weight: 600;
}
.burn-down-estimate {
  color: #999;
  font-size: 12.5px;
}
.tile-value {
  font-size: 1.4rem;
  font-weight: 700;
  color: #d68a34;
}
.tile-label {
  font-size: 0.78rem;
  color: #999;
}
.breakdown-block {
  margin-bottom: 26px;
}
.breakdown-block h3 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  color: #fff;
}
.breakdown-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.breakdown-header h3 {
  margin: 0;
}
.empty-hint {
  color: #777;
  font-size: 0.82rem;
}
.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bar-row {
  display: grid;
  grid-template-columns: 140px 1fr 40px;
  align-items: center;
  gap: 10px;
}
.bar-row-link {
  text-decoration: none;
  color: inherit;
  border-radius: 6px;
  padding: 3px 6px;
  margin: -3px -6px;
}
.bar-row-link:hover {
  background: rgba(214, 138, 52, 0.1);
}
.bar-row-link:hover .bar-label {
  color: #d68a34;
}
.plain-list-link {
  display: flex;
  justify-content: space-between;
  width: 100%;
  color: inherit;
  text-decoration: none;
}
.bar-label {
  color: #ccc;
  font-size: 0.8rem;
  text-transform: capitalize;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bar-track {
  background: #111;
  border-radius: 6px;
  height: 16px;
  overflow: hidden;
}
.bar-fill {
  background: #d68a34;
  height: 100%;
  border-radius: 6px;
  transition: width 0.3s ease;
}
.bar-count {
  color: #999;
  font-size: 0.78rem;
  text-align: right;
}
.plain-list,
.ranked-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.plain-list li,
.ranked-list li {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
  color: #ccc;
  background: #111;
  border-radius: 6px;
  padding: 8px 12px;
}
.ranked-value {
  color: #d68a34;
  font-weight: 600;
}
</style>
