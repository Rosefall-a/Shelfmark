export type PluginStatus =
  | "enabled"
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "completed"
  | "quarantined"
  | "failed"
  | "failed_start"
  | "failed_stop"
  | "disabled"
  | "unknown";
export function pluginContributionsActive(plugin: PluginSummary): boolean {
  return (
    plugin.enabled &&
    plugin.compatible &&
    plugin.status === "running" &&
    (plugin.health === "healthy" || plugin.health === "unknown")
  );
}
export interface PluginSummary {
  plugin_id: string;
  name: string;
  version: string;
  status: PluginStatus;
  compatible: boolean;
  compatibility_reason: string;
  health: "healthy" | "degraded" | "unhealthy" | "unknown";
  permissions: string[];
  permission_refs?: Array<{ name: string; version: number }>;
  granted_capabilities: string[];
  effective_capabilities: string[];
  enabled: boolean;
  source?: PluginSourceMetadata;
  trust?: Record<string, unknown>;
  description?: string;
  icon?: string | null;
  tags?: string[];
  publisher?: string | null;
  digest?: string;
  runtime_available?: boolean;
  runtime?: RuntimeCapabilities;
  last_error?: string | null;
  last_update_error?: string | null;
  available_update?: PluginUpdateCheck;
  staged_update?: PluginUpdateCheck & { status: string; version?: string };
  automatic_updates?: "follow" | "enabled" | "disabled";
  history?: Array<{ id: string; version: string; digest: string }>;
  permission_details?: PluginInstallPermission[];
}
export interface RuntimeCapabilities {
  bubblewrap_available: boolean | null;
  sandbox_available: boolean;
  mechanism: string;
  reduced_isolation_allowed: boolean;
  last_error?: string | null;
  available?: boolean;
}
export interface ManagerSettings {
  automatic_updates: boolean;
  retained_versions: number;
}
export type PluginTrustStatus =
  "trusted" | "unknown_publisher" | "invalid_signature" | "unsigned";
export interface PluginSourceMetadata {
  type: "upload" | "url" | "catalogue" | "unknown";
  url?: string;
  catalogue_url?: string;
  release_notes?: string | null;
  changelog_url?: string | null;
}
export interface PluginInstallPermission {
  key: string;
  capability: string;
  capability_version: number;
  rationale: string;
  title: string;
  category: string;
  parent: string | null;
  children: string[];
  risk: "low" | "medium" | "high" | "critical";
  highly_privileged: boolean;
  new?: boolean;
}
export interface PluginInstallPreview {
  plugin_id: string;
  name: string;
  description: string;
  icon?: string | null;
  readme?: string | null;
  version: string;
  publisher: string | null;
  publisher_key_id: string | null;
  digest: string;
  trust_status: PluginTrustStatus;
  trust_warning: string | null;
  signature_present: boolean;
  signature_verified: boolean;
  installable: boolean;
  sdk_version_range: string;
  application_version_range: string;
  dependencies: Array<{
    plugin_id: string;
    version_range: string;
    optional: boolean;
    state:
      | "satisfied"
      | "missing"
      | "incompatible"
      | "optional_missing"
      | "optional_incompatible"
      | "available"
      | "unresolved";
    installed_version: string | null;
    available_version: string | null;
    source_url: string | null;
  }>;
  dependency_ready: boolean;
  dependency_order: string[];
  dependency_conflicts: string[];
  requires_elevated_reauthentication: boolean;
  source: PluginSourceMetadata;
  operation?: "update";
  installed_version?: string;
  permission_delta?: Record<string, unknown>;
  new_permission_keys?: string[];
  existing_grants_retained?: boolean;
  identity_warning?: string | null;
  release_notes?: string | null;
  permissions: PluginInstallPermission[];
  ui: { pages: string[]; menus: string[]; has_custom_frontend: boolean };
}
export interface PluginCatalogEntry {
  plugin_id: string;
  name: string;
  description: string;
  version: string;
  url: string;
  tags?: string[];
  icon?: string | null;
  publisher?: string | null;
  compatibility?: string | null;
  readme?: string | null;
  release_notes?: string | null;
  changelog_url?: string | null;
  catalogue_url?: string;
  dependencies?: Array<{
    plugin_id: string;
    version_range: string;
    optional?: boolean;
  }>;
}
export interface PluginInstallResult {
  plugin_id: string;
  version: string;
  name: string;
  publisher: string | null;
  installation_id: string;
  permissions_requested: number;
  permissions_granted: number;
  permissions_denied: number;
  trust_status: PluginTrustStatus;
  trust_warning: string | null;
  status: string;
}
export interface PluginInstallConfirmation {
  approvedPermissions: string[];
  adminPassword?: string;
  confirmDangerous?: boolean;
}
export interface PluginCatalogue {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  priority: number;
  trust_metadata: Record<string, string>;
  last_successful_check: number | null;
  last_error: string | null;
}
export interface PluginUpdateCheck {
  plugin_id: string;
  current_version: string;
  available_version?: string;
  update_available: boolean;
  url?: string;
  release_notes?: string | null;
  changelog_url?: string | null;
  source?: PluginSourceMetadata;
  reason?: string;
  error?: string;
}
export interface PluginDiagnosticEvent {
  sequence: number;
  timestamp: string;
  level: "debug" | "info" | "warning" | "error";
  event: string;
  message: string;
  source: "runtime" | "plugin" | string;
  plugin_id: string;
  correlation_id: string | null;
  metadata: Record<string, string | number | boolean | null>;
}
export interface PluginDiagnostics {
  plugin_id: string;
  status: "running" | "stopped";
  last_exit_code: number | null;
  events: PluginDiagnosticEvent[];
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok)
    throw new Error(`Plugin manager request failed (${response.status}).`);
  return response.json() as Promise<T>;
}
export const fetchRuntimeCapabilities = () =>
  request<RuntimeCapabilities>("/api/plugins/runtime/health");
