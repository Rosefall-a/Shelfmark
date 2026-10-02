import { afterEach, describe, expect, it, vi } from "vitest";
import {
  comparePluginContributions,
  derivePluginContributions,
  refreshPluginExtensions,
  clearPluginExtensions,
  activePluginDocuments,
  activePluginDialog,
  openPluginDialog,
  pageReplacement,
  pluginNavigation,
  pluginSettingsSections,
  pluginSlots,
  pluginOverlays,
  pluginDialogs,
  pluginContextualActions,
  pluginRoutes,
  pluginPageReplacements,
  pluginDocumentReaders,
  documentReaderUrl,
} from "../state/pluginExtensions";
import { nativePluginComponent } from "../state/pluginNative";
import type { PluginUiDocument } from "../services/pluginUi";
import type { PluginSummary } from "../services/plugins";

const native = vi.hoisted(() => ({ cleanup: vi.fn(), activate: vi.fn() }));
vi.mock("../state/pluginNative", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("../state/pluginNative")>();
  return {
    ...original,
    reconcileNativePlugins: (
      sources: Parameters<typeof original.reconcileNativePlugins>[0],
    ) =>
      original.reconcileNativePlugins(sources, async () => ({
        activate(context) {
          native.activate(context.pluginId);
          context.registerComponent("dashboard", { render: () => null });
          context.onCleanup(native.cleanup);
        },
      })),
  };
});

