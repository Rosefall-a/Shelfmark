import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DocumentViewError,
  fetchDocumentView,
} from "../services/documentViewer";

describe("document viewer service", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads PDFs as blob URLs", async () => {
    const blob = new Blob(["%PDF-1.7"], { type: "application/pdf" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(blob, {
          status: 200,
          headers: { "Content-Type": "application/pdf" },
        }),
      ),
    );
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:pdf"),
      revokeObjectURL: vi.fn(),
    });

    await expect(fetchDocumentView("game", "manual.pdf")).resolves.toEqual({
      type: "pdf",
      url: "blob:pdf",
    });
  });

  it("loads HTML as a renderer result", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<h1>Hello</h1>", { status: 200, headers: { "Content-Type": "text/plain; charset=utf-8", "X-Document-Format": "html" } })));
    await expect(fetchDocumentView("game", "page.html")).resolves.toEqual({ type: "html", url: "", content: "<h1>Hello</h1>" });
  });

  it("loads text as plain text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<script>not executable</script>\nhello", {
          status: 200,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        }),
      ),
    );

    await expect(fetchDocumentView("game", "notes.txt")).resolves.toEqual({
      type: "text",
      url: "",
      content: "<script>not executable</script>\nhello",
    });
  });

  it.each([
    [401, "forbidden"],
    [403, "forbidden"],
    [404, "missing"],
    [413, "unsupported"],
    [415, "unsupported"],
    [500, "server"],
    [503, "server"],
  ] as const)("maps HTTP %s to %s", async (status, kind) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status })),
    );

    await expect(fetchDocumentView("game", "manual.txt")).rejects.toMatchObject({
      kind,
    });
  });

  it("rejects an unexpected successful content type", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );

    await expect(fetchDocumentView("game", "page.html")).rejects.toMatchObject({
      kind: "unsupported",
    });
  });

  it("reports network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    await expect(fetchDocumentView("game", "manual.txt")).rejects.toBeInstanceOf(
      Error,
    );
  });

  it("defines a typed document error", () => {
    const error = new DocumentViewError("missing", "Document not found.");
    expect(error).toBeInstanceOf(Error);
    expect(error.kind).toBe("missing");
  });
});
