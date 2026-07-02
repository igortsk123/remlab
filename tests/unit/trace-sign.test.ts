import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { signAssetQuery, verifyAssetSig } from "@/lib/trace/sign";

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