afterEach(() => {
  clearPluginExtensions();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const plugin: PluginSummary = {
  plugin_id: "example.plugin",
  name: "Example",
  version: "1.0.0",
  status: "running",
  compatible: true,
  compatibility_reason: "",
  health: "healthy",
  permissions: [],
  granted_capabilities: [
    "frontend.navigation",
    "frontend.page.extend",
    "frontend.settings",
    "frontend.page.replace.home",
    "frontend.overlay",
    "frontend.dialog",
    "frontend.routes",
    "frontend.native",
  ],
  effective_capabilities: [
    "frontend.navigation",
    "frontend.navigation.main",
    "frontend.navigation.settings",
    "frontend.navigation.admin",
    "frontend.context.game",
    "frontend.context.media",
    "frontend.page.extend",
    "frontend.settings",
    "frontend.page.replace.home",
    "frontend.overlay",
    "frontend.dialog",
    "frontend.routes",
    "frontend.native",
  ],
  enabled: true,
};

const document: PluginUiDocument = {
  schema_version: "v1",
  plugin_id: plugin.plugin_id,
  title: "Example",
  frontend: { entry: "frontend/index.html" },
  native_frontend: { entry: "native/index.js", styles: ["native/style.css"] },
  settings: [],
  actions: [{ id: "help", label: "Help" }],
  tables: [],
  dialogs: [{ id: "help-dialog", title: "Help", body: "Body", actions: [] }],
  menus: [],
  pages: [
    {
      id: "dashboard",
      title: "Dashboard",
      description: "",
      settings: [],
      actions: [],
      tables: [],
      dialogs: [],
      navigation: { sidebar: true, label: "Plugin dashboard", order: 20 },
    },
  ],
  extensions: [
    {
      id: "home-dashboard",
      slot: "home.after-widgets",
      page_id: "dashboard",
      order: 10,
    },
  ],
  navigation: [
    {
      id: "main-link",
      location: "main.sidebar",
      label: "Example route",
      route_id: "dashboard-route",
      order: 1,
      visibility: { admin_only: false },
    },
  ],
  settings_sections: [
    {
      id: "settings-section",
      label: "Example settings",
      page_id: "dashboard",
      order: 5,
      visibility: { admin_only: false },
    },
  ],
  page_replacements: [
    {
      id: "replace-home",
      page: "home",
      page_id: "dashboard",
      order: 30,
    },
  ],
  overlays: [{ id: "global-help", page_id: "dashboard", order: 0 }],
  contextual_actions: [
    {
      id: "game-help",
      location: "game",
      label: "Help",
      action_id: "help",
      order: 0,
    },
  ],
  dialog_contributions: [
    { id: "help-dialog-contribution", dialog_id: "help-dialog" },
  ],
  routes: [
    {
      id: "dashboard-route",
      path: "dashboard/summary",
      page_id: "dashboard",
    },
  ],
};

describe("plugin extension registry", () => {
  it("registers game document readers only with both grants and removes stale defaults", async () => {
    const readerDocument: PluginUiDocument = {
      ...document,
      native_frontend: undefined,
      document_readers: [
        {
          id: "reader",
          page_id: "dashboard",
          label: "Read",
          extensions: [".pdf"],
          order: 0,
        },
      ],
    };
    let current: PluginSummary = {
      ...plugin,
      effective_capabilities: ["documents.read", "frontend.context.documents"],
    };
    for (const capabilities of [
      ["documents.read"],
      ["frontend.context.documents"],
    ]) {
      expect(
        derivePluginContributions(
          { ...current, effective_capabilities: capabilities },
          readerDocument,
        ).documentReaders,
      ).toEqual([]);
    }
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (url: string) =>
          new Response(
            JSON.stringify(url === "/api/plugins" ? [current] : readerDocument),
          ),
      ),
    );
    await refreshPluginExtensions();
    expect(pluginDocumentReaders.value).toHaveLength(1);
    expect(
      documentReaderUrl("game", { id: "opaque-id", filename: "Manual.PDF" }),
    ).toBe(
      "/plugins/example.plugin/dashboard?document_id=opaque-id&game_id=game",
    );
    expect(
      documentReaderUrl("game", { filename: "Manual.pdf" }),
    ).toBeUndefined();
    expect(
      documentReaderUrl("game", { id: "opaque-id", filename: "Archive.zip" }),
    ).toBeUndefined();
    current = { ...current, effective_capabilities: [] };
    await refreshPluginExtensions();
    expect(pluginDocumentReaders.value).toEqual([]);
    expect(
      documentReaderUrl("game", { id: "opaque-id", filename: "Manual.pdf" }),
    ).toBeUndefined();
  });
  it("reconciles every contribution and native code across lifecycle transitions through HTTP", async () => {
    let current = plugin;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (url: string) =>
          new Response(
            JSON.stringify(url === "/api/plugins" ? [current] : document),
            { status: 200 },
          ),
      ),
    );
    const registries = [
      pluginNavigation,
      pluginSettingsSections,
      pluginSlots,
      pluginOverlays,
      pluginDialogs,
      pluginContextualActions,
      pluginRoutes,
      pluginPageReplacements,
    ];
    for (const status of [
      "enabled",
      "starting",
      "running",
      "stopping",
      "disabled",
      "running",
      "failed",
      "quarantined",
      "running",
    ] as const) {
      current = { ...plugin, status, enabled: status !== "disabled" };
      await refreshPluginExtensions();
      for (const registry of registries) {
        if (status === "running")
          expect(registry.value.length).toBeGreaterThan(0);
        else expect(registry.value).toEqual([]);
      }
      if (status === "running") {
        expect(
          nativePluginComponent(plugin.plugin_id, "dashboard"),
        ).toBeDefined();
        expect(
          openPluginDialog(plugin.plugin_id, "help-dialog-contribution"),
        ).toBe(true);
      } else {
        expect(
          nativePluginComponent(plugin.plugin_id, "dashboard"),
        ).toBeUndefined();
        expect(activePluginDialog.value).toBeNull();
        expect(activePluginDocuments.value).toEqual({});
        expect(pageReplacement("home")).toBeUndefined();
      }
    }
    expect(native.activate).toHaveBeenCalledTimes(3);
    expect(native.cleanup).toHaveBeenCalledTimes(2);
  });

  it("prevents a stale UI response from restoring a disabled plugin", async () => {
    let finish!: (response: Response) => void;
    let current = plugin;
    const fetcher = vi.fn(async (url: string) =>
      url === "/api/plugins"
        ? new Response(JSON.stringify([current]))
        : new Promise<Response>((resolve) => {
            finish = resolve;
          }),
    );
    vi.stubGlobal("fetch", fetcher);
    const first = refreshPluginExtensions();
    await vi.waitFor(() => expect(finish).toBeDefined());
    current = { ...plugin, enabled: false, status: "disabled" };
    await refreshPluginExtensions();
    finish(new Response(JSON.stringify(document)));
    await first;
    expect(pluginNavigation.value).toEqual([]);
    expect(activePluginDocuments.value).toEqual({});
    expect(native.activate).not.toHaveBeenCalled();
  });

  it("namespaces IDs and selects replacements independently of discovery order", async () => {
    const first = { ...plugin, plugin_id: "a.plugin" };
    const second = { ...plugin, plugin_id: "z.plugin" };
    let plugins = [second, first];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (url: string) =>
          new Response(
            JSON.stringify(
              url === "/api/plugins"
                ? plugins
                : {
                    ...document,
                    plugin_id: url.includes("a.plugin")
                      ? first.plugin_id
                      : second.plugin_id,
                  },
            ),
          ),
      ),
    );
    await refreshPluginExtensions();
    const snapshot = pluginNavigation.value.map((item) => [
      item.pluginId,
      item.contributionId,
    ]);
    expect(pageReplacement("home")?.pluginId).toBe("a.plugin");
    expect(
      pluginSlots.value.filter((item) => item.extensionId === "home-dashboard"),
    ).toHaveLength(2);
    plugins = [first, second];
    await refreshPluginExtensions();
    expect(
      pluginNavigation.value.map((item) => [
        item.pluginId,
        item.contributionId,
      ]),
    ).toEqual(snapshot);
    expect(pageReplacement("home")?.pluginId).toBe("a.plugin");
  });
  it("derives host-owned routes and slots from an enabled plugin", () => {
    const contributions = derivePluginContributions(plugin, document);

    expect(
      contributions.navigation.find(
        (item) => item.contributionId === "main-link",
      ),
    ).toMatchObject({
      pluginId: plugin.plugin_id,
      location: "main.sidebar",
      routePath: "dashboard/summary",
      label: "Example route",
      order: 1,
    });
    expect(
      contributions.navigation.find((item) => item.pageId === "dashboard"),
    ).toMatchObject({
      pluginId: plugin.plugin_id,
      location: "main.sidebar",
      pageId: "dashboard",
      label: "Plugin dashboard",
      order: 20,
    });
    expect(contributions.slots[0]).toMatchObject({
      pluginId: plugin.plugin_id,
      extensionId: "home-dashboard",
      slot: "home.after-widgets",
    });
    expect(contributions.settings[0]).toMatchObject({
      pluginId: plugin.plugin_id,
      label: "Example settings",
      pageId: "dashboard",
    });
    expect(contributions.replacements[0]).toMatchObject({
      pluginId: plugin.plugin_id,
      hostPage: "home",
      page: { id: "dashboard" },
    });
    expect(contributions.overlays[0]).toMatchObject({
      pluginId: plugin.plugin_id,
      contributionId: "global-help",
    });
    expect(contributions.routes[0]).toMatchObject({
      path: "dashboard/summary",
      page: { id: "dashboard" },
    });
    expect(contributions.contextualActions[0]).toMatchObject({
      location: "game",
      action: { id: "help" },
    });
    expect(contributions.dialogs[0]).toMatchObject({
      dialog: { id: "help-dialog" },
    });
  });

  it("ignores disabled and mismatched plugin documents", () => {
    expect(
      derivePluginContributions({ ...plugin, enabled: false }, document),
    ).toMatchObject({
      navigation: [],
      slots: [],
      settings: [],
      replacements: [],
      documentReaders: [],
    });
    expect(
      derivePluginContributions(plugin, {
        ...document,
        plugin_id: "other.plugin",
      }),
    ).toMatchObject({
      navigation: [],
      slots: [],
      settings: [],
      replacements: [],
      documentReaders: [],
    });
  });

  it("does not expose contributions whose capability is denied", () => {
    const contributions = derivePluginContributions(
      { ...plugin, granted_capabilities: [], effective_capabilities: [] },
      document,
    );

    expect(contributions.navigation).toEqual([]);
    expect(contributions.settings).toEqual([]);
    expect(contributions.slots).toEqual([]);
    expect(contributions.replacements).toEqual([]);
  });

  it("does not let a home replacement grant replace Settings", () => {
    const settingsReplacement: PluginUiDocument = {
      ...document,
      page_replacements: [
        {
          id: "replace-settings",
          page: "settings",
          page_id: "dashboard",
          order: 0,
        },
      ],
    };

    expect(
      derivePluginContributions(plugin, settingsReplacement).replacements,
    ).toEqual([]);
  });

  it("accepts a Settings replacement only with its page-specific grant", () => {
    const settingsReplacement: PluginUiDocument = {
      ...document,
      page_replacements: [
        {
          id: "replace-settings",
          page: "settings",
          page_id: "dashboard",
          order: 0,
        },
      ],
    };

    expect(
      derivePluginContributions(
        {
          ...plugin,
          effective_capabilities: [
            ...plugin.effective_capabilities,
            "frontend.page.replace.settings",
          ],
        },
        settingsReplacement,
      ).replacements[0],
    ).toMatchObject({ hostPage: "settings", page: { id: "dashboard" } });
  });

  it("resolves replacement conflicts by order, plugin ID, then contribution ID", () => {
    const values = [
      { order: 0, pluginId: "z.plugin", contributionId: "first" },
      { order: 0, pluginId: "a.plugin", contributionId: "second" },
      { order: -1, pluginId: "z.plugin", contributionId: "third" },
    ];

    expect(values.sort(comparePluginContributions)).toEqual([
      { order: -1, pluginId: "z.plugin", contributionId: "third" },
      { order: 0, pluginId: "a.plugin", contributionId: "second" },
      { order: 0, pluginId: "z.plugin", contributionId: "first" },
    ]);
  });

  it("keeps the sandbox frontend independent from native permission", () => {
    const denied = derivePluginContributions(
      {
        ...plugin,
        granted_capabilities: ["frontend.navigation"],
        effective_capabilities: [
          "frontend.navigation",
          "frontend.navigation.main",
        ],
      },
      document,
    );

    expect(document.frontend?.entry).toBe("frontend/index.html");
    expect(denied.navigation.length).toBeGreaterThan(0);
    expect(denied.slots).toEqual([]);
    expect(denied.overlays).toEqual([]);
  });
});
