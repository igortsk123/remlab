import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isLiveCheck, LIVE_CHECK_HEADER } from "@/lib/http/live-check";
import { MemoryReportRepo } from "@/modules/partner-report/repository";
import { createSend } from "@/modules/sends/service";
import { MemorySendStore } from "@/modules/sends/store-memory";
import type { Manager } from "@/modules/sends/types";

// Живые проверки прода — не покупатели (T-20261018-18): с меткой `x-remlab-check: 1` сервер отвечает как обычно, но не пишет
// счётчики застройщика, события ссылки менеджера и серверную аналитику.

const mark = vi.hoisted(() => ({ on: false }));
vi.mock("next/headers", () => ({ headers: async () => new Headers(mark.on ? { "x-remlab-check": "1" } : {}) }));

const g = globalThis as unknown as { __remlabReport?: unknown; __remlabSendStore?: unknown };
const post = (url: string, body: unknown, check: boolean) => new Request(url, {
  method: "POST", body: JSON.stringify(body),
  headers: { "x-forwarded-for": "10.0.0.2", ...(check ? { [LIVE_CHECK_HEADER]: "1" } : {}) },
});

describe("метка живой проверки", () => {
  it("признак — ровно «1», без метки и с другим значением — обычный посетитель", () => {
    expect(isLiveCheck(new Headers({ "x-remlab-check": "1" }))).toBe(true);
    expect(isLiveCheck(new Headers({ "X-Remlab-Check": "1" }))).toBe(true);
    expect(isLiveCheck(new Headers())).toBe(false);
    expect(isLiveCheck(new Headers({ "x-remlab-check": "0" }))).toBe(false);
    expect(isLiveCheck(new Headers({ "x-remlab-check": "true" }))).toBe(false);
  });
});

describe("счётчик страницы /api/events", () => {
  let repo: MemoryReportRepo;
  beforeEach(() => { repo = new MemoryReportRepo(); g.__remlabReport = repo; });

  it("с меткой — тот же 204, но счётчик не растёт; без метки — растёт", async () => {
    const { POST } = await import("@/app/api/events/route");
    const ev = { apartmentId: "flat215", kind: "variant_view", lang: "ru" };
    expect((await POST(post("http://x/api/events", ev, true))).status).toBe(204);
    expect(repo.counters.size).toBe(0);
    expect((await POST(post("http://x/api/events", ev, false))).status).toBe(204);
    expect([...repo.counters.values()]).toEqual([1]);
  });

  it("с меткой мусор по-прежнему 400 — ответ не отличается от обычного", async () => {
    const { POST } = await import("@/app/api/events/route");
    expect((await POST(post("http://x/api/events", { apartmentId: "nope", kind: "designer_open" }, true))).status).toBe(400);
    expect(repo.counters.size).toBe(0);
  });
});

describe("событие по ссылке менеджера /api/sends/:id/event", () => {
  let store: MemorySendStore;
  const mgr: Manager = {
    id: "m1", partnerId: "demo", displayName: "Анна", publicPhone: "+7 913 000-00-00", publicTelegram: null,
    publicWhatsapp: null, connectPhone: "79130000000", tgUserId: 501, tgChatId: 501, pageKey: "k".repeat(22), active: true,
  };
  beforeEach(() => { store = new MemorySendStore(); store.managers.set("m1", mgr); g.__remlabSendStore = store; });
  afterEach(() => { delete g.__remlabSendStore; });

  it("с меткой — тот же ответ, но без события, первого открытия и сигнала менеджеру; чужая ссылка — 404", async () => {
    const { POST } = await import("@/app/api/sends/[id]/event/route");
    const s = (await createSend(mgr, "flat215", "page", null, new Date(), store))!;
    const outbox = store.outbox.length;
    const call = (id: string) => POST(post(`http://x/api/sends/${id}/event`, { kind: "designer_open" }, true), { params: Promise.resolve({ id }) });
    const res = await call(s.id);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(store.eventRows).toEqual([]);
    expect(store.sends.get(s.id)?.openedAt ?? null).toBeNull();
    expect(store.outbox.length).toBe(outbox);
    expect((await call("A".repeat(22))).status).toBe(404);
  });
});

describe("серверная аналитика (PostHog)", () => {
  const fetchMock = vi.fn(async () => new Response("{}"));
  beforeEach(() => { process.env.POSTHOG_KEY = "test-key"; vi.stubGlobal("fetch", fetchMock); fetchMock.mockClear(); });
  afterEach(() => { delete process.env.POSTHOG_KEY; vi.unstubAllGlobals(); mark.on = false; });

  it("событие живой проверки не уходит, ошибка — уходит; обычный посетитель — уходит", async () => {
    const { track, captureError } = await import("@/lib/analytics");
    mark.on = true;
    await track("estimate_created", "s1");
    expect(fetchMock).not.toHaveBeenCalled();
    await captureError(new Error("boom"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    mark.on = false;
    await track("estimate_created", "s1");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
