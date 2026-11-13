import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { signAssetQuery, verifyAssetSig } from "@/lib/trace/sign";
import { signedAssetUrl } from "@/lib/trace/admin";
import { publicOrigin, SITE_ORIGIN } from "@/lib/http/origin";

// Подписанные ссылки на ассеты: валидная подпись открывается, просроченная/поддельная — нет,
// токен не раскрывается. Без токена (dev) — доступ открыт.
describe("trace signed asset urls", () => {
  const prev = process.env.TRACE_ADMIN_TOKEN;
  const prevTtl = process.env.TRACE_ASSET_TTL_MS;
  const NOW = 1_700_000_000_000;

  beforeEach(() => {
    process.env.TRACE_ADMIN_TOKEN = "secret-token";
  });
  afterEach(() => {
    if (prev === undefined) delete process.env.TRACE_ADMIN_TOKEN;
    else process.env.TRACE_ADMIN_TOKEN = prev;
    if (prevTtl === undefined) delete process.env.TRACE_ASSET_TTL_MS;
    else process.env.TRACE_ASSET_TTL_MS = prevTtl;
  });

  function parse(q: string): { exp: string; sig: string } {
    const sp = new URLSearchParams(q.startsWith("?") ? q.slice(1) : q);
    return { exp: sp.get("exp")!, sig: sp.get("sig")! };
  }

  it("подписанную ссылку принимает, токен в неё не попадает", () => {
    const q = signAssetQuery("asset-1", NOW);
    expect(q).not.toContain("secret-token");
    const { exp, sig } = parse(q);
    expect(verifyAssetSig("asset-1", exp, sig, NOW)).toBe(true);
  });

  it("просроченную ссылку отклоняет", () => {
    process.env.TRACE_ASSET_TTL_MS = "1000";
    const { exp, sig } = parse(signAssetQuery("asset-1", NOW));
    expect(verifyAssetSig("asset-1", exp, sig, NOW + 2000)).toBe(false);
  });

  it("подделанную подпись отклоняет", () => {
    const { exp } = parse(signAssetQuery("asset-1", NOW));
    expect(verifyAssetSig("asset-1", exp, "deadbeef", NOW)).toBe(false);
  });

  it("подпись одного ассета не подходит другому", () => {
    const { exp, sig } = parse(signAssetQuery("asset-1", NOW));
    expect(verifyAssetSig("asset-2", exp, sig, NOW)).toBe(false);
  });

  it("без exp/sig отклоняет", () => {
    expect(verifyAssetSig("asset-1", null, null, NOW)).toBe(false);
  });

  it("без токена (dev) — доступ открыт, подпись не требуется", () => {
    delete process.env.TRACE_ADMIN_TOKEN;
    expect(signAssetQuery("asset-1", NOW)).toBe("");
    expect(verifyAssetSig("asset-1", null, null, NOW)).toBe(true);
  });
});

// Ссылка на картинку для владельца — на внешний адрес сайта, не на внутренний адрес за прокси (T-20261113-10, П1.54)
describe("trace: абсолютная ссылка на картинку", () => {
  const keep = { base: process.env.TRACE_PUBLIC_BASE_URL, app: process.env.APP_URL, token: process.env.TRACE_ADMIN_TOKEN };
  const NOW = 1_700_000_000_000;
  const req = (headers: Record<string, string> = {}) => new Request("https://0.0.0.0:3000/api/trace/741", { headers });

  beforeEach(() => {
    delete process.env.TRACE_PUBLIC_BASE_URL;
    delete process.env.APP_URL;
    process.env.TRACE_ADMIN_TOKEN = "secret-token";
  });
  afterEach(() => {
    for (const [k, v] of [["TRACE_PUBLIC_BASE_URL", keep.base], ["APP_URL", keep.app], ["TRACE_ADMIN_TOKEN", keep.token]] as const) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  });

  it("за прокси без заголовков — адрес сайта, не 0.0.0.0", () => {
    const u = signedAssetUrl("a-1", req({ host: "0.0.0.0:3000" }), NOW);
    expect(u.startsWith(`${SITE_ORIGIN}/api/trace/asset/a-1?`)).toBe(true);
    expect(u).not.toContain("0.0.0.0");
  });

  it("свой домен из заголовков прокси — он, всегда https", () => {
    expect(publicOrigin(req({ "x-forwarded-host": "remont-lab.online", "x-forwarded-proto": "http" }))).toBe("https://remont-lab.online");
    expect(publicOrigin(req({ "x-forwarded-host": "dev.remont-lab.online" }))).toBe("https://dev.remont-lab.online");
  });

  it("чужой хост в заголовках — адрес сайта", () => {
    expect(publicOrigin(req({ "x-forwarded-host": "evil.example" }))).toBe(SITE_ORIGIN);
    expect(publicOrigin(req({ host: "remont-lab.online.evil.example" }))).toBe(SITE_ORIGIN);
  });

  it("переменная окружения главнее заголовков", () => {
    process.env.TRACE_PUBLIC_BASE_URL = "https://trace.remont-lab.online/";
    expect(signedAssetUrl("a-1", req({ "x-forwarded-host": "remont-lab.online" }), NOW)
      .startsWith("https://trace.remont-lab.online/api/trace/asset/a-1?")).toBe(true);
  });

  it("подпись в ссылке проходит проверку ручки картинки", () => {
    const u = new URL(signedAssetUrl("a-1", req(), NOW));
    expect(verifyAssetSig("a-1", u.searchParams.get("exp"), u.searchParams.get("sig"), NOW)).toBe(true);
    expect(u.toString()).not.toContain("secret-token");
  });
});
