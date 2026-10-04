<script setup lang="ts">
// Calendar and notification preferences. These are stored on the server
// (not in this browser), so they follow you between devices, and each
// change saves as soon as it is made.
import { ref, onMounted } from "vue";
import SegmentedControl from "./SegmentedControl.vue";
import ToggleButton from "./ToggleButton.vue";
import {
  DEFAULT_PREFERENCES,
  fetchPreferences,
  queuePreferences,
} from "../../services/preferences";
import type { Preferences } from "../../services/preferences";
import { preferences as sharedPreferences } from "../../state/preferences";

const prefs = ref<Preferences>({ ...DEFAULT_PREFERENCES });
const loaded = ref(false);
const error = ref<string | null>(null);
const savedNote = ref("");

onMounted(async () => {
  try {
    prefs.value = await fetchPreferences();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load settings.";
  } finally {
    loaded.value = true;
  }
});

async function change(changes: Partial<Preferences>) {
  const previous = { ...prefs.value };
  prefs.value = { ...prefs.value, ...changes };
  error.value = null;
  try {
    const { prefs: saved, latest } = await queuePreferences(changes);
    if (latest) {
      prefs.value = saved;
      sharedPreferences.value = saved;
    }
    savedNote.value = "Saved";
    setTimeout(() => (savedNote.value = ""), 1500);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to save.";
    try {
      prefs.value = await fetchPreferences();
    } catch {
      prefs.value = previous;
    }
  }
}

type NotifyStatus = Preferences["notify_statuses"][number];
type NotifyType = Preferences["notify_media_types"][number];
// switch one member of a set-valued preference on or off
function setMember<T extends string>(list: T[], value: T, on: boolean): T[] {
  return on
    ? [...list.filter((v) => v !== value), value]
    : list.filter((v) => v !== value);
}
const NOTIFY_STATUS_ROWS: { key: NotifyStatus; label: string; hint: string }[] =
  [
    {
      key: "watching",
      label: "Watching",
      hint: "titles you are in the middle of",
    },
    {
      key: "plan",
      label: "Plan to Watch",
      hint: "titles you have not started",
    },
    { key: "hold", label: "On Hold", hint: "titles you put aside" },
  ];
const NOTIFY_TYPE_ROWS: { key: NotifyType; label: string }[] = [
  { key: "anime", label: "Anime" },
  { key: "tv", label: "TV shows" },
  { key: "movie", label: "Movies" },
];

const viewOptions = [
  { value: "month", label: "Month" },
  { value: "week", label: "Week" },
  { value: "agenda", label: "Agenda" },
];
const retentionOptions = [
  { value: "7", label: "7 days" },
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "0", label: "Never" },
];
const weekOptions = [
  { value: "0", label: "Sunday" },
  { value: "1", label: "Monday" },
];

const props = withDefaults(
  defineProps<{ part?: "calendar" | "notifications" }>(),
  { part: "calendar" },
);
</script>

