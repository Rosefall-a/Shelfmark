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
export const installPlugin = async (file: File): Promise<{plugin_id:string;version:string;name:string;publisher:string|null;installation_id:string;permissions_requested:number;trust_status:"trusted"|"untrusted";trust_warning:string|null;status:string}> => {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch("/api/plugins/install", {method:"POST", credentials:"include", body:form});
  if (!response.ok) throw new Error(`Plugin installation failed (${response.status}).`);
  return response.json();
};

export const fetchPlugins = () => request<PluginSummary[]>("/api/plugins");
export const enablePlugin = (id: string) => request<void>(`/api/plugins/${encodeURIComponent(id)}/enable`, {method:"POST"});
export const disablePlugin = (id: string) => request<void>(`/api/plugins/${encodeURIComponent(id)}/disable`, {method:"POST"});
export const retryPlugin = (id: string) => request<void>(`/api/plugins/${encodeURIComponent(id)}/retry`, {method:"POST"});
export const revokePluginPermissions = (id: string) => request<void>(`/api/plugins/${encodeURIComponent(id)}/permissions/revoke`, {method:"POST"});
