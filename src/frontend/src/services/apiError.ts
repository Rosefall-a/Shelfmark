// Turns a failed API response into a sentence a person can act on, instead of
// the raw status line and JSON the server sent.

interface ValidationIssue {
  loc?: unknown[];
  msg?: unknown;
}

// ["body", "folder_location"] -> "Folder location"
function fieldLabel(loc: unknown[] | undefined): string | null {
  const parts = (loc ?? []).filter(
    (part): part is string => typeof part === "string" && part !== "body",
  );
  const last = parts.pop();
  if (!last) return null;
  const words = last.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function validationMessage(issues: ValidationIssue[]): string | null {
  const messages = issues
    .map((issue) => {
      if (typeof issue.msg !== "string") return null;
      // pydantic prefixes a validator's own message with "Value error, "
      const msg = issue.msg.replace(/^Value error,\s*/i, "");
      const field = fieldLabel(issue.loc);
      return field ? `${field}: ${msg}` : msg;
    })
    .filter((m): m is string => !!m);
  if (!messages.length) return null;
  const shown = messages.slice(0, 3).join("; ");
  return messages.length > 3 ? `${shown} (and more)` : shown;
}

function serverDetail(body: string): string | null {
  let detail: unknown;
  try {
    detail = (JSON.parse(body) as { detail?: unknown }).detail;
  } catch {
    return null;
  }
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return validationMessage(detail);
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return null;
}

export function friendlyError(status: number, body: string): string {
  if (status === 401) return "You are signed out. Sign in again to continue.";
  if (status === 403) return "You do not have permission to do that.";
  if (status === 404)
    return "That could not be found. It may have been deleted.";
  if (status === 422)
    return serverDetail(body) ?? "That is not a valid address or value.";
  if (status >= 500) {
    return "The server had a problem. Wait a moment and try again.";
  }
  return serverDetail(body) ?? `The request failed (${status}).`;
}

export async function failedRequest(response: Response): Promise<Error> {
  return new Error(friendlyError(response.status, await response.text()));
}