export const fetchManagerSettings = () =>
  request<ManagerSettings>("/api/plugins/manager-settings");
export const saveManagerSettings = (values: ManagerSettings) =>
  request<ManagerSettings>("/api/plugins/manager-settings", {
    method: "PUT",
    body: JSON.stringify(values),
  });
export const setPluginAutomaticUpdates = (id: string, mode: string) =>
  request<PluginSummary>(`/api/plugins/${encodeURIComponent(id)}/auto-update`, {
    method: "PUT",
    body: JSON.stringify({ mode }),
  });
export const packageOperation = (
  id: string,
  operation: string,
  values: Record<string, unknown> = {},
) =>
  request<PluginInstallResult>(
    `/api/plugins/${encodeURIComponent(id)}/${operation}`,
    { method: "POST", body: JSON.stringify(values) },
  );
export const previewStagedUpdate = (id: string) =>
  request<PluginInstallPreview>(
    `/api/plugins/${encodeURIComponent(id)}/update/staged/preview`,
    { method: "POST" },
  );
export class UntrustedPluginError extends Error {
  details: {
    plugin_id: string;
    name: string;
    version: string;
    publisher: string | null;
  };
  constructor(details: {
    plugin_id: string;
    name: string;
    version: string;
    publisher: string | null;
  }) {
    super(
      "This plugin has an invalid signature/untrusted publisher. Install it?",
    );
    this.name = "UntrustedPluginError";
    this.details = details;
  }
}

export const previewPluginInstall = async (
  file: File,
): Promise<PluginInstallPreview> => {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch("/api/plugins/install/preview", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail =
      typeof body?.detail === "object" ? body.detail.message : body?.detail;
    throw new Error(
      detail
        ? `Plugin preview failed (${response.status}): ${detail}`
        : `Plugin preview failed (${response.status}).`,
    );
  }
  return response.json() as Promise<PluginInstallPreview>;
};

