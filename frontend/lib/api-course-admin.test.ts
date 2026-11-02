import { describe, it, expect, vi, afterEach } from "vitest";

// No session: apiFetch proceeds without a token instead of attempting a refresh.
vi.mock("./auth", () => ({
  authClient: {
    getValidToken: vi.fn(async () => {
      throw new Error("no token");
    }),
  },
}));

import { ApiError } from "./api";
import { publishAdminCourse, unindexedSourcesFromError } from "./api-course-admin";

function jsonResponse(status: number, body: unknown) {
  return { ok: status < 400, status, json: async () => body };
}

describe("publish guard for unindexed sources (#2663)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("exposes the source list from a 409 UNINDEXED_SOURCES refusal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(409, {
          detail: {
            code: "UNINDEXED_SOURCES",
            message: "These sources have no indexed text: b.pdf.",
            sources: ["b.pdf"],
          },
        }),
      ),
    );

    const err = await publishAdminCourse("course-1").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(unindexedSourcesFromError(err)).toEqual(["b.pdf"]);
  });

  it("sends force=true once the admin has confirmed", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    await publishAdminCourse("course-1", true);

    expect(fetchMock.mock.calls[0][0]).toMatch(
      /\/api\/v1\/admin\/courses\/course-1\/publish\?force=true$/,
    );
  });

  it("returns null for any other error", () => {
    expect(unindexedSourcesFromError(new ApiError("busy", 409, "INDEX_TASK_ACTIVE"))).toBeNull();
    expect(unindexedSourcesFromError(new Error("boom"))).toBeNull();
  });
});
