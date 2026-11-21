import { afterEach, describe, expect, it, vi } from "vitest";
import { me } from "../src/lib/api/auth";
import { ApiError, request } from "../src/lib/api/client";

function stubFetch(status: number, body: unknown, json = true) {
  const res = new Response(json ? JSON.stringify(body) : String(body), { status });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("maps the error envelope to ApiError", async () => {
    stubFetch(401, { error: { code: "unauthenticated", message: "invalid username or password" } });
    const err = (await request("POST", "/auth/login", {}).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 401, code: "unauthenticated" });
    expect(err.message).toBe("invalid username or password");
  });

  it("maps nginx 429 pages to rate_limited", async () => {
    stubFetch(429, "<html>429</html>", false);
    await expect(request("POST", "/auth/login", {})).rejects.toMatchObject({
      code: "rate_limited",
    });
  });

  it("sends JSON with same-origin credentials", async () => {
    stubFetch(200, { id: "1", username: "a" });
    await request("POST", "/auth/login", { username: "a", password: "b" });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/auth/login");
    expect(init).toMatchObject({ method: "POST", credentials: "same-origin" });
    expect(JSON.parse(init!.body as string)).toEqual({ username: "a", password: "b" });
  });

  it("me() returns null on 401", async () => {
    stubFetch(401, { error: { code: "unauthenticated", message: "not logged in" } });
    expect(await me()).toBeNull();
  });
});
