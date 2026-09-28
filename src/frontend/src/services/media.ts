import { createSpeedTracker } from "../utils/uploadSpeed";

export type MediaKind = "screenshot" | "clip" | "soundtrack";

export interface MediaItem {
  id: string;
  filename: string;
  kind: MediaKind;
  url: string;
  tags: string[];
  note: string | null;
  linked_achievement_id: string | null;
  // which GameProfile (e.g. an OSRS account) this belongs to, if any
  profile_id: string | null;
  created_at: number;
  // present only from the library-wide gallery endpoint (fetchAllMedia),
  // not from a single game's own screenshots list
  game_id?: string;
  game_title?: string;
}

export interface MediaItemUpdate {
  filename?: string;
  tags?: string[];
  note?: string | null;
  linked_achievement_id?: string | null;
  profile_id?: string | null;
}

export interface UploadResult {
  filename: string;
  status: "saved" | "rejected";
  kind?: MediaKind;
  reason?: string;
}

// XMLHttpRequest, not fetch, fetch has no upload-progress event at all, so
// a multi-file batch upload's progress bar was purely cosmetic (jumping
// straight from 0 to 100 when the single request finally resolved). XHR's
// upload.onprogress gives real byte-level progress against the actual
// upload, which can be the slow part for screenshots/clips.
function uploadFiles(
  url: string,
  files: File[],
  onProgress?: (fraction: number, speedLabel?: string) => void,
  extraFields?: Record<string, string>,
): Promise<UploadResult[]> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  for (const [key, value] of Object.entries(extraFields ?? {}))
    form.append(key, value);
  const trackSpeed = createSpeedTracker();

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress)
        onProgress(e.loaded / e.total, trackSpeed(e.loaded, e.total));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText).results);
        } catch {
          reject(
            new Error("Upload succeeded but the response could not be parsed."),
          );
        }
      } else {
        reject(
          new Error(
            `Upload failed: ${xhr.status} ${xhr.statusText} ${xhr.responseText}`,
          ),
        );
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed: network error."));
    xhr.send(form);
  });
}

export async function uploadGameScreenshots(
  gameId: string,
  files: File[],
  onProgress?: (fraction: number, speedLabel?: string) => void,
  profileId?: string | null,
): Promise<UploadResult[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return files.map((f) => ({
      filename: f.name,
      status: "saved",
      kind: f.type.startsWith("video/") ? "clip" : "screenshot",
    }));
  }
  return uploadFiles(
    `/api/game/${gameId}/screenshots`,
    files,
    onProgress,
    profileId ? { profile_id: profileId } : undefined,
  );
}

// unscopedOnly, when true and no profileId, restricts to items with no
// account tag at all (used by the Accounts tab's "General" entry) rather
// than every item regardless of account (used by the plain Screenshots/
// Clips/Soundtrack tabs, which have no account concept of their own)
export async function listGameScreenshots(
  gameId: string,
  profileId?: string | null,
  unscopedOnly = false,
): Promise<MediaItem[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const params = new URLSearchParams();
  if (profileId) params.set("profile_id", profileId);
  else if (unscopedOnly) params.set("unscoped_only", "true");
  const query = params.toString();
  const response = await fetch(
    `/api/game/${gameId}/screenshots${query ? `?${query}` : ""}`,
    { credentials: "include" },
  );
  if (!response.ok)
    throw new Error(
      `Failed to list media: ${response.status} ${response.statusText}`,
    );
  const body = await response.json();
  return body.media;
}

// soft-delete, moves to trash, restorable for 7 days (see below)
export async function deleteGameScreenshot(
  gameId: string,
  kind: MediaKind,
  filename: string,
): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return;
  const response = await fetch(
    `/api/game/${gameId}/screenshots/${kind}/${encodeURIComponent(filename)}`,
    {
      method: "DELETE",
      credentials: "include",
    },
  );
  if (!response.ok)
    throw new Error(
      `Failed to delete media: ${response.status} ${response.statusText}`,
    );
}

