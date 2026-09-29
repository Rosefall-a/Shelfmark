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
};

describe("plugin extension registry", () => {
  it("derives host-owned routes and slots from an enabled plugin", () => {
    const contributions = derivePluginContributions(plugin, document);

    expect(contributions.navigation).toEqual([
      {
        pluginId: plugin.plugin_id,
        pageId: "dashboard",
        label: "Plugin dashboard",
        order: 20,
      },
    ]);
    expect(contributions.slots[0]).toMatchObject({
      pluginId: plugin.plugin_id,
      extensionId: "home-dashboard",
      slot: "home.after-widgets",
    });
  });

  it("ignores disabled and mismatched plugin documents", () => {
    expect(
      derivePluginContributions({ ...plugin, enabled: false }, document),
    ).toEqual({ navigation: [], slots: [] });
    expect(
      derivePluginContributions(plugin, {
        ...document,
        plugin_id: "other.plugin",
      }),
    ).toEqual({ navigation: [], slots: [] });
  });
});
