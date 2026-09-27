export interface PasswordPolicy {
  min_length: number;
  require_uppercase: boolean;
  require_lowercase: boolean;
  require_digit: boolean;
  require_symbol: boolean;
}

export async function fetchPasswordPolicy(): Promise<PasswordPolicy> {
  const response = await fetch("/api/auth/password-policy", { credentials: "include" });
  if (!response.ok) throw new Error(`Failed to load password policy: ${response.status}`);
  return await response.json();
}

export function passwordValidationErrors(password: string, policy: PasswordPolicy): string[] {
  const errors: string[] = [];
  if (password.length < policy.min_length) errors.push(`Password must be at least ${policy.min_length} characters long.`);
  if (policy.require_uppercase && !/[A-Z]/.test(password)) errors.push("Password must contain an uppercase letter.");
  if (policy.require_lowercase && !/[a-z]/.test(password)) errors.push("Password must contain a lowercase letter.");
  if (policy.require_digit && !/\d/.test(password)) errors.push("Password must contain a number.");
  if (policy.require_symbol && !/[^A-Za-z0-9]/.test(password)) errors.push("Password must contain a symbol.");
  return errors;
}
