<script setup lang="ts">
import { ref, watch } from "vue";
import type { MediaType } from "../services/mediaExtras";

interface Playback {
  percentage: number | null;
  position_ticks: number;
  play_count: number;
  last_played_at: number | null;
  season?: number;
  number?: number;
}
interface ProviderState {
  provider_ids: Record<string, string>;
  sources: Array<{
    source: string;
    account_scope: string;
    available: boolean;
    playback: Playback | null;
    episode_progress: Record<string, Playback>;
    metadata: { artwork?: Record<string, string>; community_rating?: number };
  }>;
  history: Array<{
    id: string;
    played_at: number;
    duration_seconds: number | null;
    episode_external_id: string | null;
    provenance: string;
  }>;
  has_more: boolean;
}
const props = defineProps<{ mediaType: MediaType; mediaId: string }>();
const data = ref<ProviderState | null>(null);
const error = ref("");
const offset = ref(0);
const busy = ref(false);
let sequence = 0;
const formatDate = (value: number | null) =>
  value == null ? "Unknown" : new Date(value * 1000).toLocaleString();
async function load() {
  const current = ++sequence;
  busy.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({
      media_type: props.mediaType,
      media_id: props.mediaId,
      offset: String(offset.value),
    });
    const response = await fetch(`/api/media/provider-state?${params}`, {
      credentials: "include",
    });
    if (!response.ok)
      throw new Error("Unable to load provider progress and history.");
    const result = (await response.json()) as ProviderState;
    if (current === sequence) data.value = result;
  } catch {
    if (current === sequence)
      error.value = "Unable to load provider progress and history.";
  } finally {
    if (current === sequence) busy.value = false;
  }
}
watch(
  () => [props.mediaType, props.mediaId],
  () => {
    offset.value = 0;
    data.value = null;
    void load();
  },
  { immediate: true },
);
function page(direction: number) {
  offset.value = Math.max(0, offset.value + direction * 50);
  void load();
}
</script>

<template>
  <section v-if="error || data?.sources.length" class="provider-panel">
    <h3>Provider progress and viewing history</h3>
    <p v-if="error" role="status">{{ error }}</p>
    <template v-if="data">
      <details v-for="source in data.sources" :key="source.account_scope">
        <summary>
          {{ source.source }} ·
          {{ source.available ? "Available" : "Unavailable remotely" }}
        </summary>
        <div v-if="source.playback" class="provider-progress">
          <progress
            v-if="source.playback.percentage != null"
            :value="source.playback.percentage"
            max="100"
          />
          <span
            >{{ source.playback.percentage?.toFixed(1) ?? "Unknown" }}% ·
            {{ (source.playback.position_ticks / 10000000 / 60).toFixed(1) }}
            minutes · {{ source.playback.play_count }} plays</span
          >
          <p>Last played: {{ formatDate(source.playback.last_played_at) }}</p>
        </div>
        <p v-if="source.metadata.community_rating != null">
          Provider community score: {{ source.metadata.community_rating }}
        </p>
        <ul v-if="Object.keys(source.episode_progress).length">
          <li v-for="(episode, id) in source.episode_progress" :key="id">
            S{{ episode.season ?? "?" }} E{{ episode.number ?? "?" }} ·
            {{ episode.percentage?.toFixed(1) ?? "Unknown" }}% ·
            {{ episode.play_count }} plays ·
            {{ formatDate(episode.last_played_at) }}
          </li>
        </ul>
        <div class="provider-artwork">
          <a
            v-for="(url, kind) in source.metadata.artwork"
            :key="kind"
            :href="url"
            target="_blank"
            rel="noopener noreferrer"
            >{{ kind }}</a
          >
        </div>
      </details>
      <ol v-if="data.history.length">
        <li v-for="event in data.history" :key="event.id">
          {{ formatDate(event.played_at) }} ·
          {{
            event.duration_seconds == null
              ? "Unknown duration"
              : `${Math.round(event.duration_seconds / 60)} minutes`
          }}
          ·
          {{ event.episode_external_id ? "Episode session" : "Film session" }} ·
          {{
            event.provenance === "reported_session"
              ? "Reported viewing session"
              : "Last-played observation"
          }}
        </li>
      </ol>
      <p v-else>
        No individual sessions imported on this page. Aggregate counts do not
        reconstruct earlier sessions.
      </p>
      <div class="provider-actions">
        <button v-if="offset" :disabled="busy" @click="page(-1)">
          Previous
        </button>
        <button v-if="data.has_more" :disabled="busy" @click="page(1)">
          More progress and history
        </button>
        <button :disabled="busy" @click="load">Refresh</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.provider-panel {
  --text: var(--ui-dim);
  --text-h: var(--ui-text);
  --border: var(--ui-border);
  --accent: var(--ui-accent);
  --accent-bg: var(--ui-accent-soft);
  margin: 1rem 0;
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: var(--ui-radius-card);
  color: var(--text);
}
.provider-panel h3 {
  color: var(--text-h);
  margin-top: 0;
}
.provider-panel details {
  margin: 0.75rem 0;
}
.provider-panel summary {
  cursor: pointer;
}
.provider-progress {
  margin-top: 0.6rem;
}
.provider-progress progress {
  width: min(100%, 18rem);
  accent-color: var(--accent);
  display: block;
}
.provider-artwork,
.provider-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem;
}
.provider-artwork a {
  color: var(--accent);
}
.provider-actions button {
  color: var(--text-h);
  background: var(--accent-bg);
  border: 1px solid var(--border);
  padding: 0.4rem 0.7rem;
  border-radius: 0.4rem;
  cursor: pointer;
}
</style>
