// A date-only value ("2026-09-12", what <input type="date"> and the API's
// date fields use) is a calendar day, not an instant. `new Date("2026-09-12")`
// reads it as UTC midnight, which toLocaleDateString() then shows as the day
// before anywhere west of UTC. These helpers keep calendar days as local
// days on the way in and out.

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

// For display: date-only strings become that local calendar day, anything
// else (a full ISO timestamp) is parsed as usual.
export function parseDisplayDate(value: string): Date {
  const match = DATE_ONLY.exec(value);
  if (!match) return new Date(value);
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

export function formatDisplayDate(
  value: string | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  if (!value) return "";
  return parseDisplayDate(value).toLocaleDateString(undefined, options);
}

// "YYYY-MM-DD" of the local calendar day an instant falls on, the value an
// <input type="date"> needs.
export function toLocalDateInput(
  value: string | Date | null | undefined,
): string {
  if (!value) return "";
  if (typeof value === "string" && DATE_ONLY.test(value)) return value;
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// Unix seconds at local midnight of a "YYYY-MM-DD" day, so it reads back
// (toLocalDateInput / toLocaleDateString) as the same day that was picked.
export function localDateInputToUnixSeconds(value: string): number | null {
  const match = DATE_ONLY.exec(value);
  if (!match) return null;
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  );
  return Math.floor(date.getTime() / 1000);
}
