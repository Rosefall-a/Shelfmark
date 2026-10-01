import { describe, expect, it, vi } from "vitest";
import {
  nativePluginComponent,
  nativePluginFailures,
  reconcileNativePlugins,
  resetNativePluginsForTests,
} from "../state/pluginNative";

const source = {
  pluginId: "example.native",
  version: "1.0.0",
  entry: "native/index.js",
  styles: [],
  pageIds: ["dashboard"],
};

describe("native plugin lifecycle", () => {
  it("does not import a native bundle when no authorized source is supplied", async () => {
    resetNativePluginsForTests();
    const importer = vi.fn();

    await reconcileNativePlugins([], importer);

    expect(importer).not.toHaveBeenCalled();
  });

  it("registers Vue components and cleans them up when the plugin disappears", async () => {
    resetNativePluginsForTests();
    const cleanup = vi.fn();
    const component = { render: () => null };

    await reconcileNativePlugins([source], async () => ({
      activate(context) {
        context.registerComponent("dashboard", component);
        context.onCleanup(cleanup);
      },
    }));
    expect(nativePluginComponent(source.pluginId, "dashboard")).toBe(component);

    await reconcileNativePlugins([]);
    expect(nativePluginComponent(source.pluginId, "dashboard")).toBeUndefined();
    expect(cleanup).toHaveBeenCalledOnce();
  });

  it("isolates activation failures and removes partial registrations", async () => {
    resetNativePluginsForTests();

    await reconcileNativePlugins([source], async () => ({
      activate(context) {
        context.registerComponent("dashboard", { render: () => null });
        throw new Error("broken plugin");
      },
    }));

    expect(nativePluginComponent(source.pluginId, "dashboard")).toBeUndefined();
    expect(nativePluginFailures.value[source.pluginId]).toBe("broken plugin");
  });
});
