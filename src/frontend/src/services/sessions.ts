export interface SessionLocation {
  country: string | null;
  region: string | null;
  city: string | null;
  latitude: number | null;
  longitude: number | null;
  network_type: string | null;
  network_label: string | null;
  network_number: number | null;
  network_organization: string | null;
}

export interface UserSession {
  id: string;
  user_id: string;
  username?: string;
  ip_address: string | null;
  user_agent: string | null;
  location: SessionLocation;
  created_at: number;
  last_seen_at: number;
  expires_at: number;
  revoked_at: number | null;
  state: "active" | "expired" | "revoked";
  is_current: boolean;
  anomaly: { reason: string | null; previous_location: string | null };
}

async function requestJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, { ...options, credentials: "include" });
  if (!response.ok) {
    throw new Error((await response.text()) || "Request failed: " + response.status);
  }
  return response.json() as Promise<T>;
}

export const fetchMySessions = () =>
  requestJson<UserSession[]>("/api/sessions/me");
export const revokeMySession = (id: string) =>
  requestJson<{ status: string }>("/api/sessions/me/" + encodeURIComponent(id), {
    method: "DELETE",
  });
export const revokeAllMySessions = () =>
  requestJson<{ revoked: number }>("/api/sessions/me/all", { method: "DELETE" });
export interface AdminSessionFilters {
  q?: string;
  user_id?: string;
  state?: "active" | "expired" | "revoked";
  country?: string;
  anomaly?: boolean;
}

export const fetchAdminSessions = (
  filters: AdminSessionFilters = {},
) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const suffix = params.toString() ? "?" + params.toString() : "";
  return requestJson<UserSession[]>(
    "/api/sessions/admin" + suffix,
  );
};
export const revokeAdminSession = (id: string) =>
  requestJson<{ status: string }>("/api/sessions/admin/" + encodeURIComponent(id), {
    method: "DELETE",
  });
export const revokeAllAdminSessions = () =>
  requestJson<{ revoked: number }>("/api/sessions/admin/all", { method: "DELETE" });
export const revokeAdminUserSessions = (id: string) =>
  requestJson<{ revoked: number }>("/api/sessions/admin/user/" + encodeURIComponent(id), {
    method: "DELETE",
  });
export interface GeoIpDatabaseStatus {
  configured: boolean;
  path: string;
}
export interface GeoIpStatus {
  city: GeoIpDatabaseStatus;
  country: GeoIpDatabaseStatus;
  network: GeoIpDatabaseStatus;
}
export const fetchGeoIpStatus = () =>
  requestJson<GeoIpStatus>("/api/sessions/admin/geoip/status");
export async function uploadGeoIp(
  file: File,
  kind: "city" | "country" | "network" = "city",
) {
  const body = new FormData();
  body.append("file", file);
  return requestJson<{ configured: boolean; kind: string; path: string }>(
    "/api/sessions/admin/geoip?kind=" + kind,
    {
      method: "POST",
      body,
    },
  );
}
