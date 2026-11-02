import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "../app/api/[...path]/route";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
it("rejects traversal before upstream access", async () => {
  const upstream = vi.fn();
  vi.stubGlobal("fetch", upstream);
  const r = await GET(new NextRequest("http://localhost/api/v1/health"), {
    params: Promise.resolve({ path: ["v1", "..", "secret"] }),
  });
  expect(r.status).toBe(404);
  expect(upstream).not.toHaveBeenCalled();
});
it("forwards only bounded authorization/content headers to a fixed upstream", async () => {
  vi.stubEnv("ASSESSMENT_API_ORIGIN", "http://127.0.0.1:8000");
  const upstream = vi.fn().mockResolvedValue(
    new Response("{}", {
      headers: {
        "Content-Type": "application/json",
        "Set-Cookie": "secret=bad",
        "X-Request-ID": "test-id",
      },
    }),
  );
  vi.stubGlobal("fetch", upstream);
  const r = await POST(
    new NextRequest("http://localhost/api/v1/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer test-only",
        Cookie: "private-cookie=1",
        "X-Forwarded-Host": "attacker.invalid",
      },
      body: "{}",
    }),
    { params: Promise.resolve({ path: ["v1", "auth", "login"] }) },
  );
  const [url, options] = upstream.mock.calls[0];
  expect(url.href).toBe("http://127.0.0.1:8000/api/v1/auth/login");
  expect(options.headers.get("cookie")).toBeNull();
  expect(options.headers.get("x-forwarded-host")).toBeNull();
  expect(r.headers.get("set-cookie")).toBeNull();
  expect(r.headers.get("cache-control")).toBe("no-store");
});
it("returns a generic problem on upstream failure", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private DSN")));
  const r = await GET(new NextRequest("http://localhost/api/v1/health"), {
    params: Promise.resolve({ path: ["v1", "health"] }),
  });
  expect(r.status).toBe(503);
  expect(await r.text()).not.toContain("private DSN");
});
