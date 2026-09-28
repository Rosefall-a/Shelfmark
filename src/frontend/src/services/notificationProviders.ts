export interface NotificationProviderSetting {
  id: "smtp" | "discord" | string;
  name: string;
  enabled: boolean;
  available: boolean;
  configured: boolean;
  destination: string | null;
}
export async function fetchNotificationProviders(): Promise<NotificationProviderSetting[]> {
  const r=await fetch("/api/settings/notification-providers",{credentials:"include"});
  if(!r.ok) throw new Error(`Failed to load notification providers: ${r.status}`);
  return await r.json();
}
export async function updateNotificationProvider(id:string,payload:{enabled?:boolean;destination?:string}):Promise<NotificationProviderSetting>{
  const r=await fetch(`/api/settings/notification-providers/${encodeURIComponent(id)}`,{method:"PUT",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  if(!r.ok){const message=await r.text();throw new Error(message||`Failed to update notification provider: ${r.status}`);}
  return await r.json();
}
export async function revokeNotificationProviderDestination(id:string):Promise<void>{
  const r=await fetch(`/api/settings/notification-providers/${encodeURIComponent(id)}/destination`,{method:"DELETE",credentials:"include"});
  if(!r.ok) throw new Error(`Failed to revoke provider destination: ${r.status}`);
}


export type NotificationTestKind =
  | "generic"
  | "episode_aired"
  | "season_started"
  | "sequel_announced"
  | "movie_released";

export async function sendNotificationProviderTest(
  id: string,
  kind: NotificationTestKind,
): Promise<void> {
  const response = await fetch(`/api/settings/notification-providers/${encodeURIComponent(id)}/test`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Notification test failed: ${response.status}`);
  }
}
