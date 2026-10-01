import {
  computed,
  defineComponent,
  h,
  markRaw,
  reactive,
  readonly,
  ref,
  shallowReadonly,
  shallowRef,
  type Component,
} from "vue";
import type { Router } from "vue-router";

export interface NativeFrontendSource {
  pluginId: string;
  version: string;
  entry: string;
  styles: string[];
  pageIds: string[];
}

export interface NativePluginContext {
  pluginId: string;
  registerComponent(pageId: string, component: Component): void;
  onCleanup(callback: () => void): void;
  vue: {
    computed: typeof computed;
    defineComponent: typeof defineComponent;
    h: typeof h;
    reactive: typeof reactive;
    readonly: typeof readonly;
    ref: typeof ref;
  };
  host: {
    navigate(path: string): Promise<void>;
    runAction(
      actionId: string,
      values?: Record<string, unknown>,
    ): Promise<Record<string, unknown>>;
    saveSettings(values: Record<string, unknown>): Promise<void>;
    openDialog(contributionId: string): void;
  };
}

interface NativePluginModule {
  activate?: (
    context: NativePluginContext,
  ) =>
    | void
    | (() => void)
    | { deactivate?: () => void }
    | Promise<void | (() => void) | { deactivate?: () => void }>;
  default?: NativePluginModule["activate"];
}

interface ActiveNativePlugin {
  signature: string;
  cleanup: () => void;
}

type ModuleImporter = (url: string) => Promise<NativePluginModule>;

const componentState = shallowRef<Record<string, Component>>({});
const failureState = shallowRef<Record<string, string>>({});
const activePlugins = new Map<string, ActiveNativePlugin>();
let hostRouter: Router | null = null;
let dialogOpener: (pluginId: string, contributionId: string) => void = () => {};

export const nativePluginComponents = shallowReadonly(componentState);
export const nativePluginFailures = shallowReadonly(failureState);

export function configureNativePluginHost(
  router: Router,
  openDialog: (pluginId: string, contributionId: string) => void,
): void {
  hostRouter = router;
  dialogOpener = openDialog;
}

function componentKey(pluginId: string, pageId: string): string {
  return `${pluginId}:${pageId}`;
}

export function nativePluginComponent(
  pluginId: string,
  pageId: string,
): Component | undefined {
  return componentState.value[componentKey(pluginId, pageId)];
}

function assetUrl(pluginId: string, path: string): string {
  const encodedPath = path.split("/").map(encodeURIComponent).join("/");
  return `/api/plugins/${encodeURIComponent(pluginId)}/native-frontend/${encodedPath}`;
}

async function defaultImporter(url: string): Promise<NativePluginModule> {
  return import(/* @vite-ignore */ url) as Promise<NativePluginModule>;
}

function removeComponents(pluginId: string): void {
  componentState.value = Object.fromEntries(
    Object.entries(componentState.value).filter(
      ([key]) => !key.startsWith(`${pluginId}:`),
    ),
  );
}

function deactivate(pluginId: string): void {
  const active = activePlugins.get(pluginId);
  if (!active) return;
  activePlugins.delete(pluginId);
  try {
    active.cleanup();
  } catch {
    // A privileged plugin cleanup failure must not interrupt host cleanup.
  }
  removeComponents(pluginId);
}

async function activate(
  source: NativeFrontendSource,
  importer: ModuleImporter,
): Promise<void> {
  const signature = `${source.version}:${source.entry}:${source.styles.join(",")}`;
  if (activePlugins.get(source.pluginId)?.signature === signature) return;
  deactivate(source.pluginId);
  const cleanups: Array<() => void> = [];
  const registeredKeys: string[] = [];
  const cleanup = () => {
    for (const callback of cleanups.reverse()) {
      try {
        callback();
      } catch {
        // Continue until every host-owned registration has been removed.
      }
    }
    if (registeredKeys.length) {
      componentState.value = Object.fromEntries(
        Object.entries(componentState.value).filter(
          ([key]) => !registeredKeys.includes(key),
        ),
      );
    }
  };
  try {
    if (typeof document !== "undefined") {
      for (const style of source.styles) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.dataset.pluginId = source.pluginId;
        link.href = assetUrl(source.pluginId, style);
        document.head.appendChild(link);
        cleanups.push(() => link.remove());
      }
    }
    const module = await importer(
      `${assetUrl(source.pluginId, source.entry)}?v=${encodeURIComponent(source.version)}`,
    );
    const entry = module.activate ?? module.default;
    if (typeof entry !== "function")
      throw new Error(
        "Native frontend must export activate or a default function.",
      );
    const result = await entry({
      pluginId: source.pluginId,
      registerComponent(pageId, component) {
        if (!/^[a-z0-9][a-z0-9._-]*$/.test(pageId))
          throw new Error("Native component page ID is invalid.");
        if (!source.pageIds.includes(pageId))
          throw new Error(
            "Native component must target a declared plugin page.",
          );
        const key = componentKey(source.pluginId, pageId);
        registeredKeys.push(key);
        componentState.value = {
          ...componentState.value,
          [key]: markRaw(component),
        };
      },
      onCleanup(callback) {
        cleanups.push(callback);
      },
      vue: { computed, defineComponent, h, reactive, readonly, ref },
      host: {
        async navigate(path) {
          if (!hostRouter) throw new Error("Host router is not ready.");
          await hostRouter.push(path);
        },
        async runAction(actionId, values = {}) {
          const response = await fetch(
            `/api/plugins/${encodeURIComponent(source.pluginId)}/actions/${encodeURIComponent(actionId)}`,
            {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ values }),
            },
          );
          if (!response.ok)
            throw new Error("Plugin action could not be completed.");
          return (await response.json()) as Record<string, unknown>;
        },
        async saveSettings(values) {
          const response = await fetch(
            `/api/plugins/${encodeURIComponent(source.pluginId)}/settings`,
            {
              method: "PUT",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(values),
            },
          );
          if (!response.ok)
            throw new Error("Plugin settings could not be saved.");
        },
        openDialog(contributionId) {
          dialogOpener(source.pluginId, contributionId);
        },
      },
    });
    if (typeof result === "function") cleanups.push(result);
    else if (result?.deactivate) cleanups.push(result.deactivate);
    activePlugins.set(source.pluginId, { signature, cleanup });
    const failures = { ...failureState.value };
    delete failures[source.pluginId];
    failureState.value = failures;
  } catch (error) {
    cleanup();
    failureState.value = {
      ...failureState.value,
      [source.pluginId]:
        error instanceof Error
          ? error.message
          : "Native frontend failed to activate.",
    };
  }
}

export async function reconcileNativePlugins(
  sources: NativeFrontendSource[],
  importer: ModuleImporter = defaultImporter,
): Promise<void> {
  const requested = new Set(sources.map((source) => source.pluginId));
  for (const pluginId of [...activePlugins.keys()]) {
    if (!requested.has(pluginId)) deactivate(pluginId);
  }
  await Promise.all(sources.map((source) => activate(source, importer)));
}

export function resetNativePluginsForTests(): void {
  for (const pluginId of [...activePlugins.keys()]) deactivate(pluginId);
  failureState.value = {};
}
