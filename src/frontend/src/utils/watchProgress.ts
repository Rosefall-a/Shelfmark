// Where you left off in a movie (#191), entered and shown as h:mm.

// "1:12" or "72" -> 72 minutes; blank -> null; anything else -> NaN
export function parseProgressMinutes(value: string): number | null {
  const text = value.trim();
  if (!text) return null;
  const clock = /^(\d+):([0-5]?\d)$/.exec(text);
  if (clock) return Number(clock[1]) * 60 + Number(clock[2]);
  if (/^\d+$/.test(text)) return Number(text);
  return Number.NaN;
}

// 72 -> "1:12", 5 -> "0:05"
export function formatProgressMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${hours}:${String(rest).padStart(2, "0")}`;
}

// 0..100, or null when the runtime isn't known
export function progressPercent(
  minutes: number | null,
  runtimeMinutes: number | null,
): number | null {
  if (minutes === null || !runtimeMinutes) return null;
  return Math.min(100, Math.round((minutes / runtimeMinutes) * 100));
}
