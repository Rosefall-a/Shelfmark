import { describe, expect, it, vi } from "vitest";
import {
  disablePlugin,
  enablePlugin,
  fetchPlugins,
  retryPlugin,
  revokePluginPermissions,
  installPlugin,
  UntrustedPluginError,
} from "../services/plugins";

describe("plugin management service", () => {
  it("uses the gateway-facing plugin lifecycle endpoints", async () => {
    const mock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await fetchPlugins();
    await enablePlugin("example.plugin");
    await disablePlugin("example.plugin");
    await retryPlugin("example.plugin");
    await revokePluginPermissions("example.plugin");

    expect(
      mock.mock.calls.map(([url, init]) => [
        String(url),
        init?.method ?? "GET",
      ]),
    ).toEqual([
      ["/api/plugins", "GET"],
      ["/api/plugins/example.plugin/enable", "POST"],
      ["/api/plugins/example.plugin/disable", "POST"],
      ["/api/plugins/example.plugin/retry", "POST"],
      ["/api/plugins/example.plugin/permissions/revoke", "POST"],
    ]);
    mock.mockRestore();
  });

  it("turns an untrusted install response into the explicit confirmation error", async () => {
    const mock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "untrusted_plugin",
            plugin_id: "example.ui-playground",
            name: "Plugin UI Playground",
            version: "1.0.0",
            publisher: null,
          },
        }),
        { status: 409 },
      ),
    );
    const file = new File([new Uint8Array([80, 75, 3, 4])], "example.ui-playground-1.0.0.utp");
    await expect(installPlugin(file)).rejects.toBeInstanceOf(UntrustedPluginError);
    mock.mockRestore();
  });

  it("surfaces gateway errors instead of silently succeeding", async () => {
    const mock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("unavailable", { status: 503 }));
    await expect(fetchPlugins()).rejects.toThrow("503");
    mock.mockRestore();
  });
});
