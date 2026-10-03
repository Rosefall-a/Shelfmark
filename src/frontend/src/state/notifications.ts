// A lightweight notification center, computed live from data the app
// already fetches (bounties), not a persisted/dismissible-per-item store.
// Recomputed fresh each time the sidebar is opened, the same way Home
// Hub's "backlog nudge"/"on this day" widgets are computed live rather
// than tracked as durable state. Deliberately doesn't cover "recently
// unlocked achievements", there's no cheap way to get that across the
// whole library without a new backend aggregate (fetchAchievementsSummary
// only returns counts, not unlock timestamps), so it's left out rather
// than faked.
import { ref } from "vue";
import { fetchBounties } from "../services/bounties";
import type { Bounty } from "../services/bounties";
import {
  fetchMediaNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "../services/notifications";
import type { MediaNotification } from "../services/notifications";

export interface Notification {
  id: string;
  kind: "deadline" | "suggested";
  title: string;
  detail: string;
  to: string;
}

const DEADLINE_WINDOW_SECONDS = 7 * 86_400;
const SUGGESTED_WINDOW_SECONDS = 7 * 86_400;

export const notifications = ref<Notification[]>([]);
export const notificationsLoaded = ref(false);

// Episode/season/movie notifications from the server. Kept separate from
// the bounty ones above because they persist and can be read/unread.
export const mediaNotifications = ref<MediaNotification[]>([]);
export const mediaUnread = ref(0);

export async function refreshMediaNotifications() {
  try {
    const res = await fetchMediaNotifications();
    mediaNotifications.value = res.items;
    mediaUnread.value = res.unread;
  } catch {
    // the badge simply doesn't change this tick
  }
}

export async function readMediaNotification(id: string) {
  const n = mediaNotifications.value.find((m) => m.id === id);
  if (!n || n.read) return;
  n.read = true;
  mediaUnread.value = Math.max(0, mediaUnread.value - 1);
  try {
    await markNotificationRead(id);
  } catch {
    n.read = false;
    mediaUnread.value += 1;
  }
}

export async function readAllMediaNotifications() {
  const before = mediaNotifications.value.map((n) => n.read);
  mediaNotifications.value.forEach((n) => (n.read = true));
  const unread = mediaUnread.value;
  mediaUnread.value = 0;
  try {
    await markAllNotificationsRead();
  } catch {
    mediaNotifications.value.forEach((n, i) => (n.read = before[i]));
    mediaUnread.value = unread;
  }
}

export function mediaNotificationRoute(n: MediaNotification): string {
  const base =
    n.mediaType === "movie"
      ? "/movies"
      : n.mediaType === "tv"
        ? "/tv"
        : "/anime";
  return `${base}/${n.mediaId}`;
}

export async function refreshNotifications() {
  let bounties: Bounty[];
  try {
    bounties = await fetchBounties({ status: "active" });
  } catch {
    notificationsLoaded.value = true;
    return;
  }

  const now = Date.now() / 1000;
  const out: Notification[] = [];

  for (const b of bounties) {
    if (
      b.target_date !== null &&
      b.target_date - now <= DEADLINE_WINDOW_SECONDS
    ) {
      const daysLeft = Math.ceil((b.target_date - now) / 86_400);
      out.push({
        id: "deadline:" + b.id,
        kind: "deadline",
        title: b.title,
        detail:
          daysLeft < 0
            ? `Overdue by ${Math.abs(daysLeft)} day${Math.abs(daysLeft) === 1 ? "" : "s"}`
            : daysLeft === 0
              ? "Due today"
              : `Due in ${daysLeft} day${daysLeft === 1 ? "" : "s"}`,
        to: "/bounties",
      });
    }
    if (b.auto_generated && now - b.created_at <= SUGGESTED_WINDOW_SECONDS) {
      out.push({
        id: "suggested:" + b.id,
        kind: "suggested",
        title: b.title,
        detail: "Suggested for you",
        to: "/bounties",
      });
    }
  }

  // deadlines first, a bounty overdue or due soon matters more than a
  // still-fresh suggestion
  out.sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "deadline" ? -1 : 1));
  notifications.value = out;
  notificationsLoaded.value = true;
}
