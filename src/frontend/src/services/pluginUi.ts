export type UiFieldType =
  | "text"
  | "textarea"
  | "password"
  | "number"
  | "boolean"
  | "select"
  | "multiselect";

export interface UiOption {
  value: string;
  label: string;
}
export interface UiValidation {
  pattern?: string;
  min_length?: number;
  max_length?: number;
  minimum?: number;
  maximum?: number;
}
export interface UiField {
  id: string;
  label: string;
  type: UiFieldType;
  description: string;
  required: boolean;
  secret: boolean;
  default?: string | number | boolean | string[];
  options: UiOption[];
  validation?: UiValidation;
}
export interface UiSettingsSection {
  id: string;
  title: string;
  description: string;
  fields: UiField[];
}
export interface UiAction {
  id: string;
  label: string;
  handler?: string;
  capability?: { name: string; version: number };
  confirmation?: string;
  external_navigation?: boolean;
}
export interface UiTableColumn {
  id: string;
  label: string;
}
export interface UiTable {
  id: string;
  title: string;
  columns: UiTableColumn[];
  empty_message: string;
}
export interface UiDialog {
  id: string;
  title: string;
  body: string;
  actions: string[];
}
export interface UiMenuItem {
  id: string;
  label: string;
  page_id?: string;
  action_id?: string;
}
export interface UiPage {
  id: string;
  title: string;
  description: string;
  settings: string[];
  actions: string[];
  tables: string[];
  dialogs: string[];
  navigation?: {
    sidebar: boolean;
    label?: string;
    order: number;
  };
}
export type UiNavigationLocation =
  | "main.sidebar"
  | "settings.sidebar"
  | "administration"
  | "game.context"
  | "media.context";
export interface UiVisibility {
  admin_only: boolean;
}
export interface UiNavigationContribution {
  id: string;
  location: UiNavigationLocation;
  label: string;
  page_id?: string;
  route_id?: string;
  settings_section_id?: string;
  action_id?: string;
  icon?: string;
  order: number;
  visibility: UiVisibility;
}
export interface UiSettingsContribution {
  id: string;
  label: string;
  page_id: string;
  icon?: string;
  order: number;
  visibility: UiVisibility;
}
export interface UiOverlayContribution {
  id: string;
  page_id: string;
  order: number;
}
export interface UiDialogContribution {
  id: string;
  dialog_id: string;
}
export interface UiContextualAction {
  id: string;
  location: "game" | "media" | "documents";
  label: string;
  action_id: string;
  icon?: string;
  order: number;
}
export interface UiPluginRoute {
  id: string;
  path: string;
  page_id: string;
}
export interface UiPageReplacement {
  id: string;
  page: "home" | "settings";
  page_id: string;
  order: number;
}
export const HOST_EXTENSION_SLOTS = [
  "home.after-widgets",
  "game.overview.after-header",
  "game.documents.actions",
  "media.detail.after-header",
  "app.global",
  "home.replace",
] as const;
export type HostExtensionSlot = (typeof HOST_EXTENSION_SLOTS)[number];
export interface UiExtension {
  id: string;
  slot: HostExtensionSlot;
  page_id: string;
  order: number;
}
export interface PluginUiDocument {
  schema_version: "v1";
  frontend?: { entry: string };
  native_frontend?: { entry: string; styles: string[] };
  plugin_id: string;
  title: string;
  settings: UiSettingsSection[];
  actions: UiAction[];
  tables: UiTable[];
  dialogs: UiDialog[];
  menus: UiMenuItem[];
  pages: UiPage[];
  extensions?: UiExtension[];
  navigation?: UiNavigationContribution[];
  settings_sections?: UiSettingsContribution[];
  overlays?: UiOverlayContribution[];
  dialog_contributions?: UiDialogContribution[];
  contextual_actions?: UiContextualAction[];
  routes?: UiPluginRoute[];
  page_replacements?: UiPageReplacement[];
}

export type UiValue = string | number | boolean | string[];
export type UiValues = Record<string, UiValue>;
export interface PluginActionContext {
  kind: "game" | "media" | "documents";
  resource_id: string;
  resource_type?: string;
}

