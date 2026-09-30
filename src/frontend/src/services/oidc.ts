export interface OidcLoginProvider {
  name: string;
  slug: string;
  button_text: string;
  button_image_url: string | null;
  button_color: string;
  autostart_enabled: boolean;
}
export interface OidcLoginStatus {
  enabled: boolean;
  issuer: string | null;
  default_login_method: "local" | "sso";
  login_button_text: string;
  providers: OidcLoginProvider[];
}
export async function oidcLoginStatus(): Promise<OidcLoginStatus> {
  const response = await fetch("/api/auth/oidc/status", {
    credentials: "include",
  });
  if (!response.ok)
    return {
      enabled: false,
      issuer: null,
      default_login_method: "local",
      login_button_text: "Continue with SSO",
      providers: [],
    };
  const result = await response.json();
  return {
    enabled: result.enabled === true,
    issuer: result.issuer ?? null,
    default_login_method:
      result.default_login_method === "sso" ? "sso" : "local",
    login_button_text:
      typeof result.login_button_text === "string" &&
        result.login_button_text.trim()
        ? result.login_button_text.trim()
        : "Continue with SSO",
    providers: Array.isArray(result.providers) ? result.providers.map(
      (provider: OidcLoginProvider) => ({
        ...provider,
        button_color: typeof provider.button_color === "string"
          ? provider.button_color : "#d68a34",
        autostart_enabled: provider.autostart_enabled !== false
      })) : []
  };
}
export async function oidcEnabled(): Promise<boolean> {
  return (await oidcLoginStatus()).enabled;
}
export function startOidcLogin(slug?: string): void {
  window.location.assign(
    slug && slug !== "default"
      ? `/api/auth/oidc/login/${encodeURIComponent(slug)}`
      : "/api/auth/oidc/login",
  );
}
