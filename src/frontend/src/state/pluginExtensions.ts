import { ref, shallowReadonly } from "vue";
import { fetchPlugins, type PluginSummary } from "../services/plugins";
import {
  fetchPluginUi,
  type HostExtensionSlot,
  type PluginUiDocument,
  type UiAction,
  type UiDialog,
  type UiNavigationLocation,
  type UiPage,
} from "../services/pluginUi";
import { reconcileNativePlugins } from "./pluginNative";

export interface PluginNavigationContribution {
  pluginId: string;
  contributionId: string;
  location: UiNavigationLocation;
  pageId?: string;
  routePath?: string;
  settingsSectionId?: string;
  action?: UiAction;
  label: string;
  icon?: string;
  order: number;
  adminOnly: boolean;
  document: PluginUiDocument;
}

export interface PluginSettingsContribution {
  pluginId: string;
  contributionId: string;
  pageId: string;
  label: string;
  icon?: string;
  order: number;
  adminOnly: boolean;
  document: PluginUiDocument;
}

export interface PluginSlotContribution {
  pluginId: string;
  extensionId: string;
  slot: HostExtensionSlot;
  page: UiPage;
  order: number;
  document: PluginUiDocument;
}

export interface PluginOverlayContribution {
  pluginId: string;
  contributionId: string;
  page: UiPage;
  order: number;
  document: PluginUiDocument;
}

export interface PluginDialogContribution {
  pluginId: string;
  contributionId: string;
  dialog: UiDialog;
  document: PluginUiDocument;
}

export interface PluginContextualActionContribution {
  pluginId: string;
  contributionId: string;
  location: "game" | "media" | "documents";
  label: string;
  action: UiAction;
  icon?: string;
  order: number;
  document: PluginUiDocument;
}

export interface PluginRouteContribution {
  pluginId: string;
  contributionId: string;
  path: string;
  page: UiPage;
  document: PluginUiDocument;
}

export interface PluginPageReplacementContribution {
  pluginId: string;
  contributionId: string;
  hostPage: "home" | "settings";
  page: UiPage;
  order: number;
  document: PluginUiDocument;
}

export interface PluginContributions {
  navigation: PluginNavigationContribution[];
  settings: PluginSettingsContribution[];
  slots: PluginSlotContribution[];
  overlays: PluginOverlayContribution[];
  dialogs: PluginDialogContribution[];
  contextualActions: PluginContextualActionContribution[];
  routes: PluginRouteContribution[];
  replacements: PluginPageReplacementContribution[];
}

const emptyContributions = (): PluginContributions => ({
  navigation: [],
  settings: [],
  slots: [],
  overlays: [],
  dialogs: [],
  contextualActions: [],
  routes: [],
  replacements: [],
});

function hasCapability(plugin: PluginSummary, capability: string): boolean {
  return plugin.effective_capabilities.includes(capability);
}

function navigationCapability(location: UiNavigationLocation): string {
  return {
    "main.sidebar": "frontend.navigation.main",
    "settings.sidebar": "frontend.navigation.settings",
    administration: "frontend.navigation.admin",
    "game.context": "frontend.context.game",
    "media.context": "frontend.context.media",
  }[location];
}

function extensionCapability(slot: HostExtensionSlot): string {
  if (slot === "home.replace") return "frontend.page.replace.home";
  if (slot === "app.global") return "frontend.overlay";
  return "frontend.page.extend";
}