export interface TrashedMediaItem extends MediaItem {
  deleted_at: number;
  purge_at: number;
}

export async function fetchGameMediaTrash(
  gameId: string,
): Promise<TrashedMediaItem[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const response = await fetch(`/api/game/${gameId}/screenshots/trash`, {
    credentials: "include",
  });
  if (!response.ok)
    throw new Error(
      `Failed to fetch media trash: ${response.status} ${response.statusText}`,
    );
  const body = await response.json();
  return body.media;
}

export async function restoreGameMedia(
  gameId: string,
  kind: MediaKind,
  filename: string,
): Promise<void> {
  const response = await fetch(
    `/api/game/${gameId}/screenshots/${kind}/${encodeURIComponent(filename)}/restore`,
    {
      method: "POST",
      credentials: "include",
    },
  );
  if (!response.ok)
    throw new Error(
      `Failed to restore media: ${response.status} ${response.statusText}`,
    );
}

export async function updateMediaItem(
  gameId: string,
  mediaId: string,
  payload: MediaItemUpdate,
): Promise<MediaItem> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return {
      id: mediaId,
      filename: "",
      kind: "screenshot",
      url: "",
      tags: payload.tags ?? [],
      note: payload.note ?? null,
      linked_achievement_id: payload.linked_achievement_id ?? null,
      profile_id: payload.profile_id ?? null,
      created_at: 0,
    };
  }
  const response = await fetch(`/api/game/${gameId}/screenshots/${mediaId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to update media item: ${response.status} ${response.statusText} ${message}`,
    );
  }
  return await response.json();
}

// library-wide gallery, every already-assigned media item across every
// game, optionally filtered
export async function fetchAllMedia(
  filters: { kind?: MediaKind; tag?: string; gameId?: string } = {},
): Promise<MediaItem[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const params = new URLSearchParams();
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.tag) params.set("tag", filters.tag);
  if (filters.gameId) params.set("game_id", filters.gameId);
  const response = await fetch(`/api/media?${params.toString()}`, {
    credentials: "include",
  });
  if (!response.ok)
    throw new Error(
      `Failed to fetch media: ${response.status} ${response.statusText}`,
    );
  return await response.json();
}

// distinct from MediaItem, an inbox item has no id/tags/note (those only
// exist once it's assigned to a game and becomes a real MediaItem row)
export interface InboxMediaItem {
  filename: string;
  kind: MediaKind;
  url: string;
  created_at: number;
}

export interface TrashedInboxItem {
  filename: string;
  kind: MediaKind;
  created_at: number;
  deleted_at: number;
  purge_at: number;
}

export async function uploadToInbox(
  files: File[],
  onProgress?: (fraction: number, speedLabel?: string) => void,
): Promise<UploadResult[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return files.map((f) => ({
      filename: f.name,
      status: "saved",
      kind: f.type.startsWith("video/") ? "clip" : "screenshot",
    }));
  }
  return uploadFiles("/api/media/inbox", files, onProgress);
}

export async function listInbox(): Promise<InboxMediaItem[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const response = await fetch("/api/media/inbox", { credentials: "include" });
  if (!response.ok)
    throw new Error(
      `Failed to list inbox: ${response.status} ${response.statusText}`,
    );
  const body = await response.json();
  return body.media;
}

export async function fetchInboxTrash(): Promise<TrashedInboxItem[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const response = await fetch("/api/media/inbox/trash", {
    credentials: "include",
  });
  if (!response.ok)
    throw new Error(
      `Failed to fetch inbox trash: ${response.status} ${response.statusText}`,
    );
  const body = await response.json();
  return body.media;
}

