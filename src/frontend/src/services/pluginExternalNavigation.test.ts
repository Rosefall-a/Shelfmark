import { describe, expect, it } from "vitest";
import { pluginExternalDestination, type UiAction } from "./pluginUi";

const action = { external_navigation: true } as UiAction;
describe("plugin external navigation", () => {
  it("uses an explicit declared HTTP destination", () => {
    expect(
      pluginExternalDestination(action, {
        redirect_url: "https://media.example/web/index.html#!/details?id=123",
      }),
    ).toBe("https://media.example/web/index.html#!/details?id=123");
    expect(
      pluginExternalDestination({} as UiAction, {
        redirect_url: "https://media.example",
      }),
    ).toBeNull();
    expect(pluginExternalDestination(action, { ok: false })).toBeNull();
  });
  it("rejects executable schemes and embedded credentials", () => {
    for (const redirect_url of [
      "javascript:alert(1)",
      "file:///etc/passwd",
      "https://secret@host",
    ]) {
      expect(() =>
        pluginExternalDestination(action, { redirect_url }),
      ).toThrow();
    }
  });
});
