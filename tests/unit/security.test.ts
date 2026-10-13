import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { checkLimits, PRESETS, windowStart } from "@/lib/ratelimit";
import { clientIp } from "@/lib/ratelimit/http";
import { MemoryCounterStore, type CounterStore } from "@/lib/ratelimit/store";
import { isYookassaIp } from "@/lib/payments/yookassa-ip";
import { traceAdminOk } from "@/lib/trace/admin";
import { verifyAssetSig } from "@/lib/trace/sign";
import { MemoryShareRequestRepository } from "@/modules/share-requests/repository";

// Безопасность перед показом застройщику (план b2b-01): каждая проверка — то, что ломалось или
// было открыто 13.10; тест краснеет ровно тогда, когда защита снова пропадает.

const T0 = Date.UTC(2026, 9, 13, 12, 0, 0);

describe("лимиты частоты", () => {
  it("parse-link: 10 в минуту с адреса проходят, 11-й — 429 с ожиданием до конца окна", async () => {
    const store = new MemoryCounterStore();
    const set = PRESETS.parseLink("1.2.3.4");
    for (let i = 0; i < 10; i++) expect((await checkLimits(set, T0 + i, store)).ok).toBe(true);
    const r = await checkLimits(set, T0 + 10, store);
    expect(r).toMatchObject({ ok: false, reason: "rate" });
    if (!r.ok) expect(r.retryAfterSec).toBeLessThanOrEqual(60);
  });

  it("другой адрес считается отдельно, новое окно — снова можно", async () => {
    const store = new MemoryCounterStore();
    for (let i = 0; i < 11; i++) await checkLimits(PRESETS.parseLink("1.1.1.1"), T0, store);
    expect((await checkLimits(PRESETS.parseLink("2.2.2.2"), T0, store)).ok).toBe(true);
    expect((await checkLimits(PRESETS.parseLink("1.1.1.1"), T0 + 61_000, store)).ok).toBe(true);
  });

  it("дневной потолок на весь сайт срабатывает, даже если каждый адрес новый", async () => {
    process.env.PAID_DAILY_CAP_GEN = "3";
    const store = new MemoryCounterStore();
    const res = [];
    for (let i = 0; i < 4; i++) res.push(await checkLimits(PRESETS.generate(`10.0.0.${i}`), T0, store));
    delete process.env.PAID_DAILY_CAP_GEN;
    expect(res.slice(0, 3).every((r) => r.ok)).toBe(true);
    expect(res[3]).toMatchObject({ ok: false, reason: "daily_cap" });
  });

  it("сбой хранилища: платное закрыто, бесплатное открыто", async () => {
    const broken: CounterStore = { hit: () => Promise.reject(new Error("db down")), prune: async () => {} };
    expect(await checkLimits(PRESETS.generate("1.1.1.1"), T0, broken)).toMatchObject({ ok: false, reason: "unavailable" });
    expect((await checkLimits(PRESETS.flatConfig("1.1.1.1"), T0, broken)).ok).toBe(true);
  });

  it("окно выровнено по началу минуты/суток", () => {
    expect(windowStart(T0 + 59_999, 60).getTime()).toBe(T0);
    expect(windowStart(T0 + 5, 86_400).toISOString()).toBe("2026-10-13T00:00:00.000Z");
  });

  it("адрес клиента — первое значение X-Forwarded-For; без заголовка — local", () => {
    expect(clientIp(new Headers({ "x-forwarded-for": "5.6.7.8, 172.18.0.1" }))).toBe("5.6.7.8");
    expect(clientIp(new Headers({ "x-forwarded-for": "2a02:6b8::1" }))).toBe("2a02:6b8::1");
    expect(clientIp(new Headers())).toBe("local");
  });
});

describe("вебхук ЮKassa: только её адреса", () => {
  it.each([
    ["185.71.76.5", true],
    ["185.71.76.40", false],
    ["77.75.156.11", true],
    ["77.75.156.12", false],
    ["77.75.154.200", true],
    ["2a02:5180:0:1::5", true],
    ["2a02:5181::1", false],
    ["::ffff:185.71.77.1", true],
    ["1.2.3.4", false],
    ["local", false],
  ])("%s → %s", (ip, ok) => expect(isYookassaIp(ip)).toBe(ok));
});

describe("трейсы с фото пользователей", () => {
  const prevToken = process.env.TRACE_ADMIN_TOKEN;
  beforeEach(() => vi.stubEnv("NODE_ENV", "production"));
  afterEach(() => {
    vi.unstubAllEnvs();
    if (prevToken === undefined) delete process.env.TRACE_ADMIN_TOKEN;
    else process.env.TRACE_ADMIN_TOKEN = prevToken;
  });

  it("на проде без секрета закрыто — и разбор, и подписанные фото", () => {
    delete process.env.TRACE_ADMIN_TOKEN;
    expect(traceAdminOk(new Request("https://x/api/trace/1"))).toBe(false);
    expect(verifyAssetSig("a1", null, null, T0)).toBe(false);
  });

  it("токен принимается только заголовком, не из адреса", () => {
    process.env.TRACE_ADMIN_TOKEN = "s3cret";
    expect(traceAdminOk(new Request("https://x/api/trace/1?token=s3cret"))).toBe(false);
    expect(traceAdminOk(new Request("https://x/api/trace/1", { headers: { "x-trace-token": "s3cret" } }))).toBe(true);
    expect(traceAdminOk(new Request("https://x/api/trace/1", { headers: { "x-trace-token": "s3cre" } }))).toBe(false);
  });
});

describe("заявки «отправить себе»", () => {
  it("контакт хранится 90 дней и удаляется по сроку", async () => {
    const repo = new MemoryShareRequestRepository();
    const now = new Date(T0);
    await repo.create({ shareId: "abc123", shareUrl: "https://x/test/share/abc123/", channel: "telegram", contact: "@me", shotCount: 2 }, now);
    expect(await repo.purgeExpired(new Date(T0 + 89 * 86_400_000))).toBe(0);
    expect(await repo.purgeExpired(new Date(T0 + 91 * 86_400_000))).toBe(1);
    expect(repo.rows).toHaveLength(0);
  });
});
