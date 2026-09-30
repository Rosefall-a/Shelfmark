import { describe, expect, it } from "vitest";
import { derivePluginContributions } from "../state/pluginExtensions";
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
  ],
  enabled: true,
};

const document: PluginUiDocument = {
  schema_version: "v1",
  plugin_id: plugin.plugin_id,
  title: "Example",
  settings: [],
  actions: [],
  tables: [],
  dialogs: [],
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
};

describe("plugin extension registry", () => {
  it("derives host-owned routes and slots from an enabled plugin", () => {
    const contributions = derivePluginContributions(plugin, document);

    expect(contributions.navigation[0]).toMatchObject({
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
});
