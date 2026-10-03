import {
  computed,
  defineComponent,
  onBeforeUnmount,
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
import { checkAuth } from "./auth";

export interface NativeFrontendSource {
  pluginId: string;
  version: string;
  entry: string;
  styles: string[];
  pageIds: string[];
  actions?: Array<{ id: string; confirmation?: string }>;
}

export interface NativePluginContext {
  pluginId: string;
  version: string;
  registerComponent(pageId: string, component: Component): void;
  onCleanup(callback: () => void): void;
  vue: {
    computed: typeof computed;
    defineComponent: typeof defineComponent;
    onBeforeUnmount: typeof onBeforeUnmount;
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
  requiresReload: boolean;
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
  // Privileged modules can retain timers and host references outside our SDK.
  // Destroy their browser realm instead of relying on cooperative cleanup.
  if (active.requiresReload && typeof window !== "undefined")
    window.location.reload();
}

export function retainNativePlugins(pluginIds: ReadonlySet<string>): void {
  for (const pluginId of [...activePlugins.keys()]) {
    if (!pluginIds.has(pluginId)) deactivate(pluginId);
  }
}

async function activate(
  source: NativeFrontendSource,
  importer: ModuleImporter,
): Promise<void> {
  const signature = JSON.stringify([
    source.version,
    source.entry,
    source.styles,
    [...source.pageIds].sort(),
  ]);
  if (activePlugins.get(source.pluginId)?.signature === signature) return;
  deactivate(source.pluginId);
  const cleanups: Array<() => void> = [];
  const registeredKeys: string[] = [];
  let disposed = false;
  const cleanup = () => {
    disposed = true;
    for (const callback of cleanups.splice(0).reverse()) {
      try {
        callback();
      } catch {
        // Continue until every host-owned registration has been removed.
      }
    }
    if (registeredKeys.length) {
      const removedKeys = registeredKeys.splice(0);
      componentState.value = Object.fromEntries(
        Object.entries(componentState.value).filter(
          ([key]) => !removedKeys.includes(key),
        ),
      );
    }
  };
  // Track pending imports too, so removal cancels activation before it starts.
  const activation = {
    signature,
    cleanup,
    requiresReload: importer === defaultImporter,
  };
  activePlugins.set(source.pluginId, activation);
  const requireActive = () => {
    if (disposed || activePlugins.get(source.pluginId) !== activation)
      throw new Error("Plugin frontend is no longer active.");
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
    if (disposed) return;
    const entry = module.activate ?? module.default;
    if (typeof entry !== "function")
      throw new Error(
        "Native frontend must export activate or a default function.",
      );
    const result = await entry({
      pluginId: source.pluginId,
      version: source.version,
      registerComponent(pageId, component) {
        requireActive();
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
        if (disposed) callback();
        else cleanups.push(callback);
      },
      vue: {
        computed,
        defineComponent,
        h,
        reactive,
        readonly,
        ref,
        onBeforeUnmount,
      },
      host: {
        async navigate(path) {
          requireActive();
          if (!hostRouter) throw new Error("Host router is not ready.");
          if (path === "/login") await checkAuth();
          await hostRouter.push(path);
        },
        async runAction(actionId, values = {}) {
          requireActive();
          const action = source.actions?.find((item) => item.id === actionId);
          if (action?.confirmation && !window.confirm(action.confirmation))
            return { cancelled: true };
          const response = await fetch(
            `/api/plugins/${encodeURIComponent(source.pluginId)}/actions/${encodeURIComponent(actionId)}`,
            {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                values,
                confirmed: Boolean(action?.confirmation),
              }),
            },
          );
          if (!response.ok)
            throw new Error("Plugin action could not be completed.");
          return (await response.json()) as Record<string, unknown>;
        },
        async saveSettings(values) {
          requireActive();
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
          requireActive();
          dialogOpener(source.pluginId, contributionId);
        },
      },
    });
    if (typeof result === "function") cleanups.push(result);
    else if (result?.deactivate) cleanups.push(result.deactivate);
    if (disposed) {
      cleanup();
      return;
    }
    const failures = { ...failureState.value };
    delete failures[source.pluginId];
    failureState.value = failures;
  } catch (error) {
    cleanup();
    if (activePlugins.get(source.pluginId) !== activation) return;
    // Keep failed production imports tracked: a later lifecycle removal must
    // still destroy any code they evaluated before throwing.
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
  retainNativePlugins(requested);
  await Promise.all(sources.map((source) => activate(source, importer)));
}

export function resetNativePluginsForTests(): void {
  for (const pluginId of [...activePlugins.keys()]) deactivate(pluginId);
  failureState.value = {};
}
