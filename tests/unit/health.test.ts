import { describe, it, expect } from "vitest";
import { buildHealth } from "@/lib/health";

describe("buildHealth", () => {
  it("возвращает ok:true и сервис remlab", () => {
    const h = buildHealth(new Date("2026-07-01T00:00:00.000Z"));
    expect(h.ok).toBe(true);
    expect(h.service).toBe("remlab");
    expect(h.ts).toBe("2026-07-01T00:00:00.000Z");
  });

  it("version берётся из APP_VERSION или dev", () => {
    const prev = process.env.APP_VERSION;
    process.env.APP_VERSION = "test-123";
    expect(buildHealth().version).toBe("test-123");
    delete process.env.APP_VERSION;
    expect(buildHealth().version).toBe("dev");
    if (prev !== undefined) process.env.APP_VERSION = prev;
  });
});
