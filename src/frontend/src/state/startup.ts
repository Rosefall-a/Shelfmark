import { ref } from "vue";

export type StartupState =
  | "checking"
  | "unavailable"
  | "setup-required"
  | "auth-required"
  | "ready";

export const startupState = ref<StartupState>("checking");
export const startupError = ref<string | null>(null);

const RETURN_PATH_KEY = "unnamedTracking.startupReturnPath";

export function setStartupState(state: StartupState, error: string | null = null) {
  startupState.value = state;
  startupError.value = error;
}

export function safeReturnPath(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//")
  ) {
    return null;
  }

  try {
    const url = new URL(value, "https://unnamed-tracking.invalid");
    if (url.origin !== "https://unnamed-tracking.invalid") return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}

export function rememberReturnPath(value: unknown): string | null {
  const path = safeReturnPath(value);
  if (!path) return null;

  try {
    sessionStorage.setItem(RETURN_PATH_KEY, path);
  } catch {
    // Storage may be unavailable; the query-string path remains sufficient.
  }
  return path;
}

export function consumeReturnPath(queryValue: unknown): string | null {
  const queryPath = safeReturnPath(queryValue);
  if (queryPath) {
    try {
      sessionStorage.removeItem(RETURN_PATH_KEY);
    } catch {
      // Ignore storage failures.
    }
    return queryPath;
  }

  try {
    const storedPath = safeReturnPath(sessionStorage.getItem(RETURN_PATH_KEY));
    if (storedPath) sessionStorage.removeItem(RETURN_PATH_KEY);
    return storedPath;
  } catch {
    return null;
  }
}

export function classifySetupStatus(status: { setup_required: boolean }): StartupState {
  return status.setup_required ? "setup-required" : "ready";
}
