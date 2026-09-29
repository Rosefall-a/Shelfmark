import { describe, expect, it } from "vitest";
import { buildInitialValues, validateDocument, validateField, type PluginUiDocument } from "../services/pluginUi";

const document: PluginUiDocument = {
  schema_version: "v1",
  plugin_id: "example.plugin",
  title: "Example",
  settings: [{
    id: "general",
    title: "General",
    description: "",
    fields: [{
      id: "token",
      label: "Token",
      type: "password",
      description: "",
      required: true,
      secret: true,
      options: [],
    }],
  }],
  actions: [],
  tables: [],
  dialogs: [],
  menus: [],
  pages: [{ id: "settings", title: "Settings", description: "", settings: ["general"], actions: [], tables: [], dialogs: [] }],
};

describe("plugin UI host contract", () => {
  it("rejects dangling declarative references", () => {
    expect(validateDocument({ ...document, menus: [{ id: "bad", label: "Bad", page_id: "missing" }] })).toHaveLength(1);
  });

  it("does not expose secret defaults", () => {
    expect(buildInitialValues(document)).toEqual({});
  });

  it("validates required fields", () => {
    expect(validateField(document.settings[0].fields[0], "")).toBe("This field is required.");
  });
});
