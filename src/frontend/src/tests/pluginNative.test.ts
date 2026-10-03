import { afterEach, describe, expect, it, vi } from "vitest";
import {
  nativePluginComponent,
  nativePluginFailures,
  reconcileNativePlugins,
  resetNativePluginsForTests,
  type NativePluginContext,
} from "../state/pluginNative";

const source = {
  pluginId: "example.native",
  version: "1.0.0",
  entry: "native/index.js",
  styles: [],
  pageIds: ["dashboard"],
};

afterEach(() => {
  resetNativePluginsForTests();
  vi.unstubAllGlobals();
});

describe("native plugin lifecycle", () => {
  it("requires host confirmation before sending a destructive action", async () => {
    const confirm = vi
      .fn()
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ revoked: 1 }) });
    vi.stubGlobal("window", { confirm });
    vi.stubGlobal("fetch", fetch);
    let context!: NativePluginContext;
    await reconcileNativePlugins(
      [
        {
          ...source,
          actions: [{ id: "revoke", confirmation: "Revoke sessions?" }],
        },
      ],
      async () => ({
        activate(value) {
          context = value;
        },
      }),
    );
    expect(await context.host.runAction("revoke")).toEqual({ cancelled: true });
    expect(fetch).not.toHaveBeenCalled();
    expect(await context.host.runAction("revoke")).toEqual({ revoked: 1 });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      values: {},
      confirmed: true,
    });
    expect(confirm).toHaveBeenCalledTimes(2);
  });
  it("reloads the browser realm when a production import is removed, including failed imports", async () => {
    resetNativePluginsForTests();
    const reload = vi.fn();
    vi.stubGlobal("window", { location: { reload } });
    // The HTTP module URL cannot import in Node. Its failed production import
    // must remain tracked until disable/quarantine removes the source.
    await reconcileNativePlugins([source]);
    expect(reload).not.toHaveBeenCalled();
    await reconcileNativePlugins([source]);
    expect(reload).not.toHaveBeenCalled();
    await reconcileNativePlugins([]);
    expect(reload).toHaveBeenCalledOnce();
  });
  it("cancels an import when the plugin is removed before activation", async () => {
    resetNativePluginsForTests();
    const activate = vi.fn();
    let finish!: (module: { activate: typeof activate }) => void;
    const pending = reconcileNativePlugins(
      [source],
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    await reconcileNativePlugins([]);
    finish({ activate });
    await pending;
    expect(activate).not.toHaveBeenCalled();
    expect(nativePluginComponent(source.pluginId, "dashboard")).toBeUndefined();
  });

  it("revokes retained host methods and cleans up a late activation result", async () => {
    resetNativePluginsForTests();
    let context!: NativePluginContext;
    let finish!: (cleanup: () => void) => void;
    const earlyCleanup = vi.fn();
    const lateCleanup = vi.fn();
    const pending = reconcileNativePlugins([source], async () => ({
      activate(value) {
        context = value;
        value.onCleanup(earlyCleanup);
        value.registerComponent("dashboard", { render: () => null });
        return new Promise((resolve) => {
          finish = resolve;
        });
      },
    }));
    await vi.waitFor(() => expect(context).toBeDefined());
    await reconcileNativePlugins([]);
    expect(earlyCleanup).toHaveBeenCalledOnce();
    expect(() =>
      context.registerComponent("dashboard", { render: () => null }),
    ).toThrow("no longer active");
    expect(() => context.host.openDialog("help")).toThrow("no longer active");
    await expect(context.host.runAction("help")).rejects.toThrow(
      "no longer active",
    );
    finish(lateCleanup);
    await pending;
    expect(lateCleanup).toHaveBeenCalledOnce();
    expect(nativePluginComponent(source.pluginId, "dashboard")).toBeUndefined();
  });
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