export function derivePluginContributions(
  plugin: PluginSummary,
  document: PluginUiDocument,
): PluginContributions {
  if (
    !plugin.enabled ||
    !plugin.compatible ||
    document.plugin_id !== plugin.plugin_id
  )
    return emptyContributions();

  const legacyNavigation = hasCapability(plugin, "frontend.navigation.main")
    ? document.pages
        .filter((page) => page.navigation?.sidebar)
        .map((page) => ({
          pluginId: plugin.plugin_id,
          contributionId: `legacy:${page.id}`,
          location: "main.sidebar" as const,
          pageId: page.id,
          label: page.navigation?.label ?? page.title,
          order: page.navigation?.order ?? 0,
          adminOnly: false,
          document,
        }))
    : [];
  const navigation = [
    ...legacyNavigation,
    ...(document.navigation ?? [])
      .filter((item) =>
        hasCapability(plugin, navigationCapability(item.location)),
      )
      .map((item) => ({
        pluginId: plugin.plugin_id,
        contributionId: item.id,
        location: item.location,
        pageId: item.page_id,
        routePath: document.routes?.find((route) => route.id === item.route_id)
          ?.path,
        settingsSectionId: item.settings_section_id,
        action: document.actions.find((action) => action.id === item.action_id),
        label: item.label,
        icon: item.icon,
        order: item.order,
        adminOnly: item.visibility.admin_only,
        document,
      })),
  ];
  const settings = hasCapability(plugin, "frontend.settings")
    ? (document.settings_sections ?? []).map((item) => ({
        pluginId: plugin.plugin_id,
        contributionId: item.id,
        pageId: item.page_id,
        label: item.label,
        icon: item.icon,
        order: item.order,
        adminOnly: item.visibility.admin_only,
        document,
      }))
    : [];
  const slots = (document.extensions ?? []).flatMap((extension) => {
    if (!hasCapability(plugin, extensionCapability(extension.slot))) return [];
    const page = document.pages.find((item) => item.id === extension.page_id);
    return page
      ? [
          {
            pluginId: plugin.plugin_id,
            extensionId: extension.id,
            slot: extension.slot,
            page,
            order: extension.order,
            document,
          },
        ]
      : [];
  });
  const overlays = hasCapability(plugin, "frontend.overlay")
    ? (document.overlays ?? []).flatMap((item) => {
        const page = document.pages.find(
          (candidate) => candidate.id === item.page_id,
        );
        return page
          ? [
              {
                pluginId: plugin.plugin_id,
                contributionId: item.id,
                page,
                order: item.order,
                document,
              },
            ]
          : [];
      })
    : [];
  const dialogs = hasCapability(plugin, "frontend.dialog")
    ? (document.dialog_contributions ?? []).flatMap((item) => {
        const dialog = document.dialogs.find(
          (candidate) => candidate.id === item.dialog_id,
        );
        return dialog
          ? [
              {
                pluginId: plugin.plugin_id,
                contributionId: item.id,
                dialog,
                document,
              },
            ]
          : [];
      })
    : [];
  const contextualActions = (document.contextual_actions ?? []).flatMap(
    (item) => {
      const capability = {
        game: "frontend.context.game",
        media: "frontend.context.media",
        documents: "frontend.context.documents",
      }[item.location];
      const action = document.actions.find(
        (candidate) => candidate.id === item.action_id,
      );
      return hasCapability(plugin, capability) && action
        ? [
            {
              pluginId: plugin.plugin_id,
              contributionId: item.id,
              location: item.location,
              label: item.label,
              action,
              icon: item.icon,
              order: item.order,
              document,
            },
          ]
        : [];
    },
  );
  const routes = hasCapability(plugin, "frontend.routes")
    ? (document.routes ?? []).flatMap((item) => {
        const page = document.pages.find(
          (candidate) => candidate.id === item.page_id,
        );
        return page
          ? [
              {
                pluginId: plugin.plugin_id,
                contributionId: item.id,
                path: item.path,
                page,
                document,
              },
            ]
          : [];
      })
    : [];
  const replacements = (document.page_replacements ?? []).flatMap((item) => {
    const capability = `frontend.page.replace.${item.page}`;
    const page = document.pages.find(
      (candidate) => candidate.id === item.page_id,
    );
    return hasCapability(plugin, capability) && page
      ? [
          {
            pluginId: plugin.plugin_id,
            contributionId: item.id,
            hostPage: item.page,
            page,
            order: item.order,
            document,
          },
        ]
      : [];
  });
  return {
    navigation,
    settings,
    slots,
    overlays,
    dialogs,
    contextualActions,
    routes,
    replacements,
  };
}

const navigationState = ref<PluginNavigationContribution[]>([]);
const settingsState = ref<PluginSettingsContribution[]>([]);
const slotState = ref<PluginSlotContribution[]>([]);
const overlayState = ref<PluginOverlayContribution[]>([]);
const dialogState = ref<PluginDialogContribution[]>([]);
const contextualActionState = ref<PluginContextualActionContribution[]>([]);
const routeState = ref<PluginRouteContribution[]>([]);
const replacementState = ref<PluginPageReplacementContribution[]>([]);
let loading: Promise<void> | null = null;

