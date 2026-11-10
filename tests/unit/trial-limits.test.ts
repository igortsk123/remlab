import { describe, expect, it } from "vitest";

import { checkLimits, PRESETS } from "@/lib/ratelimit";
import { MemoryCounterStore } from "@/lib/ratelimit/store";
import { trialDailyCap, trialFileHours, trialResultDays } from "@/lib/trial/config";
import { isOwnMachine, TRIAL_OWN_HEADER } from "@/lib/trial/own-key";

// Проба: лимиты загрузки и срок исходного плана (владелец 10.11, TG 744; T-20261110-24): с адреса 10 в час и 30 в сутки, на сайт 300,
// наши машины — без лимита по ключу; исходный план живёт столько же, сколько тур (30 дн.).

const DAY0 = Date.UTC(2026, 10, 10, 1, 0, 0); // 01:00 UTC — до конца суток далеко, окна часа выровнены
const H = 3_600_000;
const E = (e: Record<string, string> = {}) => e as NodeJS.ProcessEnv;

describe("лимит загрузки пробы с адреса", () => {
  it("10 в час проходят, 11-й — 429 «подряд» с ожиданием не дольше часа", async () => {
    const store = new MemoryCounterStore();
    const set = PRESETS.trialUpload("7.7.7.7");
    for (let i = 0; i < 10; i++) expect((await checkLimits(set, DAY0 + i * 1000, store)).ok).toBe(true);
    const r = await checkLimits(set, DAY0 + 10_000, store);
    expect(r).toMatchObject({ ok: false, reason: "rate" });
    if (!r.ok) expect(r.retryAfterSec).toBeLessThanOrEqual(3600);
    expect((await checkLimits(PRESETS.trialUpload("7.7.7.8"), DAY0 + 10_000, store)).ok).toBe(true); // другой адрес — отдельно
  });

  it("30 в сутки проходят (по 10 в разные часы), 31-й — 429 до конца суток UTC (дольше часа — форма пишет «на сегодня»)", async () => {
    const store = new MemoryCounterStore();
    const set = PRESETS.trialUpload("8.8.8.8");
    for (let i = 0; i < 30; i++) expect((await checkLimits(set, DAY0 + Math.floor(i / 10) * H + i * 1000, store)).ok).toBe(true);
    const r = await checkLimits(set, DAY0 + 3 * H, store);
    expect(r).toMatchObject({ ok: false, reason: "rate" });
    if (!r.ok) expect(r.retryAfterSec).toBe(20 * 3600); // 04:00 → 00:00 UTC следующих суток
  });
});

describe("наши машины — ключ TRIAL_OWN_KEY", () => {
  const KEY = "k".repeat(40);
  const h = (v?: string) => new Headers(v === undefined ? {} : { [TRIAL_OWN_HEADER]: v });

  it("верный ключ — да; неверный, пустой, другой длины — нет", () => {
    const env = E({ TRIAL_OWN_KEY: KEY });
    expect(isOwnMachine(h(KEY), env)).toBe(true);
    expect(isOwnMachine(h("k".repeat(39) + "x"), env)).toBe(false);
    expect(isOwnMachine(h(KEY + "k"), env)).toBe(false);
    expect(isOwnMachine(h(""), env)).toBe(false);
    expect(isOwnMachine(h(), env)).toBe(false);
  });

  it("на сервере ключа нет или он короче 32 знаков — пропуска нет ни у кого", () => {
    expect(isOwnMachine(h(KEY), E())).toBe(false);
    expect(isOwnMachine(h(""), E({ TRIAL_OWN_KEY: "" }))).toBe(false);
    expect(isOwnMachine(h("short"), E({ TRIAL_OWN_KEY: "short" }))).toBe(false);
  });
});

describe("сроки и потолок пробы", () => {
  it("исходный файл — 30 дней (как тур); env только укорачивает", () => {
    expect(trialResultDays(E())).toBe(30);
    expect(trialFileHours(E())).toBe(30 * 24);
    expect(trialFileHours(E({ TRIAL_FILE_RETENTION_HOURS: "" }))).toBe(30 * 24);
    expect(trialFileHours(E({ TRIAL_FILE_RETENTION_HOURS: "24" }))).toBe(24);
    expect(trialFileHours(E({ TRIAL_FILE_RETENTION_HOURS: "99999" }))).toBe(30 * 24);
    expect(trialFileHours(E({ TRIAL_RESULT_RETENTION_DAYS: "60" }))).toBe(60 * 24);
  });

  it("суточный потолок сайта — 300 по умолчанию", () => {
    expect(trialDailyCap(E())).toBe(300);
    expect(trialDailyCap(E({ TRIAL_DAILY_CAP: "50" }))).toBe(50);
  });
});
