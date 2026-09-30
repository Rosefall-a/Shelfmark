export type SetupSectionStatus =
  | "not_configured"
  | "partial"
  | "configured"
  | "completed_by_env"
  | "blocked_by_env";

export interface SetupChoice {
  value: string;
  label: string;
}

export interface SetupField {
  name: string;
  label: string;
  type: "text" | "secret" | "boolean" | "integer" | "choice" | "url" | "email";
  choices: SetupChoice[];
  description: string;
  hint: string;
  placeholder: string;
  required: boolean;
  required_group: string | null;
  heading: string | null;
  secret: boolean;
  generated: boolean;
  deprecated: boolean;
  deprecated_message: string;
  visible: boolean;
  env_only: boolean;
  locked: boolean;
  configured: boolean;
  source: "env" | "database" | "default" | "generated" | "unset";
  value: unknown;
}

export interface SetupSection {
  id: string;
  title: string;
  description: string;
  menu: string | null;
  required: boolean;
  removable: boolean;
  visible: boolean;
  default: boolean;
  status: SetupSectionStatus;
  blocked: boolean;
  blocked_message: string;
  env_configured: boolean;
  fields: SetupField[];
}

export interface SetupStatus {
  setup_required: boolean;
  startup_mode: string;
  startup_ui_enabled: boolean;
}

export interface SetupConfiguration {
  sections: SetupSection[];
  startup_mode: string;
  startup_ui_enabled: boolean;
}

export interface SetupOptions {
  oidc_name?: string;
  oidc_issuer_url?: string;
  oidc_client_id?: string;
  oidc_client_secret?: string;
  oidc_scopes?: string;
  oidc_redirect_uri?: string;
  oidc_groups_claim?: string;
  oidc_admin_group?: string;
  oidc_user_match_field?: string;
  oidc_allow_new_users?: boolean;
  oidc_button_text?: string;
  oidc_default_login_method?: string;
}

export interface SetupSubmission {
  sections: string[];
  configuration: Record<string, unknown>;
  username?: string;
  email?: string;
  password?: string;
}

async function parseError(response: Response, fallback: string): Promise<Error> {
  const body = await response.text();
  try {
    const parsed = JSON.parse(body) as { detail?: string | Array<{ msg?: string }> };
    if (Array.isArray(parsed.detail)) {
      const details = parsed.detail.map((item) => item.msg).filter(Boolean);
      if (details.length) return new Error(details.join(" "));
    }
    if (typeof parsed.detail === "string") return new Error(parsed.detail);
  } catch {
    // Keep the HTTP status when the backend did not return JSON.
  }
  return new Error(body ? `${fallback} ${body}` : fallback);
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  const response = await fetch("/api/setup/status", { credentials: "include" });
  if (!response.ok) throw await parseError(response, `Failed to check setup status: ${response.status}`);
  return (await response.json()) as SetupStatus;
}

export async function fetchSetupConfiguration(): Promise<SetupConfiguration> {
  const response = await fetch("/api/setup/configuration", { credentials: "include" });
  if (!response.ok) throw await parseError(response, `Failed to load setup configuration: ${response.status}`);
  return (await response.json()) as SetupConfiguration;
}

export async function saveSetupConfiguration(
  submission: SetupSubmission,
): Promise<SetupConfiguration> {
  const response = await fetch("/api/setup/configuration", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(submission),
  });
  if (!response.ok) throw await parseError(response, `Failed to save configuration: ${response.status}`);
  return (await response.json()) as SetupConfiguration;
}

export async function createInitialAdmin(
  submission: SetupSubmission,
): Promise<{ status: string; user_id: string; is_admin: boolean }> {
  const response = await fetch("/api/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(submission),
  });
  if (!response.ok) throw await parseError(response, `Setup failed: ${response.status}`);
  return (await response.json()) as { status: string; user_id: string; is_admin: boolean };
}
