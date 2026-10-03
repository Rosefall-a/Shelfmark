import { describe, expect, it, vi } from "vitest";
import {
  disablePlugin,
  enablePlugin,
  fetchPlugins,
  fetchPluginLogs,
  retryPlugin,
  revokePluginPermissions,
  installPlugin,
  previewPluginInstall,
  UntrustedPluginError,
  fetchPluginCatalog,
  fetchPluginCatalogFromSource,
  previewPluginInstallUrl,
  installPluginFromUrl,
  previewPluginUpdateUrl,
  updatePluginFromUrl,
  updatePlugin,
} from "../services/plugins";

describe("plugin management service", () => {
  it("sends administrator upload confirmation passwords only in multipart bodies", async () => {
    const mock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify({ status: "installed" }), {
          status: 201,
        }),
    );
    const file = new File([new Uint8Array([80, 75])], "example.utp");
    const confirmation = {
      approvedPermissions: ["frontend.native:v1"],
      adminPassword: "private-upload-confirmation",
      confirmDangerous: true,
    };
    await installPlugin(file, confirmation);
    await updatePlugin("example.plugin", file, confirmation);
    for (const [url, init] of mock.mock.calls) {
      expect(String(url)).not.toContain("admin_password");
      expect(String(url)).not.toContain(confirmation.adminPassword);
      expect((init?.body as FormData).get("admin_password")).toBe(
        confirmation.adminPassword,
      );
      expect((init?.body as FormData).get("file")).toBeTruthy();
    }
    mock.mockRestore();
  });
  it("uses the gateway-facing plugin lifecycle endpoints", async () => {
    const mock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
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
    const file = new File(
      [new Uint8Array([80, 75, 3, 4])],
      "example.ui-playground-1.0.0.utp",
    );
    await expect(
      installPlugin(file, { approvedPermissions: [] }),
    ).rejects.toBeInstanceOf(UntrustedPluginError);
    mock.mockRestore();
  });

  it("previews package permissions before committing an installation", async () => {
    const preview = {
      plugin_id: "example.plugin",
      name: "Example",
      description: "Example plugin",
      version: "1.0.0",
      publisher: "official-test",
      digest: "a".repeat(64),
      trust_status: "trusted" as const,
      trust_warning: null,
      sdk_version_range: "^1.0.0",
      application_version_range: "*",
      dependencies: [],
      permissions: [
        {
          key: "games.read:v1",
          capability: "games.read",
          capability_version: 1,
          rationale: "Read the game library.",
        },
      ],
      ui: { pages: ["main"], menus: ["main"], has_custom_frontend: false },
    };
    const mock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(preview), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...preview,
            installation_id: "installation",
            permissions_requested: 1,
            permissions_granted: 1,
            permissions_denied: 0,
            status: "installed",
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      );
    const file = new File([new Uint8Array([80, 75, 3, 4])], "example.utp");

    await expect(previewPluginInstall(file)).resolves.toEqual(preview);
    await installPlugin(file, { approvedPermissions: ["games.read:v1"] });

    expect(String(mock.mock.calls[0][0])).toBe("/api/plugins/install/preview");
    expect(String(mock.mock.calls[1][0])).toContain(
      "approved_permissions=games.read%3Av1",
    );
    mock.mockRestore();
  });

  it("surfaces gateway errors instead of silently succeeding", async () => {
    const mock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("unavailable", { status: 503 }));
    await expect(fetchPlugins()).rejects.toThrow("503");
    mock.mockRestore();
  });

  it("loads structured administrative diagnostics", async () => {
    const diagnostics = {
      plugin_id: "example.plugin",
      status: "stopped",
      last_exit_code: 1,
      events: [
        {
          sequence: 1,
          timestamp: "2026-09-30T00:00:00+00:00",
          level: "error",
          event: "runtime.exited",
          message: "Plugin process exited unexpectedly.",
          source: "runtime",
          plugin_id: "example.plugin",
          correlation_id: null,
          metadata: { return_code: 1 },
        },
      ],
    };
    const mock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(diagnostics), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(fetchPluginLogs("example.plugin")).resolves.toEqual(
      diagnostics,
    );
    expect(String(mock.mock.calls[0][0])).toBe(
      "/api/plugins/example.plugin/logs",
    );
    mock.mockRestore();
  });
});

