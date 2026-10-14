import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { embedCsp, injectEmbed } from "@/lib/embed/page";

// Встраивание демо (b2b-07): рамкой показывают только мы и домены партнёра; режим встраивания — первым в <head>.
describe("встраивание демо", () => {
  it("frame-ancestors: мы + домены партнёра", () => {
    expect(embedCsp([])).toBe("frame-ancestors 'self'");
    expect(embedCsp(["https://dev.example.ru"])).toBe("frame-ancestors 'self' https://dev.example.ru");
  });

  it("base и режим встраивания — сразу после <head>, до любых адресов", () => {
    const out = injectEmbed('<html><head><meta charset="utf-8"><link href="x.css"></head></html>', { partner: "demo", flat: "flat215", lang: "ru" });
    expect(out.indexOf('<base href="/demo/">')).toBeLessThan(out.indexOf("x.css"));
    expect(out).toContain('window.__sendFlat="flat215"');
  });

  it("мусор в id — отказ", () => {
    expect(() => injectEmbed("<head></head>", { partner: "<x>", flat: "a", lang: "ru" })).toThrow();
  });

  it("ручка: квартира партнёра с витриной — страница с заголовком; чужая/неизвестная — 404", async () => {
    const dir = mkdtempSync(join(tmpdir(), "demo-"));
    writeFileSync(join(dir, "index.html"), "<html><head></head><body>demo</body></html>");
    process.env.DEMO_DIR = dir;
    const { GET } = await import("@/app/embed/[partner]/[flat]/route");
    const ok = await GET(new Request("http://x/embed/demo/flat215"), { params: Promise.resolve({ partner: "demo", flat: "flat215" }) });
    expect(ok.status).toBe(200);
    expect(ok.headers.get("content-security-policy")).toMatch(/^frame-ancestors 'self'/);
    expect(await ok.text()).toContain("__EMBED");
    const bad = await GET(new Request("http://x/embed/demo/nope"), { params: Promise.resolve({ partner: "demo", flat: "nope" }) });
    expect(bad.status).toBe(404);
  });
});

describe("ручки не принимают запись с чужого сайта (b2b-07 п.3)", () => {
  it("чужой Origin — да; свой и отсутствующий — нет", async () => {
    const { foreignOrigin } = await import("@/lib/http/origin");
    const r = (o?: string) => new Request("https://remont-lab.online/api/events", { method: "POST", headers: { host: "remont-lab.online", ...(o ? { origin: o } : {}) } });
    expect(foreignOrigin(r("https://evil.example"))).toBe(true);
    expect(foreignOrigin(r("https://remont-lab.online"))).toBe(false);
    expect(foreignOrigin(r())).toBe(false);
  });
});
