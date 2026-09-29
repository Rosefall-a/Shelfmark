import { ref, shallowReadonly } from "vue";
import { fetchPlugins, type PluginSummary } from "../services/plugins";
import {
  fetchPluginUi,
  type HostExtensionSlot,
  type PluginUiDocument,
  type UiPage,
} from "../services/pluginUi";

export interface PluginNavigationContribution {
  pluginId: string;
  pageId: string;
  label: string;
  order: number;
}

export interface PluginSlotContribution {
  pluginId: string;
  extensionId: string;
  slot: HostExtensionSlot;
  page: UiPage;
  order: number;
  document: PluginUiDocument;
}

export interface PluginContributions {
  navigation: PluginNavigationContribution[];
  slots: PluginSlotContribution[];
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
    return { navigation: [], slots: [] };

  const navigation = document.pages
    .filter((page) => page.navigation?.sidebar)
    .map((page) => ({
      pluginId: plugin.plugin_id,
      pageId: page.id,
      label: page.navigation?.label ?? page.title,
      order: page.navigation?.order ?? 0,
    }));
  const slots = (document.extensions ?? []).flatMap((extension) => {
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
  return { navigation, slots };
}

const navigationState = ref<PluginNavigationContribution[]>([]);
const slotState = ref<PluginSlotContribution[]>([]);
let loading: Promise<void> | null = null;

export const pluginNavigation = shallowReadonly(navigationState);
export const pluginSlots = shallowReadonly(slotState);

export function refreshPluginExtensions(): Promise<void> {
  if (loading) return loading;
  loading = (async () => {
    const plugins = await fetchPlugins();
    const enabled = plugins.filter(
      (plugin) => plugin.enabled && plugin.compatible,
    );
    const contributions = await Promise.all(
      enabled.map(async (plugin) => {
        try {
          return derivePluginContributions(
            plugin,
            await fetchPluginUi(plugin.plugin_id),
          );
        } catch {
          return { navigation: [], slots: [] } satisfies PluginContributions;
        }
      }),
    );
    navigationState.value = contributions
      .flatMap((item) => item.navigation)
      .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
    slotState.value = contributions
      .flatMap((item) => item.slots)
      .sort(
        (a, b) =>
          a.order - b.order || a.extensionId.localeCompare(b.extensionId),
      );
  })().finally(() => {
    loading = null;
  });
  return loading;
}