describe("remote plugin installation", () => {
  it("preserves catalogue provenance and the selected release URL in every remote lifecycle request", async () => {
    const mock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify({ plugin_id: "example.test" }), {
          status: 200,
        }),
    );
    const url = "https://example.com/test-2.0.0.utp";
    const source = {
      type: "catalogue" as const,
      url: "https://example.com/test-1.0.0.utp",
      catalogue_url: "https://example.com/catalogue.json",
      release_notes: "Security fixes",
    };
    await previewPluginInstallUrl(url, source);
    await installPluginFromUrl(
      url,
      { approvedPermissions: [] },
      "a".repeat(64),
      false,
      source,
    );
    await previewPluginUpdateUrl("example.test", url, source);
    await updatePluginFromUrl(
      "example.test",
      url,
      { approvedPermissions: [] },
      "a".repeat(64),
      false,
      source,
    );
    for (const [, options] of mock.mock.calls) {
      const body = JSON.parse(String(options?.body));
      expect(body).toMatchObject({
        url,
        source_type: "catalogue",
        catalogue_url: source.catalogue_url,
        release_notes: source.release_notes,
      });
      expect(body).not.toHaveProperty("type");
    }
    mock.mockRestore();
  });

  it("loads the official catalogue", async () => {
    const mock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(
          JSON.stringify([
            {
              plugin_id: "example.test",
              name: "Test",
              description: "Demo",
              version: "1.0.0",
              url: "https://example.com/test.utp",
            },
          ]),
          { status: 200 },
        ),
    );
    await expect(fetchPluginCatalog()).resolves.toHaveLength(1);
    expect(mock.mock.calls[0][0]).toBe("/api/plugins/catalog");
    await fetchPluginCatalogFromSource("https://example.com/other-list.json");
    expect(String(mock.mock.calls[1][0])).toContain(
      "source=https%3A%2F%2Fexample.com%2Fother-list.json",
    );
    mock.mockRestore();
  });

  it("previews and installs a package from a URL", async () => {
    const mock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url) => {
        if (String(url).endsWith("/preview-url")) {
          return new Response(JSON.stringify({ plugin_id: "example.test" }), {
            status: 200,
          });
        }
        return new Response(
          JSON.stringify({ plugin_id: "example.test", version: "1.0.0" }),
          { status: 201 },
        );
      });
    await previewPluginInstallUrl("https://example.com/test.utp");
    await installPluginFromUrl(
      "https://example.com/test.utp",
      { approvedPermissions: [] },
      "a".repeat(64),
    );
    expect(String(mock.mock.calls[0][0])).toContain("/preview-url");
    expect(String(mock.mock.calls[1][0])).toContain("/install/url");
    mock.mockRestore();
  });

  it("previews and applies a discovered update through the canonical URL flow", async () => {
    const mock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url) => {
        if (String(url).endsWith("/update/preview-url")) {
          return new Response(
            JSON.stringify({
              plugin_id: "example.test",
              digest: "a".repeat(64),
            }),
            { status: 200 },
          );
        }
        return new Response(
          JSON.stringify({
            plugin_id: "example.test",
            version: "2.0.0",
            permissions_requested: 0,
            status: "running",
          }),
          { status: 200 },
        );
      });
    await previewPluginUpdateUrl(
      "example.test",
      "https://example.com/test-2.0.0.utp",
      { type: "catalogue", release_notes: "Security fixes" },
    );
    await updatePluginFromUrl(
      "example.test",
      "https://example.com/test-2.0.0.utp",
      { approvedPermissions: [] },
      "a".repeat(64),
    );
    expect(String(mock.mock.calls[0][0])).toContain("/update/preview-url");
    expect(String(mock.mock.calls[1][0])).toContain("/update/url");
    mock.mockRestore();
  });
});