export const pluginNavigation = shallowReadonly(navigationState);
export const pluginSettingsSections = shallowReadonly(settingsState);
export const pluginSlots = shallowReadonly(slotState);
export const pluginOverlays = shallowReadonly(overlayState);
export const pluginDialogs = shallowReadonly(dialogState);
export const pluginContextualActions = shallowReadonly(contextualActionState);
export const pluginRoutes = shallowReadonly(routeState);
export const pluginPageReplacements = shallowReadonly(replacementState);

export function comparePluginContributions(
  first: { order: number; pluginId: string; contributionId: string },
  second: { order: number; pluginId: string; contributionId: string },
): number {
  return (
    first.order - second.order ||
    first.pluginId.localeCompare(second.pluginId) ||
    first.contributionId.localeCompare(second.contributionId)
  );
}

export function refreshPluginExtensions(): Promise<void> {
  if (loading) return loading;
  loading = (async () => {
    const plugins = await fetchPlugins();
    const enabled = plugins.filter(
      (plugin) => plugin.enabled && plugin.compatible,
    );
    const loaded = await Promise.all(
      enabled.map(async (plugin) => {
        try {
          const document = await fetchPluginUi(plugin.plugin_id);
          return {
            document,
            contributions: derivePluginContributions(plugin, document),
          };
        } catch {
          return { document: undefined, contributions: emptyContributions() };
        }
      }),
    );
    const contributions = loaded.map((item) => item.contributions);
    await reconcileNativePlugins(
      enabled.flatMap((plugin, index) => {
        const document = loaded[index]?.document;
        const nativeFrontend = document?.native_frontend;
        return nativeFrontend && hasCapability(plugin, "frontend.native")
          ? [
              {
                pluginId: plugin.plugin_id,
                version: plugin.version,
                entry: nativeFrontend.entry,
                styles: nativeFrontend.styles,
                pageIds: document.pages.map((page) => page.id),
              },
            ]
          : [];
      }),
    );
    navigationState.value = contributions
      .flatMap((item) => item.navigation)
      .sort(comparePluginContributions);
    settingsState.value = contributions
      .flatMap((item) => item.settings)
      .sort(comparePluginContributions);
    const replacementSlots = contributions
      .flatMap((item) => item.replacements)
      .filter((item) => item.hostPage === "home")
      .map((item) => ({
        pluginId: item.pluginId,
        extensionId: item.contributionId,
        slot: "home.replace" as const,
        page: item.page,
        order: item.order,
        document: item.document,
      }));
    slotState.value = [
      ...contributions.flatMap((item) => item.slots),
      ...replacementSlots,
    ].sort(
      (a, b) =>
        a.order - b.order ||
        a.pluginId.localeCompare(b.pluginId) ||
        a.extensionId.localeCompare(b.extensionId),
    );
    overlayState.value = contributions
      .flatMap((item) => item.overlays)
      .sort(comparePluginContributions);
    dialogState.value = contributions.flatMap((item) => item.dialogs);
    if (
      activeDialogState.value &&
      !dialogState.value.some(
        (item) =>
          item.pluginId === activeDialogState.value?.pluginId &&
          item.contributionId === activeDialogState.value?.contributionId,
      )
    )
      activeDialogState.value = null;
    contextualActionState.value = contributions
      .flatMap((item) => item.contextualActions)
      .sort(comparePluginContributions);
    routeState.value = contributions.flatMap((item) => item.routes);
    replacementState.value = contributions
      .flatMap((item) => item.replacements)
      .sort(comparePluginContributions);
  })().finally(() => {
    loading = null;
  });
  return loading;
}

const activeDialogState = ref<PluginDialogContribution | null>(null);
export const activePluginDialog = shallowReadonly(activeDialogState);

export function openPluginDialog(
  pluginId: string,
  contributionId: string,
): boolean {
  const contribution = dialogState.value.find(
    (item) =>
      item.pluginId === pluginId && item.contributionId === contributionId,
  );
  activeDialogState.value = contribution ?? null;
  return contribution !== undefined;
}

export function closePluginDialog(): void {
  activeDialogState.value = null;
}

export function pageReplacement(
  hostPage: "home" | "settings",
): PluginPageReplacementContribution | undefined {
  return replacementState.value.find((item) => item.hostPage === hostPage);
}

export function pageReplacementConflicts(
  hostPage: "home" | "settings",
): PluginPageReplacementContribution[] {
  return replacementState.value.filter((item) => item.hostPage === hostPage);
}
