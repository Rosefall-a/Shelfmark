export interface DocumentViewResult {
  type: "pdf" | "text" | "html";
  url: string;
  content?: string;
}

export type DocumentViewErrorKind =
  | "missing"
  | "forbidden"
  | "unsupported"
  | "server"
  | "network";

export class DocumentViewError extends Error {
  readonly kind: DocumentViewErrorKind;

  constructor(kind: DocumentViewErrorKind, message: string) {
    super(message);
    this.name = "DocumentViewError";
    this.kind = kind;
  }
}

function classifyDocumentError(status: number): DocumentViewError {
  if (status === 401 || status === 403)
    return new DocumentViewError(
      "forbidden",
      "You are not authorized to view this document.",
    );
  if (status === 404)
    return new DocumentViewError("missing", "Document not found.");
  if (status === 413)
    return new DocumentViewError(
      "unsupported",
      "This document is too large to view.",
    );
  if (status === 415)
    return new DocumentViewError(
      "unsupported",
      "This document format is not supported.",
    );
  if (status >= 500)
    return new DocumentViewError(
      "server",
      "The server could not load this document.",
    );
  return new DocumentViewError("network", `Could not load document (HTTP ${status}).`);
}

export async function fetchDocumentView(
  gameId: string,
  filename: string,
): Promise<DocumentViewResult> {
  const response = await fetch(
    `/api/game/${gameId}/files/doc/${encodeURIComponent(filename)}/view`,
    { credentials: "include" },
  );

  if (!response.ok) throw classifyDocumentError(response.status);

  const contentType = (response.headers.get("content-type") ?? "")
    .split(";", 1)[0]
    .toLowerCase();

  if (contentType === "application/pdf") {
    return {
      type: "pdf",
      url: URL.createObjectURL(await response.blob()),
    };
  }

  if (contentType === "text/plain") {
    const content = await response.text();
    return {
      type: response.headers.get("X-Document-Format") === "html" ? "html" : "text",
      url: "",
      content,
    };
  }

  throw new DocumentViewError(
    "unsupported",
    "The server returned an unsupported document type.",
  );
}
