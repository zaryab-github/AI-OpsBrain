import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, getAccessToken, refreshSession, setAccessToken } from "./client";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
const me = { user: {}, permissions: [], superuser: false, password_change_required: false, mfa_enrollment_required: false, instance_name: "x" };

describe("api client", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken(null);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends the bearer token and query string, skipping empty values", async () => {
    setAccessToken("tok");
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    await api("/things", { query: { a: 1, b: "", c: undefined, d: "x y" } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/things?a=1&d=x+y");
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("turns an error envelope into an ApiError", async () => {
    fetchMock.mockResolvedValueOnce(json(403, { error: { code: "forbidden", message: "Nope" } }));
    const err = await api("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(403);
    expect(err.code).toBe("forbidden");
    expect(err.message).toBe("Nope");
  });

  it("refreshes once on an expired token and retries the request", async () => {
    setAccessToken("old");
    fetchMock
      .mockResolvedValueOnce(json(401, { error: { code: "token_expired", message: "expired" } }))
      .mockResolvedValueOnce(json(200, { access_token: "new", expires_in: 900, me }))
      .mockResolvedValueOnce(json(200, { value: 7 }));
    const out = await api<{ value: number }>("/data");
    expect(out.value).toBe(7);
    expect(getAccessToken()).toBe("new");
    const refreshCall = fetchMock.mock.calls[1];
    expect(refreshCall[0]).toBe("/api/v1/auth/refresh");
    expect(refreshCall[1].headers["X-OBS-CSRF"]).toBe("1");
  });

  it("does not retry login failures", async () => {
    fetchMock.mockResolvedValueOnce(json(401, { error: { code: "invalid_credentials", message: "bad" } }));
    await expect(api("/auth/login", { method: "POST", body: {}, auth: false })).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shares one refresh request between concurrent callers", async () => {
    fetchMock.mockResolvedValue(json(200, { access_token: "t", expires_in: 900, me }));
    await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears the token when refresh fails", async () => {
    setAccessToken("stale");
    fetchMock.mockResolvedValueOnce(json(401, { error: { code: "not_authenticated", message: "x" } }));
    expect(await refreshSession()).toBeNull();
    expect(getAccessToken()).toBeNull();
  });
});
