import { describe, expect, it } from "vitest";

import {
  formatProgressMinutes,
  parseProgressMinutes,
  progressPercent,
} from "../utils/watchProgress";

describe("movie left-off point (#191)", () => {
  it("accepts minutes or h:mm", () => {
    expect(parseProgressMinutes("72")).toBe(72);
    expect(parseProgressMinutes("1:12")).toBe(72);
    expect(parseProgressMinutes(" 0:05 ")).toBe(5);
    expect(parseProgressMinutes("")).toBeNull();
    expect(parseProgressMinutes("an hour")).toBeNaN();
    expect(parseProgressMinutes("1:75")).toBeNaN();
  });

  it("formats as h:mm", () => {
    expect(formatProgressMinutes(72)).toBe("1:12");
    expect(formatProgressMinutes(5)).toBe("0:05");
    expect(formatProgressMinutes(parseProgressMinutes("2:28")!)).toBe("2:28");
  });

  it("reports progress against the runtime, capped at 100%", () => {
    expect(progressPercent(74, 148)).toBe(50);
    expect(progressPercent(200, 148)).toBe(100);
    expect(progressPercent(30, null)).toBeNull();
    expect(progressPercent(null, 148)).toBeNull();
  });
});
