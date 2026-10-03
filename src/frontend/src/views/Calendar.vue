<script setup lang="ts">
// A real month-grid calendar with three layers (episode airings, upcoming
// Plan to Watch releases, and what you actually watched), an agenda view
// for "what's next", and History folded in as a second tab. Grid cells hold
// small poster thumbnails instead of title text: text is what stretched
// the columns and warped the grid, and a library with dozens of airing
// shows can't fit names in a cell anyway. Names live in the hover tooltip
// and the day drawer that opens on click.
import {
  ref,
  reactive,
  computed,
  onMounted,
  onActivated,
  onDeactivated,
  watch,
} from "vue";
import { useRouter } from "vue-router";
import { blurOnLeave } from "../utils/blurOnLeave";
import {
  fetchCalendar,
  fetchActivity,
  fetchCalendarFeedUrl,
  fetchCalendarGames,
  fetchCalendarEvents,
  createCalendarEvent,
  updateCalendarEvent,
  deleteCalendarEvent,
  createActivityEntry,
  updateActivityEntry,
  deleteActivityEntry,
} from "../services/mediaExtras";
import type {
  ActivityEventType,
  CalendarEntry,
  CalendarGameEntry,
  CalendarEventEntry,
  ActivityEntry,
  MediaType,
} from "../services/mediaExtras";
import AppTopBar from "../components/AppTopBar.vue";
import SegmentedTabs from "../components/SegmentedTabs.vue";
import type { SegmentOption } from "../components/SegmentedTabs.vue";
import {
  fetchPreferences,
  queuePreferences,
  DEFAULT_PREFERENCES,
} from "../services/preferences";
import type { Preferences } from "../services/preferences";
import { useKeptAlive } from "../utils/useKeptAlive";
import { useConfirm } from "../state/dialog";
import { fetchMovies } from "../services/movies";
import { fetchTVShows } from "../services/tvShows";
import { fetchAnime } from "../services/anime";
import { displayTitle } from "../utils/displayTitle";

const router = useRouter();
const tab = ref<"calendar" | "history">("calendar");
const calView = ref<"month" | "week" | "agenda">("month");
const TAB_OPTIONS: SegmentOption[] = [
  { value: "calendar", label: "Calendar" },
  { value: "history", label: "History" },
];
const VIEW_OPTIONS: SegmentOption[] = [
  { value: "month", label: "Month" },
  { value: "week", label: "Week" },
  { value: "agenda", label: "Agenda" },
];

// ---- shared library lookup (posters for watched chips + title picker) ----
interface PickableMedia {
  mediaType: MediaType;
  mediaId: string;
  title: string;
  posterUrl: string | null;
}
const manualLibrary = ref<PickableMedia[]>([]);
const manualLibraryLoaded = ref(false);
const posterByMedia = computed(() => {
  const map = new Map<string, string | null>();
  for (const m of manualLibrary.value)
    map.set(`${m.mediaType}-${m.mediaId}`, m.posterUrl);
  return map;
});
async function loadManualLibrary() {
  if (manualLibraryLoaded.value) return;
  const [movies, shows, anime] = await Promise.all([
    fetchMovies(),
    fetchTVShows(),
    fetchAnime(),
  ]);
  manualLibrary.value = [
    ...movies.map((m) => ({
      mediaType: "movie" as const,
      mediaId: m.id,
      title: m.title,
      posterUrl: m.posterUrl,
    })),
    ...shows.map((s) => ({
      mediaType: "tv" as const,
      mediaId: s.id,
      title: s.title,
      posterUrl: s.posterUrl,
    })),
    ...anime.map((a) => ({
      mediaType: "anime" as const,
      mediaId: a.id,
      title: displayTitle(a),
      posterUrl: a.posterUrl,
    })),
  ];
  manualLibraryLoaded.value = true;
}

// ---- filters (remembered between visits) ----
const FILTER_KEY = "calendar-filters-v1";
const filters = reactive({
  movie: true,
  tv: true,
  anime: true,
  game: true,
  episode: true,
  release: true,
  watched: true,
  event: true,
  estimated: true,
});
try {
  const saved = JSON.parse(localStorage.getItem(FILTER_KEY) ?? "null");
  if (saved && typeof saved === "object") {
    for (const k of Object.keys(filters) as (keyof typeof filters)[]) {
      if (typeof saved[k] === "boolean") filters[k] = saved[k];
    }
  }
} catch {
  /* storage unavailable: defaults are fine */
}
watch(filters, () => {
  try {
    localStorage.setItem(FILTER_KEY, JSON.stringify(filters));
  } catch {
    /* ignore */
  }
});

// ---- preferences (Settings > Calendar) ----
const prefs = ref<Preferences>({ ...DEFAULT_PREFERENCES });
const showGamesFilter = computed(
  () =>
    !prefs.value.calendar_hide_games &&
    (prefs.value.calendar_game_releases || prefs.value.calendar_game_history),
);
const weekStart = computed(() => prefs.value.calendar_week_start);
async function loadPreferences() {
  try {
    prefs.value = await fetchPreferences();
  } catch {
    // defaults are fine
  }
}

// which airing shows appear, by where they sit in the library: saved with the
// other calendar settings, so it holds on every device
type AiringStatus = Preferences["calendar_airing_statuses"][number];
const AIRING_STATUS_CHIPS: { key: AiringStatus; label: string }[] = [
  { key: "watching", label: "Watching" },
  { key: "plan", label: "Plan to Watch" },
  { key: "hold", label: "On Hold" },
];
async function toggleAiringStatus(key: AiringStatus) {
  const previous = prefs.value.calendar_airing_statuses;
  const next = previous.includes(key)
    ? previous.filter((s) => s !== key)
    : [...previous, key];
  prefs.value = { ...prefs.value, calendar_airing_statuses: next };
  try {
    const { latest } = await queuePreferences({
      calendar_airing_statuses: next,
    });
    if (latest) await loadCalendar();
  } catch {
    prefs.value = { ...prefs.value, calendar_airing_statuses: previous };
  }
}

// ---- calendar data ----
const gameEntries = ref<CalendarGameEntry[]>([]);
async function loadGameHistory() {
  try {
    // the server sends nothing unless Games history is switched on
    gameEntries.value = await fetchCalendarGames();
  } catch {
    gameEntries.value = [];
  }
}
const eventEntries = ref<CalendarEventEntry[]>([]);
async function loadEvents() {
  try {
    eventEntries.value = await fetchCalendarEvents();
  } catch {
    // the rest of the calendar still works without them
  }
}
const entries = ref<CalendarEntry[]>([]);
const calLoading = ref(true);
const calError = ref<string | null>(null);

const today = new Date();
today.setHours(0, 0, 0, 0);
const viewYear = ref(today.getFullYear());
const viewMonth = ref(today.getMonth()); // 0-11

const isCurrentMonth = computed(
  () =>
    viewYear.value === today.getFullYear() &&
    viewMonth.value === today.getMonth(),
);
const CAL_MAX_DAYS = 90;
// Back as far as the oldest entry of any kind (watch history, game history and
// release dates, your own entries), never earlier than the current month, so a
// brand-new account still has somewhere sensible to stand; forward as far as
// the backend projects airings.
const earliestMonth = computed(() => {
  let min = "";
  for (const a of historyEntries.value)
    if (!min || a.eventDate < min) min = a.eventDate;
  for (const g of gameEntries.value) if (!min || g.date < min) min = g.date;
  for (const e of eventEntries.value)
    if (!min || e.eventDate < min) min = e.eventDate;
  if (!min) return today.getFullYear() * 12 + today.getMonth();
  const d = new Date(`${min}T00:00:00`);
  return Math.min(
    d.getFullYear() * 12 + d.getMonth(),
    today.getFullYear() * 12 + today.getMonth(),
  );
});
const canGoPrev = computed(
  () => viewYear.value * 12 + viewMonth.value > earliestMonth.value,
);
const canGoNext = computed(() => {
  const firstOfNext = new Date(viewYear.value, viewMonth.value + 1, 1);
  return firstOfNext.getTime() - today.getTime() < CAL_MAX_DAYS * 86_400_000;
});
const jumpMonthValue = computed(
  () => `${viewYear.value}-${String(viewMonth.value + 1).padStart(2, "0")}`,
);
function jumpToMonth(event: Event) {
  const value = (event.target as HTMLInputElement).value;
  if (!/^\d{4}-\d{2}$/.test(value)) return;
  const [y, m] = value.split("-").map(Number);
  const index = y * 12 + (m - 1);
  const max =
    today.getFullYear() * 12 + today.getMonth() + Math.ceil(CAL_MAX_DAYS / 30);
  if (index < earliestMonth.value || index > max) return;
  viewYear.value = y;
  viewMonth.value = m - 1;
}