<template>
  <section class="settings-section">
    <h2>{{ props.part === "calendar" ? "Calendar" : "Notifications" }}</h2>
    <p class="section-hint">
      Saved on the server, so they follow you between browsers.
      <span v-if="savedNote" class="saved">{{ savedNote }}</span>
    </p>
    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="props.part === 'calendar'">
      <ToggleButton
        :model-value="prefs.calendar_game_releases"
        label="Game releases"
        :disabled="!loaded"
        @update:model-value="change({ calendar_game_releases: $event })"
      >
        <strong>Game releases</strong>: show the release date of every game in
        your library, past and upcoming
      </ToggleButton>
      <ToggleButton
        :model-value="prefs.calendar_game_history"
        label="Games history"
        :disabled="!loaded"
        @update:model-value="change({ calendar_game_history: $event })"
      >
        <strong>Games history</strong>: show the day you finished a game and the
        days you unlocked achievements
      </ToggleButton>

      <ToggleButton
        :model-value="prefs.calendar_show_estimated"
        label="Estimated episodes"
        :disabled="!loaded"
        @update:model-value="change({ calendar_show_estimated: $event })"
      >
        <strong>Estimated episodes</strong>: show later episodes projected from
        the show's usual schedule (drawn dashed). Only the next episode of a
        show is a confirmed date.
      </ToggleButton>
      <ToggleButton
        :model-value="prefs.calendar_hide_games"
        label="Hide all Games layers"
        :disabled="!loaded"
        @update:model-value="change({ calendar_hide_games: $event })"
      >
        <strong>Hide all Games layers</strong>: keep games off the calendar even
        when the two options above are on
      </ToggleButton>

      <h4 class="scope-title">Show airing episodes for titles that are</h4>
      <ToggleButton
        v-for="row in NOTIFY_STATUS_ROWS"
        :key="row.key"
        :model-value="prefs.calendar_airing_statuses.includes(row.key)"
        :label="row.label"
        :disabled="!loaded"
        @update:model-value="
          change({
            calendar_airing_statuses: setMember(
              prefs.calendar_airing_statuses,
              row.key,
              $event,
            ),
          })
        "
      >
        <strong>{{ row.label }}</strong
        >: {{ row.hint }}
      </ToggleButton>

      <div class="field">
        <span>Opens in</span>
        <SegmentedControl
          :model-value="prefs.calendar_default_view"
          :options="viewOptions"
          @update:model-value="
            change({
              calendar_default_view:
                $event as Preferences['calendar_default_view'],
            })
          "
        />
      </div>
      <div class="field">
        <span>Week starts on</span>
        <SegmentedControl
          :model-value="String(prefs.calendar_week_start)"
          :options="weekOptions"
          @update:model-value="
            change({
              calendar_week_start: Number(
                $event,
              ) as Preferences['calendar_week_start'],
            })
          "
        />
      </div>
    </template>

    <template v-else>
      <p class="section-hint">
        Built from exact air times and release dates, never from estimates. They
        show in the bell at the top of every page.
      </p>
      <div class="field">
        <span>Clear notifications after</span>
        <SegmentedControl
          :model-value="String(prefs.notification_retention_days)"
          :options="retentionOptions"
          @update:model-value="
            change({
              notification_retention_days: Number(
                $event,
              ) as Preferences['notification_retention_days'],
            })
          "
        />
      </div>
      <h4 class="scope-title">Notify me about titles that are</h4>
      <ToggleButton
        v-for="row in NOTIFY_STATUS_ROWS"
        :key="row.key"
        :model-value="prefs.notify_statuses.includes(row.key)"
        :label="row.label"
        :disabled="!loaded"
        @update:model-value="
          change({
            notify_statuses: setMember(prefs.notify_statuses, row.key, $event),
          })
        "
      >
        <strong>{{ row.label }}</strong
        >: {{ row.hint }}
      </ToggleButton>
      <h4 class="scope-title">Notify me about</h4>
      <ToggleButton
        v-for="row in NOTIFY_TYPE_ROWS"
        :key="row.key"
        :model-value="prefs.notify_media_types.includes(row.key)"
        :label="row.label"
        :disabled="!loaded"
        @update:model-value="
          change({
            notify_media_types: setMember(
              prefs.notify_media_types,
              row.key,
              $event,
            ),
          })
        "
      >
        <strong>{{ row.label }}</strong>
      </ToggleButton>
      <p class="section-hint scope-note">
        Only watching? Leave Watching on and switch off the other two. Completed
        and Dropped titles never send episode alerts. New season and sequel
        notices are about titles you finished, so they follow the kinds above
        and their own switches below, not this list.
      </p>
      <h4 class="scope-title">What to notify me about</h4>
      <ToggleButton
        :model-value="prefs.notify_episode_aired"
        label="Episode aired"
        :disabled="!loaded"
        @update:model-value="change({ notify_episode_aired: $event })"
      >
        <strong>Episode aired</strong>: a new episode of something you are
        watching, planning to watch or have on hold
      </ToggleButton>
      <ToggleButton
        :model-value="prefs.notify_season_started"
        label="Season started airing"
        :disabled="!loaded"
        @update:model-value="change({ notify_season_started: $event })"
      >
        <strong>Season started airing</strong>: the first episode of a season
        aired
      </ToggleButton>
      <ToggleButton
        :model-value="prefs.notify_sequel_announced"
        label="New season listed"
        :disabled="!loaded"
        @update:model-value="change({ notify_sequel_announced: $event })"
      >
        <strong>New season listed</strong>: a sequel appears for an anime you
        completed
      </ToggleButton>
      <ToggleButton
        :model-value="prefs.notify_movie_released"
        label="Movie released"
        :disabled="!loaded"
        @update:model-value="change({ notify_movie_released: $event })"
      >
        <strong>Movie released</strong>: a movie you were waiting on has come
        out
      </ToggleButton>
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
.settings-section h3 {
  margin: 22px 0 8px;
  font-size: 0.86rem;
  color: #ddd;
}
.scope-title {
  margin: 18px 0 8px;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #b9b9b9;
}
.scope-note {
  margin-top: 10px;
}
.section-hint {
  color: #9c9c9c;
  font-size: 0.82rem;
  line-height: 1.6;
  margin: 0 0 14px;
}
.saved {
  color: #6fbf73;
  margin-left: 8px;
  font-weight: 700;
}
.error {
  color: #e57373;
  font-size: 0.82rem;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 14px 0;
  font-size: 0.82rem;
  color: #ccc;
}
.settings-section :deep(.toggle-button) {
  margin: 12px 0;
}
</style>
