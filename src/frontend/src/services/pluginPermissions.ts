export interface PluginPermissionRequest {
  id: string;
  plugin_id: string;
  installation_id: string;
  capability: string;
  capability_version: number;
  rationale: string;
  user_id: string | null;
  status: "pending" | "approved" | "denied";
  requested_at: number;
  resolved_at: number | null;
}
export interface PluginPermissionGrant {
  id: string;
  plugin_id: string;
  installation_id: string;
  capability: string;
  capability_version: number;
  user_id: string | null;
  device_id: string | null;
  granted_at: number;
  revoked_at: number | null;
  active: boolean;
}
export interface PluginClientIdentity {
  id: string;
  plugin_id: string;
  installation_id: string;
  device_id: string;
  name: string;
  created_at: number;
  last_seen_at: number | null;
  revoked_at: number | null;
  active: boolean;
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok)
    throw new Error("Plugin permissions request failed: " + response.status);
  return response.json() as Promise<T>;
}
export const fetchPluginPermissionRequests = () =>
  request<PluginPermissionRequest[]>("/api/plugin-permissions/requests");
export const fetchPluginPermissionGrants = () =>
  request<PluginPermissionGrant[]>("/api/plugin-permissions/grants");
export const approvePluginPermission = (id: string) =>
  request<{ id: string; status: string }>(
    "/api/plugin-permissions/requests/" + id + "/approve",
    { method: "POST" },
  );
export const denyPluginPermission = (id: string) =>
  request<{ id: string; status: string }>(
    "/api/plugin-permissions/requests/" + id + "/deny",
    { method: "POST" },
  );
export const revokePluginPermission = (id: string) =>
  request<{ id: string; status: string }>(
    "/api/plugin-permissions/grants/" + id + "/revoke",
    { method: "POST" },
  );
export const fetchPluginClientIdentities = () =>
  request<PluginClientIdentity[]>("/api/plugin-permissions/clients");
export const revokePluginClientIdentity = (id: string) =>
  request<{ id: string; status: string }>(
    "/api/plugin-permissions/clients/" + id + "/revoke",
    { method: "POST" },
  );
