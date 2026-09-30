import { describe, expect, it } from "vitest";
import {
  approvePluginAction,
  buildInitialValues,
  validateDocument,
  validateField,
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
});
