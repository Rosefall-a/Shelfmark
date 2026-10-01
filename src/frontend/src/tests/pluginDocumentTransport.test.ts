import { afterEach, describe, expect, it, vi } from "vitest";
import { dispatchPluginAction, PluginActionError } from "../services/pluginUi";

afterEach(() => vi.unstubAllGlobals());

describe("scoped document action transport", () => {
  it.each([401, 403, 404, 413, 415, 500, 502])(
    "preserves HTTP %s for the sandbox bridge without disclosing response bodies",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(new Response("private diagnostic", { status })),
      );
      const error = await dispatchPluginAction(
        "example.scoped-document-viewer",
        "read-document",
      ).catch((value) => value);
      expect(error).toBeInstanceOf(PluginActionError);
      expect(error.status).toBe(status);
      expect(error.message).not.toContain("private diagnostic");
    },
  );

  it("passes safe domain errors through and keeps credentials in the host", async () => {
    const result = {
      error: {
        kind: "missing",
        message: "Document not found.",
        status_code: 404,
      },
    };
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(result)));
    vi.stubGlobal("fetch", fetch);
    expect(
      await dispatchPluginAction(
        "example.scoped-document-viewer",
        "read-document",
        { document_id: "opaque-id", chunk_bytes: 24576 },
      ),
    ).toEqual(result);
    expect(fetch.mock.calls[0][1].credentials).toBe("include");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      values: { document_id: "opaque-id", chunk_bytes: 24576 },
      confirmed: false,
    });
  });
});
