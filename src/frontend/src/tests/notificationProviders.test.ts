import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchNotificationProviders,
  revokeNotificationProviderDestination,
  updateNotificationProvider,
} from "../services/notificationProviders";

describe("notification provider service", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads provider settings without exposing a secret destination", async () => {
    const response = {
      id: "discord",
      name: "Discord webhook",
      enabled: true,
      available: true,
      configured: true,
      destination: null,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([response]), { status: 200 })));

    const result = await fetchNotificationProviders();

    expect(result).toEqual([response]);
    expect(result[0].destination).toBeNull();
  });

  it("saves a provider without changing the API contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "discord", enabled: true, available: true, configured: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateNotificationProvider("discord", { enabled: true, destination: "replacement" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/notification-providers/discord",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ enabled: true, destination: "replacement" }),
      }),
    );
  });

  it("revokes a provider destination", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await revokeNotificationProviderDestination("discord");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/notification-providers/discord/destination",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("surfaces provider API errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("invalid webhook", { status: 422 })));

    await expect(
      updateNotificationProvider("discord", { destination: "invalid" }),
    ).rejects.toThrow("invalid webhook");
  });
});
