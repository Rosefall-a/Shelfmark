import { beforeEach, describe, expect, it } from "vitest";
import {
  classifySetupStatus,
  consumeReturnPath,
  rememberReturnPath,
  safeReturnPath,
  startupState,
} from "../state/startup";

const storage = new Map<string, string>();
Object.defineProperty(globalThis, "sessionStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
    clear: () => storage.clear(),
  },
});

describe("startup state", () => {
  beforeEach(() => {
    sessionStorage.clear();
    startupState.value = "checking";
  });

  it("distinguishes confirmed setup from an available configured backend", () => {
    expect(classifySetupStatus({ setup_required: true })).toBe("setup-required");
    expect(classifySetupStatus({ setup_required: false })).toBe("ready");
  });

  it("preserves internal paths with query parameters", () => {
    const path = "/settings?section=admin-sessions";
    expect(safeReturnPath(path)).toBe(path);
    rememberReturnPath(path);
    expect(consumeReturnPath(undefined)).toBe(path);
  });

  it("rejects external and protocol-relative return paths", () => {
    expect(safeReturnPath("https://malicious.example/")).toBeNull();
    expect(safeReturnPath("//malicious.example/")).toBeNull();
    expect(safeReturnPath("javascript:alert(1)")).toBeNull();
  });

  it("falls back safely when the return path is missing or malformed", () => {
    expect(consumeReturnPath(undefined)).toBeNull();
    expect(consumeReturnPath("not a route")).toBeNull();
    rememberReturnPath("/games/example");
    expect(consumeReturnPath("/bad external value")).toBe("/games/example");
  });

  it("consumes a stored return path only once", () => {
    rememberReturnPath("/games/example?tab=history");
    expect(consumeReturnPath(undefined)).toBe("/games/example?tab=history");
    expect(consumeReturnPath(undefined)).toBeNull();
  });
});
