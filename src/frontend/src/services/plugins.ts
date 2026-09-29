export type PluginStatus =
  "running" | "stopped" | "quarantined" | "failed" | "disabled" | "unknown";
export interface PluginSummary {
  plugin_id: string;
  name: string;
  version: string;
  status: PluginStatus;
  compatible: boolean;
  compatibility_reason: string;
  health: "healthy" | "degraded" | "unhealthy" | "unknown";
  permissions: string[];
  enabled: boolean;
}
export interface PluginInstallPermission {
  key: string;
  capability: string;
  capability_version: number;
  rationale: string;
}
export interface PluginInstallPreview {
  plugin_id: string;
  name: string;
  description: string;
  version: string;
  publisher: string | null;
  digest: string;
  trust_status: "trusted" | "untrusted";
  trust_warning: string | null;
  sdk_version_range: string;
  application_version_range: string;
  dependencies: Array<{
    plugin_id: string;
    version_range: string;
    optional: boolean;
  }>;
  permissions: PluginInstallPermission[];
  ui: { pages: string[]; menus: string[]; has_custom_frontend: boolean };
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
  trust_status: "trusted" | "untrusted";
  trust_warning: string | null;
  status: string;
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
  approvedPermissions: string[],
  allowUntrusted = false,
): Promise<PluginInstallResult> => {
  const form = new FormData();
  form.append("file", file, file.name);
  const query = new URLSearchParams({
    allow_untrusted: allowUntrusted ? "true" : "false",
  });
  for (const permission of approvedPermissions)
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

export const updatePlugin = async (
  id: string,
  file: File,
): Promise<{
  plugin_id: string;
  version: string;
  permissions_requested: number;
  status: string;
}> => {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch(
    `/api/plugins/${encodeURIComponent(id)}/update`,
    { method: "PUT", credentials: "include", body: form },
  );
  if (!response.ok)
    throw new Error(`Plugin update failed (${response.status}).`);
  return response.json();
};

export const deletePlugin = async (id: string): Promise<void> => {
  const response = await fetch(`/api/plugins/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204)
    throw new Error(`Plugin deletion failed (${response.status}).`);
};
