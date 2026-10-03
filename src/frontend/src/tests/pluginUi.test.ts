import { describe, expect, it } from "vitest";
import {
  approvePluginAction,
  buildInitialValues,
  validateDocument,
  validateField,
  pluginPathForPage,
  resolvePluginPageId,
  type PluginUiDocument,
} from "../services/pluginUi";

const document: PluginUiDocument = {
  schema_version: "v1",
  plugin_id: "example.plugin",
  title: "Example",
  settings: [
    {
      id: "general",
      title: "General",
      description: "",
      fields: [
        {
          id: "token",
          label: "Token",
          type: "password",
          description: "",
          required: true,
          secret: true,
          options: [],
        },
      ],
    },
  ],
  actions: [],
  tables: [],
  dialogs: [],
  menus: [],
  pages: [
    {
      id: "settings",
      title: "Settings",
      description: "",
      settings: ["general"],
      actions: [],
      tables: [],
      dialogs: [],
    },
  ],
};

describe("plugin UI host contract", () => {
  it("rejects duplicate navigation IDs, extension IDs and route paths in either order", () => {
    const first = { ...document.pages[0]!, id: "first" };
    const second = { ...document.pages[0]!, id: "second" };
    for (const pageIds of [
      [first.id, second.id],
      [second.id, first.id],
    ]) {
      const conflicting = {
        ...document,
        pages: [first, second],
        navigation: pageIds.map((page_id) => ({
          id: "same",
          location: "main.sidebar" as const,
          label: page_id,
          page_id,
          order: 0,
          visibility: { admin_only: false },
        })),
        extensions: pageIds.map((page_id) => ({
          id: "same",
          slot: "home.after-widgets" as const,
          page_id,
          order: 0,
        })),
        routes: pageIds.map((page_id) => ({
          id: page_id,
          path: "same-path",
          page_id,
        })),
      };
      expect(validateDocument(conflicting)).toContain(
        "Navigation same is declared more than once.",
      );
      expect(validateDocument(conflicting)).toContain(
        "Extension same is declared more than once.",
      );
      expect(validateDocument(conflicting)).toContain(
        "Plugin route same-path is ambiguous.",
      );
    }
  });

  it("chooses route aliases lexically regardless of document order", () => {
    const aliases = [
      { id: "z", path: "z-alias", page_id: "settings" },
      { id: "a", path: "a-alias", page_id: "settings" },
    ];
    expect(
      pluginPathForPage({ ...document, routes: aliases }, "settings"),
    ).toBe("a-alias");
    expect(
      pluginPathForPage(
        { ...document, routes: [...aliases].reverse() },
        "settings",
      ),
    ).toBe("a-alias");
  });
  it("rejects dangling declarative references", () => {
    expect(
      validateDocument({
        ...document,
        menus: [{ id: "bad", label: "Bad", page_id: "missing" }],
      }),
    ).toHaveLength(1);
  });

  it("does not expose secret defaults", () => {
    expect(buildInitialValues(document)).toEqual({});
  });

  it("validates required fields", () => {
    expect(validateField(document.settings[0].fields[0], "")).toBe(
      "This field is required.",
    );
  });

  it("requires host confirmation for destructive actions", () => {
    const action = {
      id: "revoke-session",
      label: "Revoke",
      confirmation: "Revoke this session?",
    };
    expect(approvePluginAction(action, () => false)).toBe(false);
    expect(approvePluginAction(action, () => true)).toBe(true);
    expect(
      approvePluginAction({ id: "refresh", label: "Refresh" }, () => false),
    ).toBe(true);
  });

  it("rejects incorrect select and multiselect value shapes", () => {
    const select = {
      ...document.settings[0].fields[0],
      type: "select" as const,
      secret: false,
      required: false,
      options: [{ value: "one", label: "One" }],
    };
    const multiselect = { ...select, type: "multiselect" as const };
    expect(validateField(select, ["one"])).toBe("Select one permitted option.");
    expect(validateField(multiselect, "one")).toBe(
      "Select one or more permitted options.",
    );
  });

  it("does not crash on an invalid regex rule", () => {
    const field = {
      ...document.settings[0].fields[0],
      secret: false,
      required: false,
      validation: { pattern: "[" },
    };
    expect(validateField(field, "value")).toBe(
      "Value has an invalid format rule.",
    );
  });

  it("allows only known host extension slots and declared pages", () => {
    expect(
      validateDocument({
        ...document,
        extensions: [
          {
            id: "home-summary",
            slot: "home.after-widgets",
            page_id: "settings",
            order: 0,
          },
        ],
      }),
    ).toEqual([]);

    expect(
      validateDocument({
        ...document,
        extensions: [
          {
            id: "missing-page",
            slot: "home.after-widgets",
            page_id: "missing",
            order: 0,
          },
        ],
      }),
    ).toContain("Extension missing-page references an unknown page.");
  });

  it("keeps plugin routes distinct from host Settings sections", () => {
    const routed: PluginUiDocument = {
      ...document,
      routes: [{ id: "sessions-route", path: "sessions", page_id: "settings" }],
      settings_sections: [
        {
          id: "sessions",
          label: "Sessions",
          page_id: "settings",
          order: 0,
          visibility: { admin_only: false },
        },
      ],
    };

    expect(resolvePluginPageId(routed, "sessions")).toBe("settings");
    expect(pluginPathForPage(routed, "settings")).toBe("sessions");
    expect(routed.settings_sections?.[0].id).toBe("sessions");
  });
});
