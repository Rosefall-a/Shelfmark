import { afterEach, expect, it, vi } from "vitest";
import * as Vue from "vue";
import {
  createRenderer,
  defineComponent,
  h,
  nextTick,
  onUnmounted,
  ssrContextKey,
} from "vue";
import { compileScript, compileTemplate, parse } from "vue/compiler-sfc";
import {
  createMemoryHistory,
  createRouter,
  RouterView,
  useRoute,
} from "vue-router";
import PluginContributionHost from "../components/plugins/PluginContributionHost.vue";
import contributionHostSource from "../components/plugins/PluginContributionHost.vue?raw";
import {
  dispatchPluginAction,
  type PluginUiDocument,
} from "../services/pluginUi";
import {
  reconcileNativePlugins,
  resetNativePluginsForTests,
  type NativePluginContext,
} from "../state/pluginNative";

vi.mock("../state/pluginExtensions", async () => {
  const { shallowRef } = await import("vue");
  return { activePluginDocuments: shallowRef({ "test.page-switch": {} }) };
});
vi.mock("../services/pluginUi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../services/pluginUi")>()),
  dispatchPluginAction: vi.fn(async () => ({ completed: true })),
}));
vi.mock("../components/plugins/PluginUiHost.vue", () => ({
  default: { render: () => null },
}));

// Vitest's Node environment imports SFCs in SSR mode. Use the real template's
// client render function to exercise component reuse through the Vue renderer.
const { descriptor } = parse(contributionHostSource);
const { code } = compileTemplate({
  source: descriptor.template!.content,
  filename: "PluginContributionHost.vue",
  id: "page-switch-test",
  compilerOptions: {
    mode: "function",
    bindingMetadata: compileScript(descriptor, { id: "page-switch-test" })
      .bindings,
  },
});
Object.assign(PluginContributionHost, {
  render: new Function("Vue", code)(Vue),
});

// Exercise the actual Vue component/router in Node without a browser dependency.
interface MemoryNode {
  type: string;
  text: string;
  props: Record<string, unknown>;
  children: MemoryNode[];
  parent: MemoryNode | null;
}
const node = (type: string, text = ""): MemoryNode => ({
  type,
  text,
  props: {},
  children: [],
  parent: null,
});
function remove(child: MemoryNode) {
  const siblings = child.parent?.children;
  if (siblings) siblings.splice(siblings.indexOf(child), 1);
  child.parent = null;
}
const renderer = createRenderer<MemoryNode, MemoryNode>({
  createElement: (type) => node(type),
  createText: (text) => node("text", text),
  createComment: (text) => node("comment", text),
  setText: (target, text) => {
    target.text = text;
  },
  setElementText: (target, text) => {
    target.text = text;
    target.children = [];
  },
  patchProp: (target, key, _previous, value) => {
    target.props[key] = value;
  },
  insert(child, parent, anchor = null) {
    remove(child);
    child.parent = parent;
    const index = anchor
      ? parent.children.indexOf(anchor)
      : parent.children.length;
    parent.children.splice(index, 0, child);
  },
  remove,
  parentNode: (target) => target.parent,
  nextSibling: (target) => {
    const siblings = target.parent?.children;
    return siblings?.[siblings.indexOf(target) + 1] ?? null;
  },
});
const content = (target: MemoryNode): string =>
  target.text + target.children.map(content).join("");
const findButton = (target: MemoryNode): MemoryNode | undefined =>
  target.type === "button"
    ? target
    : target.children.map(findButton).find(Boolean);

afterEach(() => {
  resetNativePluginsForTests();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it.each(["overview", "audit"])(
  "switches shared native pages from %s and back without reloading",
  async (first) => {
    const second = first === "overview" ? "audit" : "overview";
    const reload = vi.fn();
    vi.stubGlobal("window", { confirm: vi.fn(), location: { reload } });
    const mounted: string[] = [],
      disposed: string[] = [];
    const document: PluginUiDocument = {
      schema_version: "v1",
      plugin_id: "test.page-switch",
      title: "Page switch",
      settings: [],
      tables: [],
      dialogs: [],
      menus: [],
      actions: ["overview", "audit"].flatMap((page) => [
        { id: `read-${page}`, label: `Read ${page}` },
        { id: `perform-${page}`, label: `Use ${page}` },
      ]),
      pages: ["overview", "audit"].map((id) => ({
        id,
        title: id,
        description: "",
        settings: [],
        actions: [],
        tables: [],
        dialogs: [],
      })),
    };
    // Two page IDs deliberately share one component with page-local setup state.
    const sharedPage = defineComponent({
      props: ["pageId", "host"],
      setup(props) {
        const initialPage = String(props.pageId);
        mounted.push(initialPage);
        onUnmounted(() => disposed.push(initialPage));
        void props.host.runAction(`read-${initialPage}`);
        return () =>
          h(
            "button",
            {
              onClick: () => props.host.runAction(`perform-${initialPage}`),
            },
            `View ${initialPage}`,
          );
      },
    });
    const importer = vi.fn(async () => ({
      activate(context: NativePluginContext) {
        context.registerComponent("overview", sharedPage);
        context.registerComponent("audit", sharedPage);
      },
    }));
    await reconcileNativePlugins(
      [
        {
          pluginId: document.plugin_id,
          version: "1.0.0",
          entry: "native/index.js",
          styles: [],
          pageIds: ["overview", "audit"],
        },
      ],
      importer,
    );
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: "/settings",
          component: defineComponent({
            setup() {
              const route = useRoute();
              return () =>
                h(PluginContributionHost, {
                  pluginId: document.plugin_id,
                  document,
                  pageId: String(route.query.section),
                  embedded: true,
                });
            },
          }),
        },
      ],
    });
    await router.push(`/settings?section=${first}`);
    const root = node("root");
    const app = renderer.createApp({ render: () => h(RouterView) });
    app.provide(ssrContextKey, { modules: new Set<string>() });
    app.use(router);
    app.mount(root);
    try {
      await nextTick();
      expect(content(root)).toContain(`View ${first}`);
      await router.push(`/settings?section=${second}`);
      await nextTick();
      expect(content(root)).toContain(`View ${second}`);
      expect(mounted).toEqual([first, second]);
      expect(disposed).toEqual([first]);
      await (findButton(root)!.props.onClick as () => Promise<unknown>)();
      expect(dispatchPluginAction).toHaveBeenLastCalledWith(
        document.plugin_id,
        `perform-${second}`,
        {},
        undefined,
        false,
      );
      await router.push(`/settings?section=${first}`);
      await nextTick();
      expect(content(root)).toContain(`View ${first}`);
      expect(mounted).toEqual([first, second, first]);
      expect(disposed).toEqual([first, second]);
      await router.replace({ query: { section: first, filter: "changed" } });
      await nextTick();
      expect(mounted).toHaveLength(3);
      expect(importer).toHaveBeenCalledOnce();
      expect(reload).not.toHaveBeenCalled();
    } finally {
      app.unmount();
    }
  },
);
