// Media notifications from the server: episode aired, season started
// airing, new season listed for something you finished, movie released.
// The server builds them from exact air times when this is asked for, so
// polling this is what makes them appear.

export type MediaNotificationKind =
  "episode_aired" | "season_started" | "sequel_announced" | "movie_released";

export interface MediaNotification {
  id: string;
  kind: MediaNotificationKind;
  mediaType: "movie" | "tv" | "anime";
  mediaId: string;
  title: string;
  body: string;
  posterUrl: string | null;
  eventAt: number;
  read: boolean;
}

interface BackendNotification {
  id: string;
  kind: MediaNotificationKind;
  media_type: "movie" | "tv" | "anime";
  media_id: string;
  title: string;
  body: string;
  poster_url: string | null;
  event_at: number;
  read: boolean;
}

async function ok(response: Response, action: string): Promise<Response> {
  if (!response.ok) throw new Error(`Failed to ${action}: ${response.status}`);
  return response;
}

export async function fetchMediaNotifications(
  limit = 50,
): Promise<{ items: MediaNotification[]; unread: number }> {
  const response = await ok(
    await fetch(`/api/notifications?limit=${limit}`, {
      credentials: "include",
    }),
    "load notifications",
  );
  const raw = (await response.json()) as {
    items: BackendNotification[];
    unread: number;
  };
  return {
    unread: raw.unread,
    items: raw.items.map((n) => ({
      id: n.id,
      kind: n.kind,
      mediaType: n.media_type,
      mediaId: n.media_id,
      title: n.title,
      body: n.body,
      posterUrl: n.poster_url,
      eventAt: n.event_at,
      read: n.read,
    })),
  };
}

export async function createTestNotification(payload: {
  kind: MediaNotificationKind;
  mediaType: "movie" | "tv" | "anime";
  title: string;
  body: string;
}): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return;
  }

  await ok(
    await fetch("/api/notifications/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        kind: payload.kind,
        media_type: payload.mediaType,
        title: payload.title,
        body: payload.body,
      }),
    }),
    "create a test notification",
  );
}

// Admin-only: runs the same generation the bell's poll triggers, on
// demand, so a just-edited air date doesn't need a poll cycle to show up.
export async function regenerateNotifications(): Promise<{ created: number }> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return { created: 0 };
  }

  const response = await ok(
    await fetch("/api/notifications/regenerate", {
      method: "POST",
      credentials: "include",
    }),
    "regenerate notifications",
  );
  return await response.json();
}

export async function markNotificationRead(id: string): Promise<void> {
  await ok(
    await fetch(`/api/notifications/${id}/read`, {
      method: "POST",
      credentials: "include",
    }),
    "mark notification read",
  );
}

export async function markNotificationUnread(id: string): Promise<void> {
  await ok(
    await fetch(`/api/notifications/${id}/unread`, {
      method: "POST",
      credentials: "include",
    }),
    "mark notification unread",
  );
}

export async function markAllNotificationsRead(): Promise<void> {
  await ok(
    await fetch("/api/notifications/read-all", {
      method: "POST",
      credentials: "include",
    }),
    "mark notifications read",
  );
}

export async function deleteMediaNotification(id: string): Promise<void> {
  await ok(
    await fetch(`/api/notifications/${id}`, {
      method: "DELETE",
      credentials: "include",
    }),
    "delete notification",
  );
}
