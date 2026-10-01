import { describe, expect, it } from "vitest";
import {
  comparePluginContributions,
  derivePluginContributions,
} from "../state/pluginExtensions";
import type { PluginUiDocument } from "../services/pluginUi";
import type { PluginSummary } from "../services/plugins";

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