export const installPlugin = async (
  file: File,
  confirmation: PluginInstallConfirmation,
  allowUntrusted = false,
): Promise<PluginInstallResult> => {
  const form = new FormData();
  form.append("file", file, file.name);
  const query = new URLSearchParams({
    allow_untrusted: allowUntrusted ? "true" : "false",
    confirm_dangerous: confirmation.confirmDangerous ? "true" : "false",
  });
  if (confirmation.adminPassword)
    query.set("admin_password", confirmation.adminPassword);
  for (const permission of confirmation.approvedPermissions)
    query.append("approved_permissions", permission);
  const response = await fetch(`/api/plugins/install?${query.toString()}`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (response.status === 409) {
    const body = await response.json().catch(() => null);
    if (body?.detail?.code === "untrusted_plugin")
      throw new UntrustedPluginError(body.detail);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail =
      typeof body?.detail === "object" ? body.detail.message : body?.detail;
    throw new Error(
      detail
        ? `Plugin installation failed (${response.status}): ${detail}`
        : `Plugin installation failed (${response.status}).`,
    );
  }
  return response.json();
};

export const fetchPluginCatalog = (source?: string) => {
  const query = source ? `?source=${encodeURIComponent(source)}` : "";
  return request<PluginCatalogEntry[]>(`/api/plugins/catalog${query}`);
};

export const fetchPluginCatalogFromSource = (source: string) =>
  request<PluginCatalogEntry[]>(
    `/api/plugins/catalog?source=${encodeURIComponent(source)}`,
  );

export const previewPluginInstallUrl = async (
  url: string,
  source: Partial<PluginSourceMetadata> = {},
): Promise<
  PluginInstallPreview & {
    source_url: string;
    download_filename: string;
    download_bytes: number;
  }
> => {
  const response = await fetch("/api/plugins/install/preview-url", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, ...source }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail =
      typeof body?.detail === "object" ? body.detail.message : body?.detail;
    throw new Error(
      detail
        ? `Plugin URL preview failed (${response.status}): ${detail}`
        : `Plugin URL preview failed (${response.status}).`,
    );
  }
  return response.json();
};

export const installPluginFromUrl = async (
  url: string,
  confirmation: PluginInstallConfirmation,
  expectedDigest: string,
  allowUntrusted = false,
  source: Partial<PluginSourceMetadata> = {},
): Promise<PluginInstallResult> => {
  const query = new URLSearchParams({
    allow_untrusted: allowUntrusted ? "true" : "false",
  });
  for (const permission of confirmation.approvedPermissions)
    query.append("approved_permissions", permission);
  const response = await fetch(`/api/plugins/install/url?${query.toString()}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url,
      expected_digest: expectedDigest,
      admin_password: confirmation.adminPassword,
      confirm_dangerous: confirmation.confirmDangerous ?? false,
      ...source,
    }),
  });
  if (response.status === 409) {
    const body = await response.json().catch(() => null);
    if (body?.detail?.code === "untrusted_plugin")
      throw new UntrustedPluginError(body.detail);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail =
      typeof body?.detail === "object" ? body.detail.message : body?.detail;
    throw new Error(
      detail
        ? `Plugin installation failed (${response.status}): ${detail}`
        : `Plugin installation failed (${response.status}).`,
    );
  }
  return response.json();
};

export const fetchPlugins = () => request<PluginSummary[]>("/api/plugins");
export const enablePlugin = (id: string) =>
  request<void>(`/api/plugins/${encodeURIComponent(id)}/enable`, {
    method: "POST",
  });
export const disablePlugin = (id: string) =>
  request<void>(`/api/plugins/${encodeURIComponent(id)}/disable`, {
    method: "POST",
  });
export const retryPlugin = (id: string) =>
  request<void>(`/api/plugins/${encodeURIComponent(id)}/retry`, {
    method: "POST",
  });
export const revokePluginPermissions = (id: string) =>
  request<void>(`/api/plugins/${encodeURIComponent(id)}/permissions/revoke`, {
    method: "POST",
  });

export const fetchPluginLogs = (id: string) =>
  request<PluginDiagnostics>(`/api/plugins/${encodeURIComponent(id)}/logs`);

export const previewPluginUpdate = async (
  id: string,
  file: File,
  operation = "update",
): Promise<PluginInstallPreview> => {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(id)}/update/preview?operation=${operation}`,
    { method: "PUT", credentials: "include", body: form },
  );
  if (!response.ok)
    throw new Error(`Plugin update preview failed (${response.status}).`);
  return response.json();
};

