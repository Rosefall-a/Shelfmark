import { describe, expect, it, vi } from "vitest";
import {
  fetchAdminSessions,
  fetchMySessions,
  revokeAdminSession,
  revokeAdminUserSessions,
  revokeAllAdminSessions,
  revokeAllMySessions,
  revokeMySession,
} from "../services/sessions";

describe("session service", () => {
  it("loads the current user's sessions with credentials", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => [] }),
    );
    await fetchMySessions();
    expect(fetch).toHaveBeenCalledWith("/api/sessions/me", {
      credentials: "include",
    });
  });

  it("uses session-specific revoke endpoints", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
    );
    await revokeMySession("abc");
    await revokeAdminSession("def");
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/sessions/me/abc", {
      credentials: "include",
      method: "DELETE",
    });
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/sessions/admin/def", {
      credentials: "include",
      method: "DELETE",
    });
  });

  it("supports user, server, and all-account revocation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ revoked: 2 }) }),
    );
    await revokeAllMySessions();
    await revokeAdminUserSessions("user-1");
    await revokeAllAdminSessions();
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/sessions/me/all", {
      credentials: "include",
      method: "DELETE",
    });
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/sessions/admin/user/user-1", {
      credentials: "include",
      method: "DELETE",
    });
    expect(fetch).toHaveBeenNthCalledWith(3, "/api/sessions/admin/all", {
      credentials: "include",
      method: "DELETE",
    });
  });

  it("searches admin sessions without exposing token fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [{ id: "1", ip_address: null }],
      }),
    );
    const rows = await fetchAdminSessions({ q: "alice", state: "active", country: "Australia", anomaly: true });
    expect(rows[0]).not.toHaveProperty("token");
    expect(fetch).toHaveBeenCalledWith("/api/sessions/admin?q=alice&state=active&country=Australia&anomaly=true", {
      credentials: "include",
    });
  });
});


describe("GeoIP imports", () => {
  it("selects the requested database kind", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ configured: true, kind: "country", path: "/data/GeoIP-Country.mmdb" }) }));
    const { uploadGeoIp } = await import("../services/sessions");
    const file = new File(["mmdb"], "GeoIP-Country.mmdb");
    await uploadGeoIp(file, "country");
    expect(fetch).toHaveBeenCalledWith("/api/sessions/admin/geoip?kind=country", expect.objectContaining({ method: "POST", body: expect.any(FormData) }));
  });
});