// soft-delete, moves to trash, restorable for 7 days (see restoreInboxMedia)
export async function deleteInboxMedia(
  kind: MediaKind,
  filename: string,
): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return;
  const response = await fetch(
    `/api/media/inbox/${kind}/${encodeURIComponent(filename)}`,
    {
      method: "DELETE",
      credentials: "include",
    },
  );
  if (!response.ok)
    throw new Error(
      `Failed to delete media: ${response.status} ${response.statusText}`,
    );
}

export async function restoreInboxMedia(
  kind: MediaKind,
  filename: string,
): Promise<void> {
  const response = await fetch(
    `/api/media/inbox/${kind}/${encodeURIComponent(filename)}/restore`,
    {
      method: "POST",
      credentials: "include",
    },
  );
  if (!response.ok)
    throw new Error(
      `Failed to restore media: ${response.status} ${response.statusText}`,
    );
}

export async function assignInboxMedia(
  kind: MediaKind,
  filename: string,
  gameId: string,
): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return;
  const response = await fetch(
    `/api/media/inbox/${kind}/${encodeURIComponent(filename)}/assign`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ game_id: gameId }),
    },
  );
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to assign media: ${response.status} ${response.statusText} ${message}`,
    );
  }
}

// --- Saves / Docs / World Saves / Modpacks: generic file attachments,
// any file type -------------------------------------------------------------
export type GameFileKind = "save" | "doc" | "world_save" | "modpack";

export interface GameFile {
  filename: string;
  size: number;
  url: string;
}

export async function renameGameFile(gameId: string, kind: GameFileKind, filename: string, name: string): Promise<GameFile> {
  const response = await fetch(`/api/game/${gameId}/files/${kind}/${encodeURIComponent(filename)}/rename`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ name }),
  });
  if (!response.ok) throw new Error(`Failed to rename file: ${response.status} ${response.statusText} ${await response.text()}`);
  return await response.json();
}

export async function uploadGameFiles(
  gameId: string,
  kind: GameFileKind,
  files: File[],
  onProgress?: (fraction: number, speedLabel?: string) => void,
): Promise<UploadResult[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") {
    return files.map((f) => ({ filename: f.name, status: "saved" }));
  }
  return uploadFiles(`/api/game/${gameId}/files/${kind}`, files, onProgress);
}

export async function listGameFiles(
  gameId: string,
  kind: GameFileKind,
): Promise<GameFile[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const response = await fetch(`/api/game/${gameId}/files/${kind}`, {
    credentials: "include",
  });
  if (!response.ok)
    throw new Error(
      `Failed to list files: ${response.status} ${response.statusText}`,
    );
  const body = await response.json();
  return body.files;
}

// soft-delete, moves to trash, restorable for 7 days (see below)
export async function deleteGameFile(
  gameId: string,
  kind: GameFileKind,
  filename: string,
): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return;
  const response = await fetch(
    `/api/game/${gameId}/files/${kind}/${encodeURIComponent(filename)}`,
    {
      method: "DELETE",
      credentials: "include",
    },
  );
  if (!response.ok)
    throw new Error(
      `Failed to delete file: ${response.status} ${response.statusText}`,
    );
}

export interface TrashedGameFile {
  filename: string;
  deleted_at: number;
  purge_at: number;
}

export async function fetchGameFileTrash(
  gameId: string,
  kind: GameFileKind,
): Promise<TrashedGameFile[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const response = await fetch(`/api/game/${gameId}/files/${kind}/trash`, {
    credentials: "include",
  });
  if (!response.ok)
    throw new Error(
      `Failed to fetch file trash: ${response.status} ${response.statusText}`,
    );
  const body = await response.json();
  return body.files;
}

export async function restoreGameFile(
  gameId: string,
  kind: GameFileKind,
  filename: string,
): Promise<void> {
  const response = await fetch(
    `/api/game/${gameId}/files/${kind}/${encodeURIComponent(filename)}/restore`,
    {
      method: "POST",
      credentials: "include",
    },
  );
  if (!response.ok)
    throw new Error(
      `Failed to restore file: ${response.status} ${response.statusText}`,
    );
}
