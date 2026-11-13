// Ссылка-вход /api/lab/mesh-review/session (T-20261112-118/3): за прокси req.url — внутренний хост (https://0.0.0.0:3000),
// поэтому Location только относительный и только из списка; кука ставится как раньше.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/lab/mesh-review/session/route";
import { cookieValue } from "@/lib/mesh-review/auth";
import { DEFAULT_LOGIN_TARGET, loginTarget } from "@/lib/mesh-review/login-target";

const SECRET = "test-secret-not-real";
const INNER = "https://0.0.0.0:3000"; // так req.url выглядит за прокси на проде

function call(qs: string): Promise<Response> {
  return GET(new Request(`${INNER}/api/lab/mesh-review/session?${qs}`));
}

describe("ссылка-вход mesh-review", () => {
  beforeEach(() => vi.stubEnv("MESH_REVIEW_SECRET", SECRET));
  afterEach(() => vi.unstubAllEnvs());

  it("верный ключ: 302 на относительный путь по умолчанию, без внутреннего хоста", async () => {
    const res = await call(`key=${SECRET}`);
    expect(res.status).toBe(302);
    const loc = res.headers.get("location") ?? "";
    expect(loc).toBe("/lab/mesh-review");
    expect(loc).not.toContain("0.0.0.0");
    expect(loc.startsWith("/")).toBe(true);
  });

  it("кука ставится: HttpOnly, Secure, SameSite=Lax, путь /, значение — подпись", async () => {
    const res = await call(`key=${SECRET}`);
    const set = res.headers.get("set-cookie") ?? "";
    expect(set).toContain(`mesh_review=${cookieValue()}`);
    expect(set).toMatch(/HttpOnly/i);
    expect(set).toMatch(/Secure/i);
    expect(set).toMatch(/SameSite=lax/i);
    expect(set).toMatch(/Path=\//);
    expect(set).not.toContain(SECRET);
  });

  it("to=/lab/mesh-check ведёт на проверку мешей", async () => {
    const res = await call(`key=${SECRET}&to=${encodeURIComponent("/lab/mesh-check")}`);
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/lab/mesh-check");
  });

  it.each(["https://evil.example", "//evil.example", "/lab/mesh-check/../../admin", "/lab/mesh-checkX", "/", ""])(
    "to=%s вне списка — путь по умолчанию (не открытый редирект)",
    async (to) => {
      const res = await call(`key=${SECRET}&to=${encodeURIComponent(to)}`);
      expect(res.headers.get("location")).toBe(DEFAULT_LOGIN_TARGET);
    },
  );

  it("неверный или пустой ключ: 401 без куки и без редиректа", async () => {
    for (const qs of ["key=wrong", "", "to=/lab/mesh-check"]) {
      const res = await call(qs);
      expect(res.status).toBe(401);
      expect(res.headers.get("set-cookie")).toBeNull();
      expect(res.headers.get("location")).toBeNull();
    }
  });

  it("секрета в env нет: 503 (fail-closed)", async () => {
    vi.stubEnv("MESH_REVIEW_SECRET", "");
    const res = await call(`key=${SECRET}`);
    expect(res.status).toBe(503);
  });

  it("loginTarget: только пути из списка", () => {
    expect(loginTarget("/lab/mesh-check")).toBe("/lab/mesh-check");
    expect(loginTarget("/lab/mesh-review")).toBe("/lab/mesh-review");
    expect(loginTarget(null)).toBe(DEFAULT_LOGIN_TARGET);
    expect(loginTarget("https://remont-lab.online/lab/mesh-check")).toBe(DEFAULT_LOGIN_TARGET);
  });
});
