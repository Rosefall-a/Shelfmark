export type PluginStatus = "running" | "stopped" | "quarantined" | "failed" | "disabled" | "unknown";
export interface PluginSummary {
  plugin_id: string; name: string; version: string; status: PluginStatus;
  compatible: boolean; compatibility_reason: string;
  health: "healthy" | "degraded" | "unhealthy" | "unknown";
  permissions: string[]; enabled: boolean;
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {...init, credentials: "include", headers: {"Content-Type": "application/json", ...(init?.headers ?? {})}});
  if (!response.ok) throw new Error(`Plugin manager request failed (${response.status}).`);
  return response.json() as Promise<T>;
}
export const fetchPlugins = () => request<PluginSummary[]>("/api/plugins");
export const enablePlugin = (id: string) => request<void>(`/api/plugins/${encodeURIComponent(id)}/enable`, {method:"POST"});
export const disablePlugin = (id: string) => request<void>(`/api/plugins/${encodeURIComponent(id)}/disable`, {method:"POST"});
export const retryPlugin = (id: string) => request<void>(`/api/plugins/${encodeURIComponent(id)}/retry`, {method:"POST"});
export const revokePluginPermissions = (id: string) => request<void>(`/api/plugins/${encodeURIComponent(id)}/permissions/revoke`, {method:"POST"});
