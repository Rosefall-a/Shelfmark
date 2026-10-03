import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameNote, renameGameNote, saveGameNote } from "../services/games";

describe("game note conflicts and renames", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a human-readable conflict when creating a duplicate note", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              error: "note_already_exists",
              message: 'A note titled "what is this for" already exists.',
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      createGameNote("game-1", "what is this for", "replacement"),
    ).rejects.toThrow(
      'A note titled "what is this for" already exists. Choose a different title or cancel the operation.',
    );
  });

  it("uses the rename endpoint and encodes human-readable titles", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          game_id: "game-1",
          note_name: "New title",
          status: "saved",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await renameGameNote("game-1", "Old title", "New title");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/game/game-1/notes/Old%20title/rename",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ new_name: "New title" }),
      }),
    );
  });

  it("does not expose backend error payloads for rename failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              error: "note_already_exists",
              message: 'A note titled "Existing" already exists.',
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      renameGameNote("game-1", "Source", "Existing"),
    ).rejects.toThrow(
      'A note titled "Existing" already exists. Choose a different title or cancel the operation.',
    );
  });

  it("uses update rather than create when saving an existing note", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          game_id: "game-1",
          note_name: "Existing note",
          status: "saved",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await saveGameNote("game-1", "Existing note", "updated");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/game/game-1/notes/Existing%20note",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ content: "updated" }),
      }),
    );
  });
});
