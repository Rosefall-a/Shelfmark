import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyGameMetadataRefresh,
  previewGameMetadataRefresh,
} from "../services/games";
import type { Game } from "../types/game";

const game = {
  id: "game-1",
  title: "Example",
  updatedAt: 123,
} as Game;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("game metadata refresh service", () => {
  it("maps a provider preview without applying changes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "updated",
          provider: "Steam",
          provider_errors: [],
          changed_fields: ["description", "developer"],
          skipped_locked_fields: ["publisher"],
          would_add_key_art: true,
          would_add_banner: false,
          game_updated_at: 123,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const preview = await previewGameMetadataRefresh(game);
    expect(preview.changedFields).toEqual(["description", "developer"]);
    expect(preview.skippedLockedFields).toEqual(["publisher"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/game/game-1/metadata/refresh",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("surfaces a stale preview conflict instead of silently applying it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("Game changed after the metadata preview.", { status: 409 }),
      ),
    );
    await expect(applyGameMetadataRefresh(game)).rejects.toThrow("409");
  });
});