// Only a first load (nothing on screen yet) shows the loading state; later
// refreshes swap data in quietly.
async function loadCalendar() {
  if (!entries.value.length) calLoading.value = true;
  calError.value = null;
  try {
    // The backend only looks forward from today, so a wide window is
    // enough for every month the nav allows; past cells get their content
    // from the watched layer instead.
    entries.value = await fetchCalendar(CAL_MAX_DAYS);
  } catch (e) {
    calError.value =
      e instanceof Error ? e.message : "Failed to load the calendar.";
  } finally {
    calLoading.value = false;
  }
}

// ---- history data (also feeds the calendar's "watched" layer) ----
const historyEntries = ref<ActivityEntry[]>([]);
const historyLoading = ref(false);
const historyError = ref<string | null>(null);

async function loadHistory() {
  if (!historyEntries.value.length) historyLoading.value = true;
  historyError.value = null;
  try {
    // every entry there is, not a fixed window
    historyEntries.value = await fetchActivity(36500);
  } catch (e) {
    historyError.value =
      e instanceof Error ? e.message : "Failed to load history.";
  } finally {
    historyLoading.value = false;
  }
}
const refreshing = ref(false);
async function refreshAll() {
  refreshing.value = true;
  try {
    await loadPreferences();
    await Promise.all([
      loadCalendar(),
      loadHistory(),
      loadGameHistory(),
      loadEvents(),
    ]);
  } finally {
    refreshing.value = false;
  }
}
let appliedDefaultView = false;
onMounted(async () => {
  await refreshAll();
  if (!appliedDefaultView) {
    appliedDefaultView = true;
    calView.value = prefs.value.calendar_default_view;
  }
  loadManualLibrary();
});
useKeptAlive(refreshAll);

// ---- unify everything the grid/agenda draws ----
type Layer = "episode" | "release" | "watched" | "event";
type CalMediaType = MediaType | "game" | "custom";
interface CalItem {
  key: string;
  layer: Layer;
  mediaType: CalMediaType;
  mediaId: string;
  title: string;
  posterUrl: string | null;
  badge: string; // short text on the thumbnail: "12", "×3", ""
  detail: string; // longer line for tooltip/drawer
  projected: boolean;
  sortAt: number;
  dayKey: string;
  eventId?: string;
}

function keyOfDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function timeLabel(airAt: number): string {
  return new Date(airAt * 1000).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

function fromEntry(e: CalendarEntry): CalItem {
  const layer: Layer = e.kind === "release" ? "release" : "episode";
  const ep = e.nextEpisodeNumber ? `Episode ${e.nextEpisodeNumber}` : "";
  // a release/premiere date has no real time-of-day (see _date_to_unix's
  // noon-UTC encoding, a placeholder to keep the date right across
  // timezones, not an actual airing time)
  const when = layer === "release" ? "Release date" : timeLabel(e.airAt);
  const estimate = e.isProjected ? "estimated" : "";
  return {
    key: `${e.mediaType}-${e.mediaId}-${e.kind}-${e.nextEpisodeNumber ?? 0}`,
    layer,
    mediaType: e.mediaType,
    mediaId: e.mediaId,
    title: e.title,
    posterUrl: e.posterUrl,
    badge: e.nextEpisodeNumber ? String(e.nextEpisodeNumber) : "",
    detail: [ep, when, estimate].filter(Boolean).join(" · "),
    projected: e.isProjected,
    sortAt: e.airAt,
    dayKey: keyOfDate(new Date(e.airAt * 1000)),
  };
}
function fromGame(g: CalendarGameEntry): CalItem {
  const detail =
    g.kind === "game_released"
      ? "Release date"
      : g.kind === "game_finished"
        ? "Finished"
        : g.kind === "game_purchased"
          ? "Bought"
          : `${g.count} achievement${g.count === 1 ? "" : "s"} unlocked`;
  return {
    key: `${g.kind}-${g.gameId}-${g.date}`,
    // a release date belongs with the other releases, the rest with what you did
    layer: g.kind === "game_released" ? "release" : "watched",
    mediaType: "game",
    mediaId: g.gameId,
    title: g.title,
    posterUrl: g.posterUrl,
    badge:
      g.kind === "game_released"
        ? ""
        : g.kind === "game_finished"
          ? "✓"
          : g.kind === "game_purchased"
            ? "$"
            : String(g.count),
    detail,
    projected: false,
    sortAt: new Date(`${g.date}T12:00:00`).getTime() / 1000,
    dayKey: g.date,
  };
}
function fromEvent(e: CalendarEventEntry): CalItem {
  const linked =
    e.mediaType && e.mediaId
      ? (posterByMedia.value.get(`${e.mediaType}-${e.mediaId}`) ?? null)
      : null;
  return {
    key: `event-${e.id}`,
    layer: "event",
    mediaType: "custom",
    mediaId: e.mediaId ?? "",
    title: e.title,
    posterUrl: linked,
    badge: "",
    detail: [e.eventTime ? e.eventTime : "All day", e.note]
      .filter(Boolean)
      .join(" · "),
    projected: false,
    sortAt:
      new Date(`${e.eventDate}T${e.eventTime ?? "00:00"}:00`).getTime() / 1000,
    dayKey: e.eventDate,
    eventId: e.id,
  };
}
function fromActivity(a: ActivityEntry): CalItem | null {
  if (a.eventType !== "episodes_watched" && a.eventType !== "rewatched")
    return null;
  const isRewatch = a.eventType === "rewatched";
  return {
    key: `watched-${a.id}`,
    layer: "watched",
    mediaType: a.mediaType,
    mediaId: a.mediaId,
    title: a.mediaTitle,
    posterUrl: posterByMedia.value.get(`${a.mediaType}-${a.mediaId}`) ?? null,
    badge: isRewatch ? "↻" : a.count > 1 ? `×${a.count}` : "",
    detail: isRewatch
      ? "Rewatched"
      : `Watched ${a.count} episode${a.count === 1 ? "" : "s"}`,
    projected: false,
    sortAt: new Date(`${a.eventDate}T12:00:00`).getTime() / 1000,
    dayKey: a.eventDate,
  };
}

// Indexed by day once, when the underlying data changes, so drawing a
// month only looks up its ~42 days instead of filtering everything ever
// logged on every filter click or navigation.
function indexByDay(items: CalItem[]): Map<string, CalItem[]> {
  const map = new Map<string, CalItem[]>();
  for (const i of items) {
    const list = map.get(i.dayKey);
    if (list) list.push(i);
    else map.set(i.dayKey, [i]);
  }
  return map;
}
const upcomingByDay = computed(() =>
  indexByDay([
    ...entries.value.map(fromEntry),
    ...eventEntries.value.map(fromEvent),
  ]),
);
const watchedByDay = computed(() => {
  const items: CalItem[] = [];
  for (const a of historyEntries.value) {
    const item = fromActivity(a);
    if (item) items.push(item);
  }
  for (const g of gameEntries.value) items.push(fromGame(g));
  return indexByDay(items);
});
function passesFilters(i: CalItem): boolean {
  if (i.mediaType !== "custom" && !filters[i.mediaType]) return false;
  if (!filters[i.layer]) return false;
  if (i.mediaType === "game" && prefs.value.calendar_hide_games) return false;
  return !(
    i.projected &&
    (!filters.estimated || !prefs.value.calendar_show_estimated)
  );
}
function itemsForDay(key: string): CalItem[] {
  const a = upcomingByDay.value.get(key);
  const b = watchedByDay.value.get(key);
  if (!a && !b) return [];
  return [...(a ?? []), ...(b ?? [])]
    .filter(passesFilters)
    .sort((x, y) => x.sortAt - y.sortAt);
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const ALL_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY_LABELS = computed(() => [
  ...ALL_WEEKDAYS.slice(weekStart.value),
  ...ALL_WEEKDAYS.slice(0, weekStart.value),
]);

interface DayCell {
  day: number;
  inMonth: boolean;
  key: string;
  isToday: boolean;
  isPast: boolean;
  items: CalItem[];
}

const todayKey = keyOfDate(today);
const gridCells = computed<DayCell[]>(() => {
  const y = viewYear.value;
  const m = viewMonth.value;
  const firstWeekday = (new Date(y, m, 1).getDay() - weekStart.value + 7) % 7;
  const daysInMonth = new Date(y, m + 1, 0).getDate();
  // Always a full 6 rows would leave a blank final week most months, so
  // pad only to the end of the week the month actually reaches.
  const total = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;
  const cells: DayCell[] = [];
  for (let i = 0; i < total; i++) {
    const d = new Date(y, m, 1 - firstWeekday + i);
    const key = keyOfDate(d);
    cells.push({
      day: d.getDate(),
      inMonth: d.getMonth() === m,
      key,
      isToday: key === todayKey,
      isPast: key < todayKey,
      items: itemsForDay(key),
    });
  }
  return cells;
});

function prevMonth() {
  if (!canGoPrev.value) return;
  if (viewMonth.value === 0) {
    viewMonth.value = 11;
    viewYear.value -= 1;
  } else {
    viewMonth.value -= 1;
  }
}
function nextMonth() {
  if (!canGoNext.value) return;
  if (viewMonth.value === 11) {
    viewMonth.value = 0;
    viewYear.value += 1;
  } else {
    viewMonth.value += 1;
  }
}
function startOfWeek(d: Date): Date {
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  start.setDate(start.getDate() - ((start.getDay() - weekStart.value + 7) % 7));
  return start;
}
const weekAnchor = ref(startOfWeek(today));
watch(weekStart, () => (weekAnchor.value = startOfWeek(weekAnchor.value)));
interface WeekDay {
  key: string;
  label: string;
  isToday: boolean;
  isPast: boolean;
  items: CalItem[];
}
const weekDays = computed<WeekDay[]>(() =>
  Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekAnchor.value);
    d.setDate(d.getDate() + i);
    const key = keyOfDate(d);
    return {
      key,
      label: d.toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
      }),
      isToday: key === todayKey,
      isPast: key < todayKey,
      items: itemsForDay(key),
    };
  }),
);
const weekLabel = computed(() => {
  const end = new Date(weekAnchor.value);
  end.setDate(end.getDate() + 6);
  const fmt = (d: Date, year: boolean) =>
    d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      ...(year ? { year: "numeric" } : {}),
    });
  return `${fmt(weekAnchor.value, false)} to ${fmt(end, true)}`;
});
const isCurrentWeek = computed(
  () => keyOfDate(weekAnchor.value) === keyOfDate(startOfWeek(today)),
);
const canWeekNext = computed(
  () =>
    weekAnchor.value.getTime() + 7 * 86_400_000 - today.getTime() <
    CAL_MAX_DAYS * 86_400_000,
);
const canWeekPrev = computed(() => {
  const first = new Date(
    Math.floor(earliestMonth.value / 12),
    earliestMonth.value % 12,
    1,
  );
  return weekAnchor.value.getTime() > first.getTime();
});
function shiftWeek(weeks: number) {
  const next = new Date(weekAnchor.value);
  next.setDate(next.getDate() + weeks * 7);
  weekAnchor.value = next;
}
function goToday() {
  viewYear.value = today.getFullYear();
  viewMonth.value = today.getMonth();
  weekAnchor.value = startOfWeek(today);
}