export const previewPluginUpdateUrl = async (
  id: string,
  url: string,
  source: Partial<PluginSourceMetadata> = {},
  operation = "update",
): Promise<PluginInstallPreview> => {
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(id)}/update/preview-url?operation=${operation}`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, ...source }),
    },
  );
  if (!response.ok)
    throw new Error(`Plugin update preview failed (${response.status}).`);
  return response.json();
};

export const updatePlugin = async (
  id: string,
  file: File,
  confirmation: PluginInstallConfirmation,
  allowUntrusted = false,
  operation = "update",
): Promise<{
  plugin_id: string;
  version: string;
  permissions_requested: number;
  status: string;
}> => {
  const form = new FormData();
  form.append("file", file, file.name);
  const query = new URLSearchParams({
    operation,
    allow_untrusted: allowUntrusted ? "true" : "false",
    confirm_dangerous: confirmation.confirmDangerous ? "true" : "false",
  });
  if (confirmation.adminPassword)
    query.set("admin_password", confirmation.adminPassword);
  for (const permission of confirmation.approvedPermissions)
    query.append("approved_permissions", permission);
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(id)}/update?${query.toString()}`,
    { method: "PUT", credentials: "include", body: form },
  );
  if (!response.ok)
    throw new Error(`Plugin update failed (${response.status}).`);
  return response.json();
};

export const updatePluginFromUrl = async (
  id: string,
  url: string,
  confirmation: PluginInstallConfirmation,
  expectedDigest: string,
  allowUntrusted = false,
  source: Partial<PluginSourceMetadata> = {},
  operation = "update",
): Promise<{
  plugin_id: string;
  version: string;
  permissions_requested: number;
  status: string;
}> => {
  const query = new URLSearchParams({
    operation,
    allow_untrusted: allowUntrusted ? "true" : "false",
  });
  for (const permission of confirmation.approvedPermissions)
    query.append("approved_permissions", permission);
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(id)}/update/url?${query.toString()}`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        expected_digest: expectedDigest,
        admin_password: confirmation.adminPassword,
        confirm_dangerous: confirmation.confirmDangerous ?? false,
        ...source,
      }),
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail =
      typeof body?.detail === "object" ? body.detail.message : body?.detail;
    throw new Error(
      detail
        ? `Plugin update failed (${response.status}): ${detail}`
        : `Plugin update failed (${response.status}).`,
    );
  }
  return response.json();
};

export const fetchPluginCatalogues = () =>
  request<PluginCatalogue[]>("/api/plugins/catalogues");
export const createPluginCatalogue = (catalogue: {
  name: string;
  url: string;
  enabled?: boolean;
  priority?: number;
}) =>
  request<PluginCatalogue>("/api/plugins/catalogues", {
    method: "POST",
    body: JSON.stringify(catalogue),
  });
export const updatePluginCatalogue = (
  id: string,
  changes: Partial<
    Pick<PluginCatalogue, "name" | "url" | "enabled" | "priority">
  >,
) =>
  request<PluginCatalogue>(
    `/api/plugins/catalogues/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      body: JSON.stringify(changes),
    },
  );
export const deletePluginCatalogue = async (id: string): Promise<void> => {
  const response = await fetch(
    `/api/plugins/catalogues/${encodeURIComponent(id)}`,
    {
      method: "DELETE",
      credentials: "include",
    },
  );
  if (!response.ok && response.status !== 204)
    throw new Error(`Catalogue removal failed (${response.status}).`);
};
export const checkPluginUpdates = () =>
  request<{
    updates: PluginUpdateCheck[];
    available: number;
    checked_at: number;
  }>("/api/plugins/updates/check", { method: "POST" });
export const fetchPluginChangelog = (id: string) =>
  request<{
    plugin_id: string;
    version: string | null;
    format: "markdown" | "text";
    source: string;
    body: string;
    url?: string;
  }>(`/api/plugins/${encodeURIComponent(id)}/changelog`);

export const deletePlugin = async (id: string): Promise<void> => {
  const response = await fetch(`/api/plugins/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204)
    throw new Error(`Plugin deletion failed (${response.status}).`);
};
