import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Builds a JWT-shaped token whose payload carries an `exp` claim.
function makeToken(expSecondsFromNow: number): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = btoa(
    JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expSecondsFromNow }),
  );
  return `${header}.${payload}.sig`;
}

describe("authClient.getValidToken", () => {
  beforeEach(() => {
    localStorage.clear();
    // Fresh singleton per test: the constructor reads tokens from localStorage,
    // so an empty store reproduces the post-page-load state (refreshToken null).
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("refreshes via the cookie when no refresh token is held in memory (regression #2112)", async () => {
    const fresh = makeToken(900);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        access_token: fresh,
        token_type: "bearer",
        expires_in: 900,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { authClient } = await import("./auth");
    const token = await authClient.getValidToken();

    // It must attempt the cookie-based refresh rather than throwing 401.
    expect(token).toBe(fresh);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/auth/refresh");
  });

  it("throws a clean session-expired error when the cookie refresh fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Refresh token required" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { authClient, AuthError } = await import("./auth");

    await expect(authClient.getValidToken()).rejects.toMatchObject({
      name: "AuthError",
      status: 401,
    });
    // One refresh attempt, no retry loop.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(AuthError).toBeDefined();
  });
});