// Grid chips: up to 6 slots; past that the last slot becomes "+N"
const CHIP_SLOTS = 6;
function chipsFor(cell: DayCell): { shown: CalItem[]; more: number } {
  if (cell.items.length <= CHIP_SLOTS) return { shown: cell.items, more: 0 };
  return {
    shown: cell.items.slice(0, CHIP_SLOTS - 1),
    more: cell.items.length - (CHIP_SLOTS - 1),
  };
}
function itemTooltip(i: CalItem): string {
  return `${i.title}${i.detail ? ` · ${i.detail}` : ""}`;
}
function activate(i: CalItem) {
  if (i.eventId) openEventEditor(i.eventId);
  else openItem(i);
}
function openItem(i: { mediaType: CalMediaType; mediaId: string }) {
  if (i.mediaType === "custom") return;
  const base =
    i.mediaType === "movie"
      ? "/movies"
      : i.mediaType === "anime"
        ? "/anime"
        : i.mediaType === "game"
          ? "/games"
          : "/tv";
  router.push(`${base}/${i.mediaId}`);
}

// ---- agenda: what's coming, day by day ----
const agendaGroups = computed(() =>
  [...upcomingByDay.value.keys()]
    .filter((key) => key >= todayKey)
    .sort()
    .map((key) => ({
      key,
      items: itemsForDay(key).filter((i) => i.layer !== "watched"),
    }))
    .filter((g) => g.items.length),
);
function longDayLabel(key: string): string {
  const yesterday = keyOfDate(new Date(today.getTime() - 86_400_000));
  const tomorrow = keyOfDate(new Date(today.getTime() + 86_400_000));
  const base = new Date(`${key}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
  if (key === todayKey) return `Today · ${base}`;
  if (key === tomorrow) return `Tomorrow · ${base}`;
  if (key === yesterday) return `Yesterday · ${base}`;
  return base;
}

// ---- day drawer (opens on click, holds the full list for that day) ----
const drawerKey = ref<string | null>(null);
const drawerItems = computed(() =>
  drawerKey.value ? itemsForDay(drawerKey.value) : [],
);
function openDrawer(cell: DayCell) {
  drawerKey.value = cell.key;
}
function closeDrawer() {
  drawerKey.value = null;
}
const LAYER_LABEL: Record<Layer, string> = {
  episode: "Airing",
  release: "Release",
  watched: "Watched",
  event: "Mine",
};

// ---- entries you add by hand ----
const showEventForm = ref(false);
const eventId = ref<string | null>(null);
const eventTitle = ref("");
const eventDate = ref(keyOfDate(new Date()));
const eventTime = ref("");
const eventNote = ref("");
const eventLink = ref<PickableMedia | null>(null);
const eventLinkSearch = ref("");
const eventError = ref<string | null>(null);
const eventSaving = ref(false);

async function openEventForm(date?: string) {
  eventId.value = null;
  eventTitle.value = "";
  eventDate.value = date ?? keyOfDate(new Date());
  eventTime.value = "";
  eventNote.value = "";
  eventLink.value = null;
  eventLinkSearch.value = "";
  eventError.value = null;
  showEventForm.value = true;
  if (!manualLibraryLoaded.value) await loadManualLibrary();
}
async function openEventEditor(id: string) {
  const e = eventEntries.value.find((x) => x.id === id);
  if (!e) return;
  if (!manualLibraryLoaded.value) await loadManualLibrary();
  eventId.value = e.id;
  eventTitle.value = e.title;
  eventDate.value = e.eventDate;
  eventTime.value = e.eventTime ?? "";
  eventNote.value = e.note ?? "";
  eventLink.value =
    manualLibrary.value.find(
      (m) => m.mediaType === e.mediaType && m.mediaId === e.mediaId,
    ) ?? null;
  eventLinkSearch.value = eventLink.value?.title ?? "";
  eventError.value = null;
  closeDrawer();
  showEventForm.value = true;
}
function closeEventForm() {
  showEventForm.value = false;
}
const eventLinkResults = computed(() => {
  const q = eventLinkSearch.value.trim().toLowerCase();
  if (!q || eventLink.value) return [];
  return manualLibrary.value
    .filter((m) => m.title.toLowerCase().includes(q))
    .slice(0, 6);
});
function pickEventLink(m: PickableMedia) {
  eventLink.value = m;
  eventLinkSearch.value = m.title;
}
async function saveEvent() {
  if (eventSaving.value) return; // a fast double click must not save twice
  if (!eventTitle.value.trim()) {
    eventError.value = "Give the entry a title.";
    return;
  }
  if (!eventDate.value) {
    eventError.value = "Pick a date.";
    return;
  }
  eventSaving.value = true;
  eventError.value = null;
  const input = {
    title: eventTitle.value.trim(),
    eventDate: eventDate.value,
    eventTime: eventTime.value || null,
    note: eventNote.value.trim() || null,
    mediaType: eventLink.value?.mediaType ?? null,
    mediaId: eventLink.value?.mediaId ?? null,
  };
  try {
    if (eventId.value) await updateCalendarEvent(eventId.value, input);
    else await createCalendarEvent(input);
    await loadEvents();
    closeEventForm();
  } catch (e) {
    eventError.value = e instanceof Error ? e.message : "Failed to save.";
  } finally {
    eventSaving.value = false;
  }
}
async function removeEvent() {
  if (!eventId.value) return;
  const ok = await confirm({
    title: "Delete entry",
    message: "Delete this calendar entry?",
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await deleteCalendarEvent(eventId.value);
    await loadEvents();
    closeEventForm();
  } catch (e) {
    eventError.value = e instanceof Error ? e.message : "Failed to delete.";
  }
}
function openLinkedTitle() {
  if (eventLink.value) openItem(eventLink.value);
}

// ---- keyboard: left and right change month or week, T goes to today ----
function onKey(e: KeyboardEvent) {
  if (tab.value !== "calendar" || calView.value === "agenda") return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const target = e.target as HTMLElement | null;
  if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
  if (
    drawerKey.value ||
    showEventForm.value ||
    showManualForm.value ||
    showFeed.value
  )
    return;
  if (e.key === "ArrowLeft") {
    if (calView.value === "month") prevMonth();
    else if (canWeekPrev.value) shiftWeek(-1);
  } else if (e.key === "ArrowRight") {
    if (calView.value === "month") nextMonth();
    else if (canWeekNext.value) shiftWeek(1);
  } else if (e.key.toLowerCase() === "t") {
    goToday();
  }
}
// Escape closes whichever dialog is open, like every other dialog in the app
function onEscape(e: KeyboardEvent) {
  if (e.key !== "Escape") return;
  if (showEventForm.value) closeEventForm();
  else if (showManualForm.value) closeManualForm();
  else if (showFeed.value) showFeed.value = false;
}
function listen() {
  window.addEventListener("keydown", onKey);
  window.addEventListener("keydown", onEscape);
}
function unlisten() {
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("keydown", onEscape);
}
onActivated(listen);
onDeactivated(unlisten);
onMounted(listen);

// ---- subscribe (iCal feed) ----
const showFeed = ref(false);
const feedUrl = ref("");
const feedError = ref<string | null>(null);
const feedCopied = ref(false);
const feedBusy = ref(false);
async function openFeed() {
  showFeed.value = true;
  feedError.value = null;
  feedCopied.value = false;
  if (feedUrl.value) return;
  try {
    feedUrl.value = await fetchCalendarFeedUrl();
  } catch (e) {
    feedError.value =
      e instanceof Error ? e.message : "Couldn't load the feed link.";
  }
}
async function copyFeed() {
  try {
    await navigator.clipboard.writeText(feedUrl.value);
    feedCopied.value = true;
    setTimeout(() => (feedCopied.value = false), 1800);
  } catch {
    feedError.value = "Copy failed. Select the link and copy it by hand.";
  }
}
const confirm = useConfirm();
async function regenerateFeed() {
  const ok = await confirm({
    message:
      "Make a new link? Anything subscribed to the old one stops updating.",
    confirmLabel: "Make new link",
  });
  if (!ok) return;
  feedBusy.value = true;
  try {
    feedUrl.value = await fetchCalendarFeedUrl(true);
    feedCopied.value = false;
  } catch (e) {
    feedError.value =
      e instanceof Error ? e.message : "Couldn't make a new link.";
  } finally {
    feedBusy.value = false;
  }
}

// ---- history (folded in as a second tab) ----
const historySearch = ref("");
const historyType = ref<"all" | ActivityEventType>("all");
const historyWindowDays = ref(60);

function historyDayLabel(key: string): string {
  return longDayLabel(key);
}
function describeActivity(e: ActivityEntry): string {
  switch (e.eventType) {
    case "episodes_watched":
      return `Watched ${e.count} episode${e.count === 1 ? "" : "s"} of ${e.mediaTitle}`;
    case "status_changed":
      return `${e.mediaTitle}${e.detail ? `: ${e.detail}` : " status changed"}`;
    case "rewatched":
      return `Rewatched ${e.mediaTitle}${e.count > 1 ? ` (${e.count} times)` : ""}`;
    case "rated":
      return `Rated ${e.mediaTitle}`;
    default:
      return e.mediaTitle;
  }
}
const HISTORY_ICONS: Record<ActivityEntry["eventType"], string> = {
  episodes_watched: "▶",
  status_changed: "↻",
  rewatched: "⟲",
  rated: "★",
};
const filteredHistory = computed(() => {
  const q = historySearch.value.trim().toLowerCase();
  return historyEntries.value.filter((e) => {
    if (historyType.value !== "all" && e.eventType !== historyType.value)
      return false;
    if (q && !e.mediaTitle.toLowerCase().includes(q)) return false;
    return true;
  });
});
const historyCutoff = computed(() =>
  keyOfDate(new Date(today.getTime() - historyWindowDays.value * 86_400_000)),
);
const groupedHistory = computed(() => {
  const map = new Map<string, ActivityEntry[]>();
  for (const e of filteredHistory.value) {
    if (e.eventDate < historyCutoff.value) continue;
    const list = map.get(e.eventDate);
    if (list) list.push(e);
    else map.set(e.eventDate, [e]);
  }
  return [...map.entries()].sort((a, b) => b[0].localeCompare(a[0]));
});
const hasOlderHistory = computed(() =>
  filteredHistory.value.some((e) => e.eventDate < historyCutoff.value),
);
function openHistoryEntry(e: ActivityEntry) {
  openItem(e);
}

// ---- editing a history entry: every field, including which title and
// event type it's attached to ----
const editingId = ref<string | null>(null);
const editDate = ref("");
const editCount = ref(1);
const editDetail = ref("");
const editEventType = ref<ActivityEventType>("episodes_watched");
const editMediaSearch = ref("");
const editMediaPicked = ref<PickableMedia | null>(null);
const editChangingMedia = ref(false);
const editError = ref<string | null>(null);

function startEdit(e: ActivityEntry) {
  editingId.value = e.id;
  editDate.value = e.eventDate;
  editCount.value = e.count;
  editDetail.value = e.detail ?? "";
  editEventType.value = e.eventType;
  editMediaPicked.value = {
    mediaType: e.mediaType,
    mediaId: e.mediaId,
    title: e.mediaTitle,
    posterUrl: posterByMedia.value.get(`${e.mediaType}-${e.mediaId}`) ?? null,
  };
  editMediaSearch.value = e.mediaTitle;
  editChangingMedia.value = false;
  editError.value = null;
}
function cancelEdit() {
  editingId.value = null;
}
const editSearchResults = computed(() => {
  const q = editMediaSearch.value.trim().toLowerCase();
  if (!q) return [];
  return manualLibrary.value
    .filter((m) => m.title.toLowerCase().includes(q))
    .slice(0, 8);
});
function pickEditMedia(m: PickableMedia) {
  editMediaPicked.value = m;
  editMediaSearch.value = m.title;
  editChangingMedia.value = false;
}
async function saveEdit(e: ActivityEntry) {
  if (!editMediaPicked.value) {
    editError.value = "Pick a title.";
    return;
  }
  editError.value = null;
  try {
    const updated = await updateActivityEntry(e.id, {
      mediaType: editMediaPicked.value.mediaType,
      mediaId: editMediaPicked.value.mediaId,
      eventType: editEventType.value,
      eventDate: editDate.value,
      count: editCount.value,
      detail: editDetail.value || null,
    });
    const idx = historyEntries.value.findIndex((h) => h.id === e.id);
    if (idx !== -1) {
      if (updated.id === e.id) {
        historyEntries.value[idx] = updated;
      } else {
        // moved onto a day that already had a bucket — merged server
        // side into that row, so this one is gone and the target
        // needs its own count/detail refreshed
        historyEntries.value.splice(idx, 1);
        const targetIdx = historyEntries.value.findIndex(
          (h) => h.id === updated.id,
        );
        if (targetIdx !== -1) historyEntries.value[targetIdx] = updated;
        else historyEntries.value.push(updated);
      }
    }
    editingId.value = null;
  } catch (err) {
    editError.value = err instanceof Error ? err.message : "Failed to save.";
  }
}
async function removeHistoryEntry(e: ActivityEntry) {
  const ok = await confirm({
    message: "Delete this history entry? This can't be undone.",
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await deleteActivityEntry(e.id);
    historyEntries.value = historyEntries.value.filter((h) => h.id !== e.id);
  } catch (err) {
    historyError.value =
      err instanceof Error ? err.message : "Failed to delete entry.";
  }
}

// ---- manually logging a new history entry ----
const showManualForm = ref(false);
const manualSearch = ref("");
const manualPicked = ref<PickableMedia | null>(null);
const manualEventType = ref<ActivityEventType>("episodes_watched");
const manualDate = ref(keyOfDate(new Date()));
const manualCount = ref(1);
const manualDetail = ref("");
const manualError = ref<string | null>(null);
const manualSaving = ref(false);

const EVENT_TYPE_LABELS: Record<ActivityEventType, string> = {
  episodes_watched: "Episodes watched",
  status_changed: "Status changed",
  rewatched: "Rewatched",
  rated: "Rated",
};

async function openManualForm(date?: string) {
  showManualForm.value = true;
  manualPicked.value = null;
  manualSearch.value = "";
  manualError.value = null;
  manualDate.value = date ?? keyOfDate(new Date());
  await loadManualLibrary();
}
function closeManualForm() {
  showManualForm.value = false;
}
function addEventForDrawerDay() {
  const key = drawerKey.value;
  closeDrawer();
  void openEventForm(key ?? undefined);
}
function logForDrawerDay() {
  const key = drawerKey.value ?? undefined;
  closeDrawer();
  openManualForm(key);
}
const manualSearchResults = computed(() => {
  const q = manualSearch.value.trim().toLowerCase();
  if (!q) return [];
  return manualLibrary.value
    .filter((m) => m.title.toLowerCase().includes(q))
    .slice(0, 8);
});
function pickManualMedia(m: PickableMedia) {
  manualPicked.value = m;
  manualSearch.value = m.title;
}
async function submitManualEntry() {
  if (manualSaving.value) return;
  if (!manualPicked.value) {
    manualError.value = "Pick a title first.";
    return;
  }
  manualSaving.value = true;
  manualError.value = null;
  try {
    const created = await createActivityEntry({
      mediaType: manualPicked.value.mediaType,
      mediaId: manualPicked.value.mediaId,
      eventType: manualEventType.value,
      eventDate: manualDate.value,
      count: manualCount.value,
      detail: manualDetail.value || null,
    });
    // Same upsert semantics as the backend's automatic logging — if a
    // bucket for this exact (media, event type, day) already existed,
    // `created` is that same row with the count bumped, not a new one.
    const idx = historyEntries.value.findIndex((h) => h.id === created.id);
    if (idx !== -1) historyEntries.value[idx] = created;
    else historyEntries.value.push(created);
    showManualForm.value = false;
  } catch (err) {
    manualError.value =
      err instanceof Error ? err.message : "Failed to log entry.";
  } finally {
    manualSaving.value = false;
  }
}
</script>

<template>
  <main class="ui-page">
    <AppTopBar>
      <SegmentedTabs
        :options="TAB_OPTIONS"
        :model-value="tab"
        aria-label="Calendar sections"
        @update:model-value="tab = $event as 'calendar' | 'history'"
      />
      <template #actions>
        <button
          v-if="tab === 'calendar'"
          type="button"
          class="ui-btn ui-btn-secondary"
          @click="openFeed"
        >
          Subscribe
        </button>
        <button
          v-if="tab === 'calendar'"
          type="button"
          class="ui-btn ui-btn-primary"
          @click="openEventForm()"
        >
          + Add Entry
        </button>
        <button
          type="button"
          class="ui-btn"
          :class="tab === 'calendar' ? 'ui-btn-secondary' : 'ui-btn-primary'"
          @click="openManualForm()"
        >
          + Log Watched
        </button>
      </template>
    </AppTopBar>

    <div class="ui-content medium">
      <div class="ui-head">
        <h1>Calendar</h1>
      </div>
      <template v-if="tab === 'calendar'">
        <div class="month-bar">
          <div v-if="calView === 'month'" class="month-nav">
            <button
              type="button"
              class="nav-btn"
              :disabled="!canGoPrev"
              @click="prevMonth"
            >
              ‹
            </button>
            <label class="month-label month-picker" title="Jump to a month">
              {{ MONTH_NAMES[viewMonth] }} {{ viewYear }}
              <input
                type="month"
                :value="jumpMonthValue"
                @change="jumpToMonth"
              />
            </label>
            <button
              type="button"
              class="nav-btn"
              :disabled="!canGoNext"
              @click="nextMonth"
            >
              ›
            </button>
          </div>
          <div v-else-if="calView === 'week'" class="month-nav">
            <button
              type="button"
              class="nav-btn"
              :disabled="!canWeekPrev"
              aria-label="Previous week"
              @click="shiftWeek(-1)"
            >
              ‹
            </button>
            <span class="month-label">{{ weekLabel }}</span>
            <button
              type="button"
              class="nav-btn"
              :disabled="!canWeekNext"
              aria-label="Next week"
              @click="shiftWeek(1)"
            >
              ›
            </button>
          </div>
          <div v-else class="month-nav">
            <span class="month-label agenda-label"
              >Next {{ CAL_MAX_DAYS }} days</span
            >
          </div>
          <div class="month-bar-actions">
            <SegmentedTabs
              :options="VIEW_OPTIONS"
              :model-value="calView"
              aria-label="Calendar view"
              @update:model-value="
                calView = $event as 'month' | 'week' | 'agenda'
              "
            />
            <button
              type="button"
              class="refresh-btn"
              :class="{ spinning: refreshing }"
              title="Refresh"
              :disabled="refreshing"
              @click="refreshAll"
            >
              <svg
                viewBox="0 0 24 24"
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M21 12a9 9 0 1 1-2.64-6.36" />
                <polyline points="21 4 21 10 15 10" />
              </svg>
            </button>
            <button
              type="button"
              class="ui-btn ui-btn-sm ui-btn-secondary"
              :class="{ 'is-hidden': calView === 'agenda' }"
              :aria-hidden="calView === 'agenda'"
              :tabindex="calView === 'agenda' ? -1 : undefined"
              :disabled="
                calView === 'agenda' ||
                (calView === 'month' ? isCurrentMonth : isCurrentWeek)
              "
              title="Jump to today (T)"
              @click="goToday"
            >
              Today
            </button>
          </div>
        </div>

        <div class="filter-row">
          <div class="filter-group">
            <button
              type="button"
              class="ui-chip"
              :class="{ on: filters.movie }"
              @click="filters.movie = !filters.movie"
            >
              Movies
            </button>
            <button
              type="button"
              class="ui-chip"
              :class="{ on: filters.tv }"
              @click="filters.tv = !filters.tv"
            >
              TV
            </button>
            <button
              type="button"
              class="ui-chip"
              :class="{ on: filters.anime }"
              @click="filters.anime = !filters.anime"
            >
              Anime
            </button>
            <button
              v-if="showGamesFilter"
              type="button"
              class="ui-chip"
              :class="{ on: filters.game }"
              @click="filters.game = !filters.game"
            >
              Games
            </button>
          </div>
          <div class="filter-group">
            <button
              type="button"
              class="ui-chip layer-episode"
              :class="{ on: filters.episode }"
              @click="filters.episode = !filters.episode"
            >
              <span class="swatch"></span>Airing
            </button>
            <button
              type="button"
              class="ui-chip layer-release"
              :class="{ on: filters.release }"
              @click="filters.release = !filters.release"
            >
              <span class="swatch"></span>Releases
            </button>
            <button
              type="button"
              class="ui-chip layer-watched"
              :class="{ on: filters.watched }"
              @click="filters.watched = !filters.watched"
            >
              <span class="swatch"></span>Watched
            </button>
            <button
              type="button"
              class="ui-chip layer-event"
              :class="{ on: filters.event }"
              title="Entries you added yourself"
              @click="filters.event = !filters.event"
            >
              <span class="swatch"></span>My entries
            </button>
            <button
              v-if="prefs.calendar_show_estimated"
              type="button"
              class="ui-chip layer-estimated"
              :class="{ on: filters.estimated }"
              title="Episodes projected from the weekly airing pattern, not confirmed dates"
              @click="filters.estimated = !filters.estimated"
            >
              <span class="swatch"></span>Estimated
            </button>
          </div>
          <div class="filter-group" role="group" aria-label="Airing shows">
            <span class="filter-caption">Airing shows</span>
            <button
              v-for="chip in AIRING_STATUS_CHIPS"
              :key="chip.key"
              type="button"
              class="ui-chip"
              :class="{ on: prefs.calendar_airing_statuses.includes(chip.key) }"
              :title="`Show airing episodes for titles on ${chip.label}`"
              @click="toggleAiringStatus(chip.key)"
            >
              {{ chip.label }}
            </button>
          </div>
        </div>

        <p v-if="calError" class="ui-state error">{{ calError }}</p>

        <template v-if="calView === 'month'">
          <div class="weekday-row">
            <span v-for="w in WEEKDAY_LABELS" :key="w">{{ w }}</span>
          </div>
          <div class="month-grid" :class="{ loading: calLoading }">
            <button
              v-for="cell in gridCells"
              :key="cell.key"
              type="button"
              class="day-cell"
              :class="{
                'out-of-month': !cell.inMonth,
                today: cell.isToday,
                past: cell.isPast,
              }"
              @click="openDrawer(cell)"
            >
              <span class="day-number">{{ cell.day }}</span>
              <span class="day-chips">
                <span
                  v-for="i in chipsFor(cell).shown"
                  :key="i.key"
                  class="chip"
                  :class="[`layer-${i.layer}`, { projected: i.projected }]"
                  :title="itemTooltip(i)"
                >
                  <img
                    v-if="i.posterUrl"
                    :src="i.posterUrl"
                    alt=""
                    loading="lazy"
                  />
                  <span v-else class="chip-fallback">{{
                    i.title.slice(0, 1)
                  }}</span>
                  <span v-if="i.badge" class="chip-badge">{{ i.badge }}</span>
                </span>
                <span v-if="chipsFor(cell).more" class="chip chip-more"
                  >+{{ chipsFor(cell).more }}</span
                >
              </span>
            </button>
          </div>
        </template>

        <template v-else-if="calView === 'week'">
          <div class="week-grid" :class="{ loading: calLoading }">
            <section
              v-for="d in weekDays"
              :key="d.key"
              class="week-day"
              :class="{ today: d.isToday, past: d.isPast }"
            >
              <header class="week-day-head">
                <span>{{ d.label }}</span>
                <button
                  type="button"
                  class="week-add"
                  title="Add an entry on this day"
                  @click="openEventForm(d.key)"
                >
                  +
                </button>
              </header>
              <p v-if="!d.items.length" class="week-empty">Nothing</p>
              <button
                v-for="i in d.items"
                :key="i.key"
                type="button"
                class="agenda-row"
                :class="[`layer-${i.layer}`, { projected: i.projected }]"
                :title="i.title"
                @click="activate(i)"
              >
                <span class="agenda-thumb">
                  <img
                    v-if="i.posterUrl"
                    :src="i.posterUrl"
                    alt=""
                    loading="lazy"
                  />
                </span>
                <span class="agenda-main">
                  <span class="agenda-title">{{ i.title }}</span>
                  <span class="agenda-detail">{{ i.detail }}</span>
                </span>
              </button>
            </section>
          </div>
        </template>

        <template v-else>
          <p v-if="!agendaGroups.length && !calLoading" class="ui-state">
            Nothing scheduled in the next {{ CAL_MAX_DAYS }} days with these
            filters.
          </p>
          <div v-else class="agenda">
            <div v-for="g in agendaGroups" :key="g.key" class="agenda-day">
              <div class="day-heading">{{ longDayLabel(g.key) }}</div>
              <button
                v-for="i in g.items"
                :key="i.key"
                type="button"
                class="agenda-row"
                :class="[`layer-${i.layer}`, { projected: i.projected }]"
                :title="i.title"
                @click="activate(i)"
              >
                <span class="agenda-thumb">
                  <img
                    v-if="i.posterUrl"
                    :src="i.posterUrl"
                    alt=""
                    loading="lazy"
                  />
                </span>
                <span class="agenda-main">
                  <span class="agenda-title">{{ i.title }}</span>
                  <span class="agenda-detail">{{ i.detail }}</span>
                </span>
                <span class="agenda-tag">{{ LAYER_LABEL[i.layer] }}</span>
              </button>
            </div>
          </div>
        </template>
      </template>

      <template v-else>
        <div class="history-filters">
          <input
            v-model="historySearch"
            type="text"
            class="ui-field history-search"
            placeholder="Search history…"
          />
          <select v-model="historyType" class="ui-field history-type">
            <option value="all">Everything</option>
            <option
              v-for="(label, key) in EVENT_TYPE_LABELS"
              :key="key"
              :value="key"
            >
              {{ label }}
            </option>
          </select>
        </div>
        <p v-if="historyLoading" class="ui-state">Loading…</p>
        <p v-else-if="historyError" class="ui-state error">
          {{ historyError }}
        </p>
        <p
          v-else-if="!groupedHistory.length && historyEntries.length"
          class="ui-state"
        >
          Nothing matches the search and filters.
        </p>
        <p v-else-if="!groupedHistory.length" class="ui-state">
          Nothing logged yet. Checking off episodes or changing a status will
          show up here.
        </p>
        <div v-else class="days">
          <div
            v-for="[key, dayEntries] in groupedHistory"
            :key="key"
            class="day-group"
          >
            <div class="day-heading">{{ historyDayLabel(key) }}</div>
            <template v-for="entry in dayEntries" :key="entry.id">
              <div v-if="editingId === entry.id" class="entry-edit-row">
                <div class="entry-edit-title-row">
                  <template v-if="editChangingMedia">
                    <div class="entry-edit-title-search">
                      <input
                        v-model="editMediaSearch"
                        type="text"
                        placeholder="Search your library…"
                        class="entry-edit-detail"
                        @input="editMediaPicked = null"
                      />
                      <div
                        v-if="editSearchResults.length"
                        class="modal-search-results"
                      >
                        <button
                          v-for="m in editSearchResults"
                          :key="`${m.mediaType}-${m.mediaId}`"
                          type="button"
                          class="modal-search-result"
                          @click="pickEditMedia(m)"
                        >
                          {{ m.title }}
                          <span class="modal-search-kind">{{
                            m.mediaType
                          }}</span>
                        </button>
                      </div>
                    </div>
                  </template>
                  <template v-else>
                    <span class="entry-edit-title">{{
                      editMediaPicked?.title
                    }}</span>
                    <button
                      type="button"
                      class="entry-change-title-btn"
                      @click="
                        editChangingMedia = true;
                        loadManualLibrary();
                      "
                    >
                      Change title
                    </button>
                  </template>
                </div>
                <div class="entry-edit-fields">
                  <select v-model="editEventType" class="entry-edit-type">
                    <option
                      v-for="(label, key) in EVENT_TYPE_LABELS"
                      :key="key"
                      :value="key"
                    >
                      {{ label }}
                    </option>
                  </select>
                  <input
                    v-model="editDate"
                    type="date"
                    class="entry-edit-date"
                  />
                  <input
                    v-model.number="editCount"
                    type="number"
                    min="1"
                    class="entry-edit-count"
                  />
                  <input
                    v-model="editDetail"
                    type="text"
                    placeholder="Note (optional)"
                    class="entry-edit-detail"
                  />
                </div>
                <p v-if="editError" class="ui-error-box">{{ editError }}</p>
                <div class="entry-edit-actions">
                  <button
                    type="button"
                    class="entry-save-btn"
                    @click="saveEdit(entry)"
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    class="entry-cancel-btn"
                    @click="cancelEdit"
                  >
                    Cancel
                  </button>
                </div>
              </div>
              <div
                v-else
                class="entry-row"
                :class="entry.eventType"
                @click="openHistoryEntry(entry)"
                @mouseleave="blurOnLeave"
              >
                <span class="entry-icon">{{
                  HISTORY_ICONS[entry.eventType]
                }}</span>
                <span class="entry-text">{{ describeActivity(entry) }}</span>
                <span class="entry-actions">
                  <button
                    type="button"
                    class="entry-action-btn"
                    title="Edit"
                    @click.stop="startEdit(entry)"
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    class="entry-action-btn"
                    title="Delete"
                    @click.stop="removeHistoryEntry(entry)"
                  >
                    ×
                  </button>
                </span>
              </div>
            </template>
          </div>
          <button
            v-if="hasOlderHistory"
            type="button"
            class="secondary-button older-btn"
            @click="historyWindowDays += 90"
          >
            Show Older
          </button>
        </div>
      </template>
    </div>

    <Teleport to="body">
      <div v-if="drawerKey" class="drawer-backdrop" @click.self="closeDrawer">
        <aside class="drawer" role="dialog" aria-label="Day details">
          <div class="drawer-head">
            <h3>{{ longDayLabel(drawerKey) }}</h3>
            <button
              type="button"
              class="drawer-close"
              title="Close"
              @click="closeDrawer"
            >
              ×
            </button>
          </div>
          <p v-if="!drawerItems.length" class="drawer-empty">
            Nothing on this day with the current filters.
          </p>
          <div v-else class="drawer-list">
            <button
              v-for="i in drawerItems"
              :key="i.key"
              type="button"
              class="agenda-row"
              :class="[`layer-${i.layer}`, { projected: i.projected }]"
              @click="activate(i)"
            >
              <span class="agenda-thumb">
                <img
                  v-if="i.posterUrl"
                  :src="i.posterUrl"
                  alt=""
                  loading="lazy"
                />
              </span>
              <span class="agenda-main">
                <span class="agenda-title">{{ i.title }}</span>
                <span class="agenda-detail">{{ i.detail }}</span>
              </span>
              <span class="agenda-tag">{{ LAYER_LABEL[i.layer] }}</span>
            </button>
          </div>
          <div class="drawer-foot">
            <button
              type="button"
              class="ui-btn ui-btn-primary"
              @click="addEventForDrawerDay"
            >
              Add an entry
            </button>
            <button
              type="button"
              class="ui-btn ui-btn-secondary"
              @click="logForDrawerDay"
            >
              Log something watched
            </button>
          </div>
        </aside>
      </div>
    </Teleport>

    <div v-if="showFeed" class="ui-backdrop" @click.self="showFeed = false">
      <div class="ui-modal" role="dialog" aria-modal="true">
        <h3>Subscribe in your calendar app</h3>
        <p class="modal-hint">
          Paste this link into Google Calendar (Other calendars, From URL),
          Apple Calendar or Outlook and every airing episode and release shows
          up there, kept up to date. Anyone with the link can see your schedule,
          so treat it like a password. The app has to be reachable from the
          internet for Google Calendar to fetch it.
        </p>
        <input
          class="ui-field"
          type="text"
          readonly
          :value="feedUrl"
          placeholder="Loading…"
          @focus="($event.target as HTMLInputElement).select()"
        />
        <p v-if="feedError" class="ui-error-box feed-error">{{ feedError }}</p>
        <div class="ui-modal-actions">
          <button
            type="button"
            class="ui-btn ui-btn-secondary"
            :disabled="feedBusy"
            @click="regenerateFeed"
          >
            New link
          </button>
          <button
            type="button"
            class="ui-btn ui-btn-primary"
            :disabled="!feedUrl"
            @click="copyFeed"
          >
            {{ feedCopied ? "Copied" : "Copy link" }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showEventForm" class="ui-backdrop" @click.self="closeEventForm">
      <div class="ui-modal" role="dialog" aria-modal="true">
        <h3>{{ eventId ? "Edit entry" : "Add a calendar entry" }}</h3>
        <p class="modal-hint">
          For anything the sources do not list: a premiere date, a watch party,
          a reminder. It only appears here and in your calendar feed.
        </p>
        <label class="modal-field">
          <span>Title</span>
          <input
            v-model="eventTitle"
            type="text"
            class="ui-field"
            maxlength="200"
            placeholder="e.g. Dune Part 3 premiere"
          />
        </label>
        <div class="modal-field-row">
          <label class="modal-field">
            <span>Date</span>
            <input v-model="eventDate" type="date" class="ui-field" />
          </label>
          <label class="modal-field">
            <span>Time (optional)</span>
            <input v-model="eventTime" type="time" class="ui-field" />
          </label>
        </div>
        <label class="modal-field">
          <span>Related title (optional)</span>
          <input
            v-model="eventLinkSearch"
            type="text"
            class="ui-field"
            placeholder="Search your library…"
            @input="eventLink = null"
          />
          <div v-if="eventLinkResults.length" class="modal-search-results">
            <button
              v-for="m in eventLinkResults"
              :key="`${m.mediaType}-${m.mediaId}`"
              type="button"
              class="modal-search-result"
              @click="pickEventLink(m)"
            >
              {{ m.title }}
              <span class="modal-search-kind">{{ m.mediaType }}</span>
            </button>
          </div>
        </label>
        <label class="modal-field">
          <span>Note (optional)</span>
          <input
            v-model="eventNote"
            type="text"
            class="ui-field"
            maxlength="2000"
          />
        </label>
        <p v-if="eventError" class="ui-error-box">{{ eventError }}</p>
        <div class="ui-modal-actions">
          <button
            v-if="eventId"
            type="button"
            class="ui-btn ui-btn-danger"
            @click="removeEvent"
          >
            Delete
          </button>
          <button
            v-if="eventLink"
            type="button"
            class="ui-btn ui-btn-secondary"
            @click="openLinkedTitle"
          >
            Open title
          </button>
          <button
            type="button"
            class="ui-btn ui-btn-secondary"
            @click="closeEventForm"
          >
            Cancel
          </button>
          <button
            type="button"
            class="ui-btn ui-btn-primary"
            :disabled="eventSaving"
            @click="saveEvent"
          >
            {{ eventSaving ? "Saving…" : "Save" }}
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="showManualForm"
      class="ui-backdrop"
      @click.self="closeManualForm"
    >
      <div class="ui-modal" role="dialog" aria-modal="true">
        <h3>Log a history entry</h3>
        <p class="modal-hint">
          For anything the app didn't catch automatically: watch history from
          before you added this title, or an import.
        </p>

        <label class="modal-field">
          <span>Title</span>
          <input
            v-model="manualSearch"
            type="text"
            placeholder="Search your library…"
            class="ui-field"
            @input="manualPicked = null"
          />
          <div
            v-if="manualSearchResults.length && !manualPicked"
            class="modal-search-results"
          >
            <button
              v-for="m in manualSearchResults"
              :key="`${m.mediaType}-${m.mediaId}`"
              type="button"
              class="modal-search-result"
              @click="pickManualMedia(m)"
            >
              {{ m.title }}
              <span class="modal-search-kind">{{ m.mediaType }}</span>
            </button>
          </div>
        </label>

        <label class="modal-field">
          <span>What happened</span>
          <select v-model="manualEventType" class="ui-field">
            <option
              v-for="(label, key) in EVENT_TYPE_LABELS"
              :key="key"
              :value="key"
            >
              {{ label }}
            </option>
          </select>
        </label>

        <div class="modal-field-row">
          <label class="modal-field">
            <span>Date</span>
            <input v-model="manualDate" type="date" class="ui-field" />
          </label>
          <label
            v-if="manualEventType === 'episodes_watched'"
            class="modal-field"
          >
            <span>Episodes</span>
            <input
              v-model.number="manualCount"
              type="number"
              min="1"
              class="ui-field"
            />
          </label>
        </div>

        <label class="modal-field">
          <span>Note (optional)</span>
          <input
            v-model="manualDetail"
            type="text"
            class="ui-field"
            placeholder="e.g. rewatched with friends"
          />
        </label>

        <p v-if="manualError" class="ui-error-box">{{ manualError }}</p>

        <div class="ui-modal-actions">
          <button
            type="button"
            class="ui-btn ui-btn-secondary"
            @click="closeManualForm"
          >
            Cancel
          </button>
          <button
            type="button"
            class="ui-btn ui-btn-primary"
            :disabled="manualSaving"
            @click="submitManualEntry"
          >
            {{ manualSaving ? "Logging…" : "Log entry" }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
/* month calendar grid */
.month-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 10px;
}
.month-nav {
  display: flex;
  align-items: center;
  gap: 14px;
}
.month-label {
  font-size: 1.1rem;
  font-weight: 700;
  min-width: 160px;
  text-align: center;
}
.nav-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #1a1a1a;
  border: 1px solid #2b2b2b;
  color: #eee;
  font-size: 1rem;
  cursor: pointer;
}
.nav-btn:hover:not(:disabled) {
  border-color: rgba(214, 138, 52, 0.4);
  color: #d68a34;
}
.nav-btn:disabled {
  opacity: 0.3;
  cursor: default;
}
/* Hidden, not removed, in Agenda so the view switcher beside it keeps its place */
.is-hidden {
  visibility: hidden;
}
.month-bar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.refresh-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid #2b2b2b;
  color: #ccc;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.refresh-btn:hover:not(:disabled) {
  border-color: rgba(214, 138, 52, 0.4);
  color: #d68a34;
}
.refresh-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
.refresh-btn.spinning svg {
  animation: refresh-spin 0.7s linear infinite;
}
@keyframes refresh-spin {
  to {
    transform: rotate(360deg);
  }
}
.month-picker {
  position: relative;
  cursor: pointer;
}
.month-picker input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
  width: 100%;
}
.agenda-label {
  min-width: 0;
  text-align: left;
}

/* filters */
.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 22px;
  margin-bottom: 16px;
}
.filter-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.filter-caption {
  font-size: 0.74rem;
  font-weight: 700;
  color: #9a9a9a;
  margin-right: 2px;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  border: 2px solid var(--layer, #888);
  box-sizing: border-box;
}
.ui-chip:not(.on) .swatch {
  opacity: 0.4;
}
.layer-episode {
  --layer: #d68a34;
}
.layer-release {
  --layer: #7ba7d9;
}
.layer-watched {
  --layer: #6fbf73;
}
.layer-event {
  --layer: #c084d9;
}
.layer-estimated {
  --layer: #d68a34;
}
.layer-estimated .swatch {
  border-style: dashed;
}

/* month grid: minmax(0, 1fr) is what stops long content from stretching
   a column, and cells have a fixed height so a busy day can't make its
   whole row taller than the rest */
.weekday-row {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
  margin-bottom: 6px;
}
.weekday-row span {
  text-align: center;
  font-size: 0.72rem;
  font-weight: 700;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.month-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  grid-auto-rows: 112px;
  gap: 6px;
  transition: opacity 0.15s ease;
}
.month-grid.loading {
  opacity: 0.5;
}
.day-cell {
  min-width: 0;
  overflow: hidden;
  background: #171717;
  border: 1px solid #202020;
  border-radius: 8px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
  font-family: inherit;
  color: inherit;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}
.day-cell:hover {
  border-color: rgba(214, 138, 52, 0.45);
  background: #1b1b1b;
}
.day-cell:focus-visible {
  outline: 2px solid #d68a34;
  outline-offset: 1px;
}
.day-cell.out-of-month {
  opacity: 0.35;
}
.day-cell.today {
  border-color: rgba(214, 138, 52, 0.55);
  background: rgba(214, 138, 52, 0.07);
}
.day-number {
  font-size: 0.74rem;
  font-weight: 700;
  color: #9c9c9c;
  font-variant-numeric: tabular-nums;
}
.day-cell.today .day-number {
  color: #d68a34;
}
.day-chips {
  display: flex;
  flex-wrap: wrap;
  align-content: flex-start;
  gap: 3px;
  min-width: 0;
}
.chip {
  position: relative;
  width: 27px;
  height: 39px;
  border-radius: 4px;
  overflow: hidden;
  flex-shrink: 0;
  background: #262626;
  border: 2px solid var(--layer, #888);
  box-sizing: border-box;
}
.chip img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.chip-fallback {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 700;
  color: #9c9c9c;
}
.chip.projected {
  border-style: dashed;
  opacity: 0.75;
}
.chip-badge {
  position: absolute;
  right: 0;
  bottom: 0;
  min-width: 12px;
  padding: 0 2px;
  background: rgba(0, 0, 0, 0.82);
  color: #fff;
  font-size: 0.58rem;
  font-weight: 800;
  line-height: 13px;
  text-align: center;
  border-top-left-radius: 3px;
  font-variant-numeric: tabular-nums;
}
.chip-more {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #333;
  background: transparent;
  color: #9c9c9c;
  font-size: 0.68rem;
  font-weight: 700;
}

/* agenda + day drawer rows */
.agenda {
  display: flex;
  flex-direction: column;
  gap: 22px;
}
.agenda-day .day-heading {
  margin-bottom: 8px;
}
.agenda-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  box-sizing: border-box;
  background: #171717;
  border: 1px solid #202020;
  border-left: 3px solid var(--layer, #888);
  border-radius: 10px;
  padding: 8px 12px 8px 8px;
  margin-bottom: 6px;
  text-align: left;
  color: #ddd;
  font-family: inherit;
  cursor: pointer;
  transition:
    background 0.15s ease,
    border-color 0.15s ease;
}
.agenda-row:hover {
  background: #1c1c1c;
  border-color: rgba(214, 138, 52, 0.4);
  border-left-color: var(--layer, #888);
}
.agenda-row.projected {
  border-left-style: dashed;
}
.agenda-thumb {
  width: 34px;
  height: 50px;
  border-radius: 4px;
  overflow: hidden;
  background: #262626;
  flex-shrink: 0;
}
.agenda-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.agenda-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}
.agenda-title {
  font-size: 0.86rem;
  font-weight: 700;
  color: #fff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agenda-detail {
  font-size: 0.75rem;
  color: #9c9c9c;
}
.agenda-tag {
  font-size: 0.66rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--layer, #888);
  flex-shrink: 0;
}

.drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--ui-z-drawer);
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  justify-content: flex-end;
}
.drawer {
  width: min(400px, 100%);
  height: 100%;
  box-sizing: border-box;
  background: #141414;
  border-left: 1px solid #262626;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  color: #fff;
  box-shadow: -24px 0 64px rgba(0, 0, 0, 0.5);
}
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.drawer-head h3 {
  margin: 0;
  font-size: 1.05rem;
}
.drawer-close {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid #2b2b2b;
  background: rgba(255, 255, 255, 0.06);
  color: #ccc;
  font-size: 1.1rem;
  cursor: pointer;
}
.drawer-empty {
  color: #9c9c9c;
  font-size: 0.84rem;
}
.drawer-list {
  flex: 1;
}
.drawer-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  border-top: 1px solid #202020;
  padding-top: 14px;
}

.history-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.history-search {
  flex: 1;
  min-width: 180px;
}
.older-btn {
  align-self: center;
}
.feed-error {
  margin-top: 10px;
}

/* history list */
.days {
  display: flex;
  flex-direction: column;
  gap: 26px;
  margin-top: 8px;
}
.day-heading {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 700;
  color: #d68a34;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid #202020;
}
.entry-row {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #171717;
  border: 1px solid #202020;
  border-left: 3px solid #3a3a3a;
  border-radius: 10px;
  padding: 11px 14px;
  margin-bottom: 8px;
  font-size: 0.86rem;
  color: #ddd;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    transform 0.1s ease;
}
.entry-row:hover {
  border-color: rgba(214, 138, 52, 0.4);
  border-left-color: #d68a34;
  background: #1c1c1c;
  transform: translateX(2px);
}
.entry-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
  font-size: 0.78rem;
  flex-shrink: 0;
}
.entry-row.episodes_watched {
  border-left-color: #6fbf73;
}
.entry-row.episodes_watched .entry-icon {
  color: #6fbf73;
  background: rgba(111, 191, 115, 0.14);
}
.entry-row.status_changed {
  border-left-color: #7ba7d9;
}
.entry-row.status_changed .entry-icon {
  color: #7ba7d9;
  background: rgba(123, 167, 217, 0.14);
}
.entry-row.rewatched {
  border-left-color: #d68a34;
}
.entry-row.rewatched .entry-icon {
  color: #d68a34;
  background: rgba(214, 138, 52, 0.14);
}
.entry-row.rated {
  border-left-color: #d9c86f;
}
.entry-row.rated .entry-icon {
  color: #d9c86f;
  background: rgba(217, 200, 111, 0.14);
}
.entry-text {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.entry-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s ease;
  flex-shrink: 0;
}
.entry-row:hover .entry-actions,
.entry-row:focus-within .entry-actions {
  opacity: 1;
}
/* touch screens have no hover, so the buttons must always show */
@media (hover: none) {
  .entry-actions {
    opacity: 1;
  }
}
.entry-action-btn {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid #2b2b2b;
  color: #ccc;
  border-radius: 6px;
  width: 24px;
  height: 24px;
  font-size: 0.78rem;
  cursor: pointer;
  font-family: inherit;
}
.entry-action-btn:hover {
  border-color: rgba(214, 138, 52, 0.4);
  color: #d68a34;
}

/* history inline edit row */
.entry-edit-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #171717;
  border: 1px solid rgba(214, 138, 52, 0.4);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
}
.entry-edit-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.entry-edit-title {
  font-weight: 700;
  font-size: 0.86rem;
  color: #fff;
}
.entry-edit-title-search {
  position: relative;
  flex: 1;
}
.entry-change-title-btn {
  background: none;
  border: none;
  color: #d68a34;
  font-size: 0.74rem;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
  padding: 0;
}
.entry-edit-fields {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.entry-edit-type {
  background: #0d0d0d;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #eee;
  padding: 6px 8px;
  font-size: 0.8rem;
  font-family: inherit;
}
.entry-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.entry-edit-date,
.entry-edit-count,
.entry-edit-detail {
  background: #0d0d0d;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #eee;
  padding: 6px 8px;
  font-size: 0.8rem;
  font-family: inherit;
}
.entry-edit-count {
  width: 64px;
}
.entry-edit-detail {
  flex: 1;
  min-width: 120px;
}
.entry-save-btn,
.entry-cancel-btn {
  border: none;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
}
.entry-save-btn {
  background: #d68a34;
  color: #14100a;
}
.entry-cancel-btn {
  background: rgba(255, 255, 255, 0.08);
  color: #ccc;
}

/* manual log-entry modal */
.modal-hint {
  color: #9c9c9c;
  font-size: 0.78rem;
  margin: 0 0 16px;
  line-height: 1.5;
}
.modal-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.82rem;
  color: #ccc;
  margin-bottom: 14px;
  position: relative;
}
.modal-field-row {
  display: flex;
  gap: 12px;
}
.modal-field-row .modal-field {
  flex: 1;
}
.modal-search-results {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 10;
  background: #171717;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  margin-top: 4px;
  max-height: 200px;
  overflow-y: auto;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
}
.modal-search-result {
  display: flex;
  justify-content: space-between;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  color: #ddd;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 0.82rem;
  font-family: inherit;
}
.modal-search-result:hover {
  background: rgba(255, 255, 255, 0.06);
}
.modal-search-kind {
  color: #666;
  font-size: 0.7rem;
  text-transform: uppercase;
}

/* week view: seven day columns, one per day, stacking on a phone */
.week-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}
.week-grid.loading {
  opacity: 0.6;
}
.week-day {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #171717;
  border: 1px solid #202020;
  border-radius: 8px;
  padding: 8px;
}
.week-day.today {
  border-color: rgba(214, 138, 52, 0.55);
  background: rgba(214, 138, 52, 0.07);
}
.week-day.past {
  opacity: 0.75;
}
.week-day-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.76rem;
  font-weight: 700;
  color: #ccc;
}
.week-add {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: 1px solid #2b2b2b;
  background: transparent;
  color: #999;
  cursor: pointer;
}
.week-add:hover {
  color: #d68a34;
  border-color: rgba(214, 138, 52, 0.4);
}
.week-empty {
  margin: 0;
  font-size: 0.72rem;
  color: #8a8a8a;
}
/* a day column is narrow: drop the poster so the title can wrap */
.week-day .agenda-row {
  padding: 6px 8px;
  gap: 8px;
}
.week-day .agenda-thumb {
  display: none;
}
.week-day .agenda-title {
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
}

@media (max-width: 720px) {
  .week-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .week-day .agenda-thumb {
    display: block;
  }
  .month-grid {
    gap: 3px;
    grid-auto-rows: 70px;
  }
  .weekday-row {
    gap: 3px;
  }
  .day-cell {
    padding: 3px;
    border-radius: 6px;
  }
  .day-number {
    font-size: 0.66rem;
  }
  .day-chips {
    gap: 2px;
  }
  .chip {
    width: 17px;
    height: 25px;
    border-width: 1.5px;
    border-radius: 3px;
  }
  .chip-badge {
    display: none;
  }
  .month-label {
    min-width: 0;
  }
  .drawer {
    width: 100%;
  }
  .agenda-row {
    padding-right: 8px;
  }
  .agenda-tag {
    display: none;
  }
}
</style>

.month-picker input { font-family: inherit; }
