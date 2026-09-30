<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import SegmentedControl from "./SegmentedControl.vue";
import {
  fetchLibraryExport,
  importLibrary,
  fetchBackupStatus,
  previewMal,
  importMal,
  previewList,
  importList,
  restoreMedia,
  fetchMediaCsv,
  importYamtrack,
} from "../../services/exportImport";
import type {
  ImportResult,
  BackupStatus,
  MalImportResult,
  MalPreview,
  ImportSource,
  MediaRestoreResult,
  YamtrackImportResult,
} from "../../services/exportImport";

const backupStatus = ref<BackupStatus | null>(null);
onMounted(async () => {
  try {
    backupStatus.value = await fetchBackupStatus();
  } catch {
    // status tile just doesn't show, not worth failing the whole page over
  }
});
function formatBackupDate(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

const exporting = ref(false);
const exportError = ref<string | null>(null);

async function exportLibrary() {
  exporting.value = true;
  exportError.value = null;
  try {
    const data = await fetchLibraryExport();
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const date = new Date().toISOString().slice(0, 10);
    const link = document.createElement("a");
    link.href = url;
    link.download = `library-export-${date}.json`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    exportError.value =
      err instanceof Error ? err.message : "Failed to export library";
  } finally {
    exporting.value = false;
  }
}

const csvBusy = ref(false);
const csvError = ref<string | null>(null);
async function exportCsv() {
  csvBusy.value = true;
  csvError.value = null;
  try {
    const url = URL.createObjectURL(await fetchMediaCsv());
    const link = document.createElement("a");
    link.href = url;
    link.download = `media-library-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    csvError.value =
      err instanceof Error ? err.message : "Failed to export the CSV";
  } finally {
    csvBusy.value = false;
  }
}

const SOURCES: {
  value: ImportSource;
  label: string;
  accept: string;
  what: string;
  how: string;
}[] = [
  {
    value: "mal",
    label: "MyAnimeList",
    accept: ".xml,.gz,application/xml,text/xml,application/gzip",
    what: "anime",
    how: "Use MyAnimeList's export file (the .xml or .xml.gz from its export page). Status, episodes watched, score, rewatches, dates, tags and your comment come across.",
  },
  {
    value: "letterboxd",
    label: "Letterboxd",
    accept: ".zip,.csv,application/zip,text/csv",
    what: "movies",
    how: "Use the zip from Letterboxd's data export (or one of its CSV files). Watched films, ratings (doubled onto the 10-point scale), rewatches from your diary, liked films as favorites, and your watchlist come across.",
  },
  {
    value: "imdb",
    label: "IMDb",
    accept: ".csv,text/csv",
    what: "movies and TV shows",
    how: "Use an IMDb ratings or watchlist export (the CSV from your list's Export button). Rated titles come in as watched with your rating, unrated ones as plan to watch. Episodes and other kinds are skipped.",
  },
  {
    value: "yamtrack",
    label: "Yamtrack",
    accept: ".csv,text/csv",
    what: "movies, TV shows and anime",
    how: "Use Yamtrack's CSV export. Movies, TV shows and anime are grouped by Yamtrack's provider ID, with seasons and watched episodes restored under the correct parent.",
  },
];
const source = ref<ImportSource>("mal");
const sourceInfo = computed(
  () => SOURCES.find((s) => s.value === source.value) ?? SOURCES[0],
);
function changeSource(value: string) {
  source.value = value as ImportSource;
  cancelMal();
  malResult.value = null;
  malError.value = null;
  yamtrackResult.value = null;
  yamtrackError.value = null;
}

const yamtrackBusy = ref(false);
const yamtrackError = ref<string | null>(null);
const yamtrackResult = ref<YamtrackImportResult | null>(null);

const malBusy = ref(false);
const malError = ref<string | null>(null);
const malFile = ref<File | null>(null);
const malPreview = ref<MalPreview | null>(null);
const malResult = ref<MalImportResult | null>(null);
// titles already on the site whose data the user wants replaced by MAL's
const useMal = ref<Set<string>>(new Set());
const fetchDetails = ref(true);

async function onMalSelected(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  malBusy.value = true;
  malError.value = null;
  malResult.value = null;
  malPreview.value = null;
  useMal.value = new Set();
  try {
    if (source.value === "yamtrack") {
      yamtrackResult.value = await importYamtrack(file);
      return;
    }
    malPreview.value =
      source.value === "mal"
        ? await previewMal(file)
        : await previewList(file, source.value);
    malFile.value = file;
  } catch (err) {
    malError.value =
      err instanceof Error ? err.message : "Failed to read the file";
  } finally {
    malBusy.value = false;
    input.value = "";
  }
}
function toggleMal(id: string) {
  const next = new Set(useMal.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  useMal.value = next;
}
function chooseAllMal(all: boolean) {
  useMal.value = new Set(
    all ? (malPreview.value?.existing.map((x) => x.mal_id) ?? []) : [],
  );
}
function cancelMal() {
  malPreview.value = null;
  malFile.value = null;
  useMal.value = new Set();
}
async function runMalImport() {
  if (!malFile.value) return;
  malBusy.value = true;
  malError.value = null;
  try {
    if (source.value === "mal") {
      malResult.value = await importMal(
        malFile.value,
        [...useMal.value],
        fetchDetails.value,
      );
    } else if (source.value === "letterboxd" || source.value === "imdb") {
      malResult.value = await importList(
        malFile.value,
        source.value,
        [...useMal.value],
        fetchDetails.value,
      );
    }
    cancelMal();
  } catch (err) {
    malError.value =
      err instanceof Error ? err.message : "Failed to import the list";
  } finally {
    malBusy.value = false;
  }
}

const restoreBusy = ref(false);
const restoreError = ref<string | null>(null);
const restoreResult = ref<MediaRestoreResult | null>(null);
const RESTORE_LABEL: Record<string, string> = {
  movies: "movies",
  tv_shows: "TV shows",
  anime: "anime",
};
async function onRestoreSelected(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  restoreBusy.value = true;
  restoreError.value = null;
  restoreResult.value = null;
  try {
    restoreResult.value = await restoreMedia(file);
  } catch (err) {
    restoreError.value =
      err instanceof Error ? err.message : "Failed to restore the export";
  } finally {
    restoreBusy.value = false;
    input.value = "";
  }
}

const importing = ref(false);
const importError = ref<string | null>(null);
const importResult = ref<ImportResult | null>(null);

async function onFileSelected(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;

  importing.value = true;
  importError.value = null;
  importResult.value = null;

  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    const games = Array.isArray(parsed) ? parsed : parsed.games;
    if (!Array.isArray(games)) {
      throw new Error(
        'This file doesn\'t look like a library export, expected a "games" list.',
      );
    }
    importResult.value = await importLibrary(games);
  } catch (err) {
    importError.value =
      err instanceof Error ? err.message : "Failed to import library";
  } finally {
    importing.value = false;
    // otherwise re-picking the same file for a second attempt fires no
    // 'change' event at all
    input.value = "";
  }
}
</script>

<template>
  <section class="settings-section">
    <h2>Export / Import</h2>
    <p class="section-hint">
      A portable JSON snapshot of your whole library (games, movies, TV shows
      and anime) for backups, or moving to a new server. Covers title data and
      metadata only, not attached files (screenshots, saves, docs). Games,
      movies, TV shows and anime can each be brought back below.
    </p>

    <div v-if="backupStatus" class="tile backup-status-tile">
      <h3>Automatic backups</h3>
      <p class="tile-desc">
        A snapshot like the one above is written automatically every
        {{ backupStatus.interval_hours }} hours, keeping the last
        {{ backupStatus.backups_kept }} on this server, a safety net, not a
        replacement for the manual export below (nothing here can be downloaded
        directly; it's the same file shape, stored server-side).
      </p>
      <p class="backup-status-line">
        <span v-if="backupStatus.last_backup_at">
          Last backup {{ formatBackupDate(backupStatus.last_backup_at) }} ·
          {{ backupStatus.backup_count }} kept
        </span>
        <span v-else
          >No backup yet, the first one is written within
          {{ backupStatus.interval_hours }} hours of the server starting.</span
        >
      </p>
    </div>

    <div class="tile">
      <h3>Export</h3>
      <p class="tile-desc">
        Downloads your games, movies, TV shows, and anime as a single JSON file.
      </p>
      <div v-if="exportError" class="form-error">{{ exportError }}</div>
      <button
        type="button"
        class="primary-button"
        :disabled="exporting"
        @click="exportLibrary"
      >
        {{ exporting ? "Exporting…" : "Export library" }}
      </button>
    </div>

    <div class="tile">
      <h3>Export as a spreadsheet</h3>
      <p class="tile-desc">
        Movies, TV shows and anime as one CSV: status, score, favorite,
        rewatches, genres and episodes watched.
      </p>
      <div v-if="csvError" class="form-error">{{ csvError }}</div>
      <button
        type="button"
        class="secondary-button"
        :disabled="csvBusy"
        @click="exportCsv"
      >
        {{ csvBusy ? "Exporting…" : "Export CSV" }}
      </button>
    </div>

    <div class="tile">
      <h3>Import from another site</h3>
      <div class="mal-source">
        <SegmentedControl
          :model-value="source"
          :options="SOURCES.map((s) => ({ value: s.value, label: s.label }))"
          @update:model-value="changeSource"
        />
      </div>
      <p class="tile-desc">
        Add your {{ sourceInfo.what }}. {{ sourceInfo.how }}
        <template v-if="source !== 'yamtrack'">
          You see what it would add or change before anything happens, and for
          titles already on the site you choose, title by title, whether to keep
          them as they are or use the file's data.
        </template>
        <template v-else>
          Yamtrack imports directly and skips items already in your library.
        </template>
      </p>
      <div v-if="malError" class="form-error">{{ malError }}</div>
      <div v-if="yamtrackError" class="form-error">{{ yamtrackError }}</div>
      <div v-if="yamtrackResult" class="form-success">
        Movies: {{ yamtrackResult.created.movies ?? 0 }} added,
        TV shows: {{ yamtrackResult.created.tv_shows ?? 0 }} added,
        anime: {{ yamtrackResult.created.anime ?? 0 }} added.
        {{ yamtrackResult.seasons_created }} seasons and
        {{ yamtrackResult.episodes_created }} episodes imported.
        <template v-if="yamtrackResult.skipped.movies || yamtrackResult.skipped.tv_shows || yamtrackResult.skipped.anime">
          Existing items skipped:
          {{ (yamtrackResult.skipped.movies ?? 0) + (yamtrackResult.skipped.tv_shows ?? 0) + (yamtrackResult.skipped.anime ?? 0) }}.
        </template>
        <ul v-if="yamtrackResult.errors.length" class="import-errors">
          <li v-for="(err, i) in yamtrackResult.errors" :key="i">{{ err }}</li>
        </ul>
      </div>
      <div v-if="malResult" class="form-success">
        Added {{ malResult.created }}, updated {{ malResult.updated }} from the
        file, kept {{ malResult.kept }} as they were.
        <template v-if="malResult.details_filled"
          >Filled in details for {{ malResult.details_filled }}.</template
        >
        <template v-if="malResult.details_not_found">
          {{ malResult.details_source ?? "AniList" }} had no match for
          {{ malResult.details_not_found }}.</template
        >
        <template v-if="malResult.details_lookup_failed">
          AniList could not be reached for
          {{ malResult.details_lookup_failed }}, so their details are still
          blank: import the same file again later to fill them.</template
        >
        <template v-if="malResult.details_unavailable">
          No TMDB or OMDb key is set, so posters and details were not fetched:
          add one in Metadata Sources, then import the same file
          again.</template
        >
        <template v-if="malResult.assumed_complete">
          {{ malResult.assumed_complete }} marked Completed with no episodes
          listed, so counted as fully watched.</template
        >
        <template v-if="malResult.seasons_assumed_watched">
          {{ malResult.seasons_assumed_watched }} TV show{{
            malResult.seasons_assumed_watched === 1 ? "" : "s"
          }}
          were rated, so all their seasons are counted as fully watched: change
          any of them in the library.</template
        >
        <template v-if="malResult.skipped_other">
          {{ malResult.skipped_other }} rows were episodes or other kinds and
          were skipped.</template
        >
      </div>

      <div v-if="malPreview" class="mal-review">
        <p class="tile-desc">
          {{ malPreview.total }} titles in the file:
          <strong>{{ malPreview.new_count }} new</strong>,
          {{ malPreview.existing.length }} already here with differences,
          {{ malPreview.identical }} already here and identical.
        </p>
        <template v-if="malPreview.existing.length">
          <div class="mal-bulk">
            <button
              type="button"
              class="secondary-button"
              @click="chooseAllMal(true)"
            >
              Use MAL for all
            </button>
            <button
              type="button"
              class="secondary-button"
              @click="chooseAllMal(false)"
            >
              Keep all as they are
            </button>
          </div>
          <ul class="mal-list">
            <li v-for="item in malPreview.existing" :key="item.mal_id">
              <label class="mal-row">
                <input
                  type="checkbox"
                  :checked="useMal.has(item.mal_id)"
                  @change="toggleMal(item.mal_id)"
                />
                <span class="mal-title">{{ item.site_title }}</span>
                <span class="mal-choice">{{
                  useMal.has(item.mal_id) ? "Use MAL's" : "Keep as is"
                }}</span>
              </label>
              <ul class="mal-diffs">
                <li v-for="d in item.differences" :key="d.field">
                  {{ d.field }}: {{ d.site ?? "empty" }} on the site,
                  {{ d.mal }} on MAL
                </li>
              </ul>
            </li>
          </ul>
        </template>
        <label class="mal-details">
          <input v-model="fetchDetails" type="checkbox" />
          Fill in missing posters, genres and details from
          {{ source === "mal" ? "AniList" : "TMDB or OMDb" }}. This only fills
          blank fields and never replaces anything already there.
        </label>
        <div class="mal-actions">
          <button
            type="button"
            class="primary-button"
            :disabled="malBusy"
            @click="runMalImport"
          >
            {{ malBusy ? "Importing…" : "Import" }}
          </button>
          <button
            type="button"
            class="secondary-button"
            :disabled="malBusy"
            @click="cancelMal"
          >
            Cancel
          </button>
        </div>
      </div>
      <label v-else class="secondary-button upload-label">
        {{ source === "yamtrack" ? "Choose Yamtrack CSV…" : malBusy ? "Reading…" : "Choose file…" }}
        <input
          type="file"
          :accept="sourceInfo.accept"
          class="hidden-input"
          :disabled="malBusy || yamtrackBusy"
          @change="onMalSelected"
        />
      </label>
    </div>

    <div class="tile">
      <h3>Restore movies, TV shows and anime</h3>
      <p class="tile-desc">
        Add your movies, TV shows and anime back from a library export or a
        backup file, with their seasons and watched episodes. Anything already
        in your library (same title and year) is skipped, never overwritten.
      </p>
      <div v-if="restoreError" class="form-error">{{ restoreError }}</div>
      <div v-if="restoreResult" class="form-success">
        <template v-for="(label, key) in RESTORE_LABEL" :key="key"
          >{{ label }}: {{ restoreResult.created[key] ?? 0 }} added,
          {{ restoreResult.skipped[key] ?? 0 }} skipped.
        </template>
        <ul v-if="restoreResult.errors.length" class="import-errors">
          <li v-for="(err, i) in restoreResult.errors" :key="i">{{ err }}</li>
        </ul>
      </div>
      <label class="secondary-button upload-label">
        {{ restoreBusy ? "Restoring…" : "Choose file…" }}
        <input
          type="file"
          accept="application/json,.json"
          class="hidden-input"
          :disabled="restoreBusy"
          @change="onRestoreSelected"
        />
      </label>
    </div>

    <div class="tile">
      <h3>Import games</h3>
      <p class="tile-desc">
        Add games from a previously exported file. Existing games are never
        overwritten, a folder name collision gets a numbered suffix instead of
        failing the whole import.
      </p>
      <div v-if="importError" class="form-error">{{ importError }}</div>
      <div v-if="importResult" class="form-success">
        Imported {{ importResult.created }} game{{
          importResult.created === 1 ? "" : "s"
        }}.
        <template v-if="importResult.skipped"
          >{{ importResult.skipped }} skipped.</template
        >
        <ul v-if="importResult.errors.length" class="import-errors">
          <li v-for="(err, i) in importResult.errors" :key="i">{{ err }}</li>
        </ul>
      </div>
      <label class="secondary-button upload-label">
        {{ importing ? "Importing…" : "Choose file…" }}
        <input
          type="file"
          accept="application/json"
          class="hidden-input"
          :disabled="importing"
          @change="onFileSelected"
        />
      </label>
    </div>
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
.tile {
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 16px;
}
.tile h3 {
  margin: 0 0 6px;
  font-size: 0.9rem;
  color: #fff;
}
.tile-desc {
  color: #999;
  font-size: 0.8rem;
  line-height: 1.5;
  margin: 0 0 14px;
}
.backup-status-tile {
  border-color: rgba(214, 138, 52, 0.3);
  background: rgba(214, 138, 52, 0.04);
}
.backup-status-line {
  margin: 0;
  color: #d68a34;
  font-size: 0.78rem;
  font-weight: 600;
}
.primary-button {
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 8px;
  padding: 11px 20px;
  font-weight: 600;
  cursor: pointer;
}
.primary-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.secondary-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}
.upload-label {
  display: inline-block;
  cursor: pointer;
}
.hidden-input {
  display: none;
}
.form-error {
  color: #fca5a5;
  font-size: 13px;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 12px;
}
.form-success {
  color: #86efac;
  font-size: 13px;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 12px;
}
.import-errors {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #fca5a5;
  font-size: 12px;
}
.mal-source {
  margin-bottom: 12px;
}
.mal-review {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mal-bulk,
.mal-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.mal-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
}
.mal-list > li {
  padding: 10px 12px;
  border-bottom: 1px solid #1f1f1f;
}
.mal-list > li:last-child {
  border-bottom: none;
}
.mal-row {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  color: #fff;
  font-size: 0.85rem;
}
.mal-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mal-choice {
  color: #d68a34;
  font-size: 0.75rem;
}
.mal-diffs {
  list-style: none;
  margin: 6px 0 0 26px;
  padding: 0;
  color: #999;
  font-size: 0.75rem;
  line-height: 1.5;
}
.mal-details {
  display: flex;
  gap: 8px;
  color: #999;
  font-size: 0.8rem;
  line-height: 1.5;
}
</style>
