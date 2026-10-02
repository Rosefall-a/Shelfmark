import { ref, shallowReadonly } from "vue";
import {
  fetchPlugins,
  pluginContributionsActive,
  type PluginSummary,
} from "../services/plugins";
import {
  fetchPluginUi,
  type HostExtensionSlot,
  type PluginUiDocument,
  type UiAction,
  type UiDialog,
  type UiNavigationLocation,
  type UiPage,
} from "../services/pluginUi";
import { reconcileNativePlugins, retainNativePlugins } from "./pluginNative";

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
  documentReaders: PluginDocumentReaderContribution[];
}

export interface PluginDocumentReaderContribution {
  pluginId: string;
  contributionId: string;
  pageId: string;
  label: string;
  extensions: string[];
  order: number;
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
  documentReaders: [],
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
    !pluginContributionsActive(plugin) ||
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
    documentReaders:
      hasCapability(plugin, "frontend.context.documents") &&
      hasCapability(plugin, "documents.read")
        ? (document.document_readers ?? [])
            .filter((item) =>
              document.pages.some((page) => page.id === item.page_id),
            )
            .map((item) => ({
              pluginId: plugin.plugin_id,
              contributionId: item.id,
              pageId: item.page_id,
              label: item.label,
              extensions: item.extensions,
              order: item.order,
            }))
        : [],
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
const documentReaderState = ref<PluginDocumentReaderContribution[]>([]);
let refreshVersion = 0;
const documentState = ref<Record<string, PluginUiDocument>>({});
export const activePluginDocuments = shallowReadonly(documentState);

function retainContributions(pluginIds: ReadonlySet<string>): void {
  navigationState.value = navigationState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  settingsState.value = settingsState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  slotState.value = slotState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  overlayState.value = overlayState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  dialogState.value = dialogState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  contextualActionState.value = contextualActionState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  routeState.value = routeState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  replacementState.value = replacementState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  documentReaderState.value = documentReaderState.value.filter((item) =>
    pluginIds.has(item.pluginId),
  );
  documentState.value = Object.fromEntries(
    Object.entries(documentState.value).filter(([id]) => pluginIds.has(id)),
  );
  if (
    activeDialogState.value &&
    !pluginIds.has(activeDialogState.value.pluginId)
  )
    activeDialogState.value = null;
  retainNativePlugins(pluginIds);
}

export function clearPluginExtensions(): void {
  refreshVersion++;
  retainContributions(new Set());
}

function compareIds(first: string, second: string): number {
  return first < second ? -1 : first > second ? 1 : 0;
}

export const pluginNavigation = shallowReadonly(navigationState);
export const pluginSettingsSections = shallowReadonly(settingsState);
export const pluginSlots = shallowReadonly(slotState);
export const pluginOverlays = shallowReadonly(overlayState);
export const pluginDialogs = shallowReadonly(dialogState);
export const pluginContextualActions = shallowReadonly(contextualActionState);
export const pluginRoutes = shallowReadonly(routeState);
export const pluginPageReplacements = shallowReadonly(replacementState);
export const pluginDocumentReaders = shallowReadonly(documentReaderState);

export function documentReaderUrl(
  gameId: string,
  file: { id?: string; filename: string },
): string | undefined {
  if (!file.id) return;
  const suffix = file.filename
    .slice(file.filename.lastIndexOf("."))
    .toLowerCase();
  const reader = documentReaderState.value.find(
    (item) => item.extensions.includes("*") || item.extensions.includes(suffix),
  );
  if (!reader) return;
  const query = new URLSearchParams({ document_id: file.id, game_id: gameId });
  return `/plugins/${encodeURIComponent(reader.pluginId)}/${encodeURIComponent(reader.pageId)}?${query}`;
}

export function comparePluginContributions(
  first: { order: number; pluginId: string; contributionId: string },
  second: { order: number; pluginId: string; contributionId: string },
): number {
  return (
    first.order - second.order ||
    compareIds(first.pluginId, second.pluginId) ||
    compareIds(first.contributionId, second.contributionId)
  );
}

export async function refreshPluginExtensions(): Promise<void> {
  const version = ++refreshVersion;
  try {
    const plugins = await fetchPlugins();
    if (version !== refreshVersion) return;
    const enabled = plugins
      .filter(pluginContributionsActive)
      .sort((a, b) => compareIds(a.plugin_id, b.plugin_id));
    retainContributions(new Set(enabled.map((plugin) => plugin.plugin_id)));
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
    if (version !== refreshVersion) return;
    const contributions = loaded.map((item) => item.contributions);
    documentState.value = Object.fromEntries(
      loaded.flatMap((item) =>
        item.document ? [[item.document.plugin_id, item.document]] : [],
      ),
    );
    const nativeSources = enabled.flatMap((plugin, index) => {
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
              actions: document.actions,
            },
          ]
        : [];
    });
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
        extensionId: `replacement:${item.contributionId}`,
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
        compareIds(a.pluginId, b.pluginId) ||
        compareIds(a.extensionId, b.extensionId),
    );
    overlayState.value = contributions
      .flatMap((item) => item.overlays)
      .sort(comparePluginContributions);
    dialogState.value = contributions
      .flatMap((item) => item.dialogs)
      .sort(
        (a, b) =>
          compareIds(a.pluginId, b.pluginId) ||
          compareIds(a.contributionId, b.contributionId),
      );
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
    routeState.value = contributions
      .flatMap((item) => item.routes)
      .sort(
        (a, b) =>
          compareIds(a.pluginId, b.pluginId) ||
          compareIds(a.path, b.path) ||
          compareIds(a.contributionId, b.contributionId),
      );
    replacementState.value = contributions
      .flatMap((item) => item.replacements)
      .sort(comparePluginContributions);
    documentReaderState.value = contributions
      .flatMap((item) => item.documentReaders)
      .sort(comparePluginContributions);
    // Publish lifecycle removal before waiting on privileged plugin code.
    await reconcileNativePlugins(nativeSources);
  } catch {
    if (version === refreshVersion) clearPluginExtensions();
  }
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