export async function dispatchPluginAction(
  pluginId: string,
  actionId: string,
  values: Record<string, unknown> = {},
  context?: PluginActionContext,
  confirmed = false,
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(pluginId)}/actions/${encodeURIComponent(actionId)}`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values, context, confirmed }),
    },
  );
  if (!response.ok) throw new Error("Plugin action could not be completed.");
  return (await response.json()) as Record<string, unknown>;
}

export function approvePluginAction(
  action: UiAction,
  confirm: (message: string) => boolean,
): boolean {
  return !action.confirmation || confirm(action.confirmation);
}

export function validateField(
  field: UiField,
  value: UiValue | undefined,
): string | null {
  if (field.secret && value === undefined) return null;
  if (
    field.required &&
    (value === undefined ||
      value === "" ||
      (Array.isArray(value) && value.length === 0))
  ) {
    return "This field is required.";
  }
  if (value === undefined || value === "") return null;
  if (field.type === "number" && typeof value !== "number")
    return "Enter a number.";
  if (field.type === "boolean" && typeof value !== "boolean")
    return "Enter a boolean value.";
  if (field.type === "select") {
    if (typeof value !== "string") return "Select one permitted option.";
    if (!field.options.some((option) => option.value === value))
      return "Select a permitted option.";
  }
  if (field.type === "multiselect") {
    if (
      !Array.isArray(value) ||
      value.some((item) => typeof item !== "string")
    ) {
      return "Select one or more permitted options.";
    }
    if (
      value.some(
        (item) => !field.options.some((option) => option.value === item),
      )
    ) {
      return "Select a permitted option.";
    }
  }
  if (
    field.validation?.min_length !== undefined &&
    typeof value === "string" &&
    value.length < field.validation.min_length
  ) {
    return "Value is too short.";
  }
  if (
    field.validation?.max_length !== undefined &&
    typeof value === "string" &&
    value.length > field.validation.max_length
  ) {
    return "Value is too long.";
  }
  if (
    field.validation?.minimum !== undefined &&
    typeof value === "number" &&
    value < field.validation.minimum
  ) {
    return "Value is too small.";
  }
  if (
    field.validation?.maximum !== undefined &&
    typeof value === "number" &&
    value > field.validation.maximum
  ) {
    return "Value is too large.";
  }
  if (field.validation?.pattern !== undefined && typeof value === "string") {
    try {
      if (!new RegExp(field.validation.pattern).test(value))
        return "Value has an invalid format.";
    } catch {
      return "Value has an invalid format rule.";
    }
  }
  return null;
}

export function validateDocument(document: PluginUiDocument): string[] {
  if (document.schema_version !== "v1")
    return ["Unsupported plugin UI schema version."];
  const errors: string[] = [];
  const settings = new Set(document.settings.map((item) => item.id));
  const actions = new Set(document.actions.map((item) => item.id));
  const tables = new Set(document.tables.map((item) => item.id));
  const dialogs = new Set(document.dialogs.map((item) => item.id));
  const pages = new Set(document.pages.map((item) => item.id));
  const extensions = document.extensions ?? [];
  const navigation = document.navigation ?? [];
  const settingsSections = document.settings_sections ?? [];
  const overlays = document.overlays ?? [];
  const dialogContributions = document.dialog_contributions ?? [];
  const contextualActions = document.contextual_actions ?? [];
  const routes = document.routes ?? [];
  const pageReplacements = document.page_replacements ?? [];
  const routePaths = new Set<string>();
  for (const route of routes) {
    if (
      routePaths.has(route.path) ||
      route.path.split("/").some((part) => !part)
    )
      errors.push(`Plugin route ${route.path} is ambiguous.`);
    if (pages.has(route.path) && route.page_id !== route.path)
      errors.push(
        `Plugin route ${route.path} conflicts with a page identifier.`,
      );
    routePaths.add(route.path);
  }
  const groups: Array<[string, Array<{ id: string }>]> = [
    ["Setting", document.settings],
    ["Action", document.actions],
    ["Table", document.tables],
    ["Dialog", document.dialogs],
    ["Menu", document.menus],
    ["Page", document.pages],
    ["Extension", extensions],
    ["Navigation", navigation],
    ["Settings contribution", settingsSections],
    ["Overlay", overlays],
    ["Dialog contribution", dialogContributions],
    ["Contextual action", contextualActions],
    ["Route", routes],
    ["Page replacement", pageReplacements],
  ];
  for (const [kind, items] of groups) {
    const ids = new Set<string>();
    for (const item of items) {
      if (ids.has(item.id))
        errors.push(`${kind} ${item.id} is declared more than once.`);
      ids.add(item.id);
    }
  }

  for (const menu of document.menus) {
    if (menu.page_id && !pages.has(menu.page_id))
      errors.push(`Menu ${menu.id} references an unknown page.`);
    if (menu.action_id && !actions.has(menu.action_id))
      errors.push(`Menu ${menu.id} references an unknown action.`);
    if ((menu.page_id ? 1 : 0) + (menu.action_id ? 1 : 0) !== 1)
      errors.push(`Menu ${menu.id} must target exactly one page or action.`);
  }
  for (const page of document.pages) {
    for (const id of page.settings)
      if (!settings.has(id))
        errors.push(`Page ${page.id} references an unknown setting.`);
    for (const id of page.actions)
      if (!actions.has(id))
        errors.push(`Page ${page.id} references an unknown action.`);
    for (const id of page.tables)
      if (!tables.has(id))
        errors.push(`Page ${page.id} references an unknown table.`);
    for (const id of page.dialogs)
      if (!dialogs.has(id))
        errors.push(`Page ${page.id} references an unknown dialog.`);
  }
  for (const extension of extensions) {
    if (!HOST_EXTENSION_SLOTS.includes(extension.slot))
      errors.push(`Extension ${extension.id} uses an unsupported host slot.`);
    if (!pages.has(extension.page_id))
      errors.push(`Extension ${extension.id} references an unknown page.`);
    if (extension.order < -1000 || extension.order > 1000)
      errors.push(`Extension ${extension.id} has an invalid order.`);
  }
  for (const contribution of [
    ...settingsSections,
    ...overlays,
    ...routes,
    ...pageReplacements,
  ]) {
    if (!pages.has(contribution.page_id))
      errors.push(
        `Contribution ${contribution.id} references an unknown page.`,
      );
  }
  const routeIds = new Set(routes.map((item) => item.id));
  const settingsSectionIds = new Set(settingsSections.map((item) => item.id));
  for (const contribution of navigation) {
    const targets = [
      contribution.page_id,
      contribution.route_id,
      contribution.settings_section_id,
      contribution.action_id,
    ].filter(Boolean);
    if (targets.length !== 1)
      errors.push(
        `Navigation ${contribution.id} must target exactly one destination.`,
      );
    if (contribution.page_id && !pages.has(contribution.page_id))
      errors.push(`Navigation ${contribution.id} references an unknown page.`);
    if (contribution.route_id && !routeIds.has(contribution.route_id))
      errors.push(
        `Navigation ${contribution.id} references an unknown plugin route.`,
      );
    if (
      contribution.settings_section_id &&
      !settingsSectionIds.has(contribution.settings_section_id)
    )
      errors.push(
        `Navigation ${contribution.id} references an unknown Settings section.`,
      );
    if (contribution.action_id && !actions.has(contribution.action_id))
      errors.push(
        `Navigation ${contribution.id} references an unknown action.`,
      );
  }
  for (const contribution of dialogContributions) {
    if (!dialogs.has(contribution.dialog_id))
      errors.push(
        `Dialog contribution ${contribution.id} references an unknown dialog.`,
      );
  }
  for (const contribution of contextualActions) {
    if (!actions.has(contribution.action_id))
      errors.push(
        `Contextual action ${contribution.id} references an unknown action.`,
      );
  }
  return errors;
}

export async function fetchPluginUi(
  pluginId: string,
): Promise<PluginUiDocument> {
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(pluginId)}/ui`,
    { credentials: "include" },
  );
  if (!response.ok)
    throw new Error(`Plugin UI unavailable (${response.status}).`);
  const document = (await response.json()) as PluginUiDocument;
  const errors = validateDocument(document);
  if (errors.length)
    throw new Error("Plugin UI document is invalid: " + errors.join(" "));
  return document;
}

export function resolvePluginPageId(
  document: PluginUiDocument,
  requestedPath?: string,
): string | undefined {
  if (!requestedPath) return document.pages[0]?.id;
  const declaredRoute = document.routes?.find(
    (route) => route.path === requestedPath,
  );
  if (declaredRoute) return declaredRoute.page_id;
  return document.pages.some((page) => page.id === requestedPath)
    ? requestedPath
    : undefined;
}

export function pluginPathForPage(
  document: PluginUiDocument,
  pageId: string,
): string {
  return (
    document.routes
      ?.filter((route) => route.page_id === pageId)
      .map((route) => route.path)
      .sort()[0] ?? pageId
  );
}

export function buildInitialValues(document: PluginUiDocument): UiValues {
  const values: UiValues = {};
  for (const section of document.settings) {
    for (const field of section.fields) {
      if (field.default !== undefined && !field.secret)
        values[field.id] = field.default;
    }
  }
  return values;
}
