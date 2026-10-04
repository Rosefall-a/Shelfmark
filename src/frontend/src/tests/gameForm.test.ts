import { afterEach, describe, expect, it, vi } from "vitest";

import { friendlyError } from "../services/apiError";
import { mapBackendGame, rankMetadataResults } from "../services/games";
import type { BackendGame } from "../services/games";
import {
  formatDisplayDate,
  localDateInputToUnixSeconds,
  parseDisplayDate,
  toLocalDateInput,
} from "../utils/dates";
import { activePriority, priorityRank } from "../utils/priority";

describe("friendlyError", () => {
  it("turns a FastAPI validation list into readable field messages (#16)", () => {
    const body = JSON.stringify({
      detail: [
        {
          type: "string_pattern_mismatch",
          loc: ["body", "folder_location"],
          msg: "String should match pattern '^[A-Za-z0-9_-]+$'",
        },
        {
          type: "value_error",
          loc: ["body", "purchase_price_currency_code"],
          msg: "Value error, Invalid currency code: XYZ",
        },
      ],
    });
    const message = friendlyError(422, body);
    expect(message).toContain("Folder location: String should match pattern");
    expect(message).toContain(
      "Purchase price currency code: Invalid currency code: XYZ",
    );
    expect(message).not.toContain("{");
  });

  it("uses a structured detail's message, e.g. a duplicate folder", () => {
    const body = JSON.stringify({
      detail: {
        error: "duplicate_folder_location",
        message: "A game with folder_location 'Hades' already exists.",
      },
    });
    expect(friendlyError(409, body)).toBe(
      "A game with folder_location 'Hades' already exists.",
    );
  });

  it("falls back to a generic sentence rather than raw text", () => {
    expect(friendlyError(422, "not json")).toBe(
      "That is not a valid address or value.",
    );
    expect(friendlyError(400, "<html>")).toBe("The request failed (400).");
  });
});

describe("rankMetadataResults", () => {
  it("puts the exact title first, then prefix and substring matches", () => {
    const results = [
      { title: "Hades II", provider: "steam" },
      { title: "Hades: Battle Out of Hell", provider: "igdb" },
      { title: "The Hades Chronicles", provider: "steam" },
      { title: "Hades™", provider: "igdb" },
      { title: "Unrelated", provider: "steam" },
    ];
    expect(rankMetadataResults(results, "hades").map((r) => r.title)).toEqual([
      "Hades™",
      "Hades II",
      "Hades: Battle Out of Hell",
      "The Hades Chronicles",
      "Unrelated",
    ]);
  });
});

describe("date-only values", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("reads a YYYY-MM-DD value as that local calendar day", () => {
    const date = parseDisplayDate("2026-09-12");
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([
      2026, 8, 12,
    ]);
    expect(formatDisplayDate("2026-09-12")).toBe(
      new Date(2026, 8, 12).toLocaleDateString(),
    );
  });

  it("round-trips a picked day through unix seconds", () => {
    const seconds = localDateInputToUnixSeconds("2026-01-31");
    expect(seconds).not.toBeNull();
    expect(toLocalDateInput(new Date(seconds! * 1000))).toBe("2026-01-31");
    expect(localDateInputToUnixSeconds("")).toBeNull();
  });
});

describe("game priority", () => {
  it("accepts 1-5 and the AniList HIGH/MEDIUM/LOW values", () => {
    expect(priorityRank("1")).toBe(1);
    expect(priorityRank("5")).toBe(5);
    expect(priorityRank("HIGH")).toBe(1);
    expect(priorityRank("9")).toBeNull();
    expect(priorityRank(null)).toBeNull();
  });

  it("drops finished games out of priority (#32)", () => {
    expect(activePriority({ status: "backlog", priority: "2" })).toBe(2);
    expect(activePriority({ status: "beaten", priority: "2" })).toBeNull();
    expect(activePriority({ status: "mastered", priority: "1" })).toBeNull();
  });
});

describe("mapBackendGame", () => {
  const raw = {
    id: "g1",
    title: "The Witcher 3",
    sort_title: "witcher 3",
    source: "Steam",
    platform: "Nintendo Switch",
    region: "PAL",
    language: "English",
    priority: "2",
    status: "BACKLOG",
    playtime_seconds: 0,
    created_at: 0,
    updated_at: 0,
    last_played_at: null,
    stale_since: null,
    completion_date: null,
    purchase_date: null,
    purchase_price: null,
    purchase_price_currency_code: null,
    physical_condition: null,
    rating_overall: null,
    rating_story: null,
    rating_gameplay: null,
    rating_soundtrack: null,
    time_to_beat_hours: null,
    tags: [],
    features: [],
    collections: [],
    links: [],
  } as unknown as BackendGame;

  it("keeps platform, region, language and priority from the API", () => {
    const game = mapBackendGame(raw);
    expect(game.platform).toBe("Nintendo Switch");
    expect(game.platforms[0].platform).toBe("Nintendo Switch");
    expect(game.region).toBe("PAL");
    expect(game.language).toBe("English");
    expect(game.priority).toBe("2");
  });

  it("only reports a sorting name someone chose", () => {
    expect(mapBackendGame(raw).sortTitle).toBeNull();
    expect(
      mapBackendGame({ ...raw, sort_title: "witcher 3 goty" }).sortTitle,
    ).toBe("witcher 3 goty");
  });

  it("falls back to the source when no platform is recorded", () => {
    const game = mapBackendGame({ ...raw, platform: null });
    expect(game.platforms[0].platform).toBe("Steam");
  });
});
