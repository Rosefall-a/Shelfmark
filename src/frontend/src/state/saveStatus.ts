import { ref } from "vue";

export type SaveState = "idle" | "saving" | "saved" | "error";

export const saveState = ref<SaveState>("idle");
export const savedAt = ref<number | null>(null);

let pending = 0;
let originalFetch: typeof window.fetch | null = null;

function isWrite(method: string | undefined): boolean {
  const m = (method ?? "GET").toUpperCase();
  return m === "POST" || m === "PUT" || m === "PATCH" || m === "DELETE";
}

// While the Settings page is open, every write to /api shows up in one
// "Saving… / Saved / Couldn't save" indicator. Watching fetch here means
// all of Settings' sections report their saves without each one having to
// be wired up individually, and it's removed again when the page closes.
export function startTrackingSaves() {
  if (originalFetch) return;
  originalFetch = window.fetch.bind(window);
  const real = originalFetch;
  window.fetch = async (input, init) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const method =
      init?.method ?? (input instanceof Request ? input.method : "GET");
    const tracked = url.startsWith("/api/") && isWrite(method);
    if (!tracked) return real(input, init);
    pending += 1;
    saveState.value = "saving";
    try {
      const response = await real(input, init);
      pending -= 1;
      if (!response.ok) saveState.value = "error";
      else if (pending === 0) {
        saveState.value = "saved";
        savedAt.value = Date.now();
      }
      return response;
    } catch (err) {
      pending -= 1;
      saveState.value = "error";
      throw err;
    }
  };
}

export function stopTrackingSaves() {
  if (!originalFetch) return;
  window.fetch = originalFetch;
  originalFetch = null;
  pending = 0;
  saveState.value = "idle";
  savedAt.value = null;
}
