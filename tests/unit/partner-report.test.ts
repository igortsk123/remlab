import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";

import { pageCounterKind } from "@/contracts/analytics";
import { buyerEventKind } from "@/contracts/send";
import { buildReport, firstWeek, mondayOf, weekOf } from "@/modules/partner-report/report";
import { keyHash, MemoryReportRepo } from "@/modules/partner-report/repository";

// Отчёт застройщику (план b2b-03): неделя — когорта по дате отправки в его поясе; шаги — по отправкам;
// статус менеджера — текущий; анонимные счётчики отдельно и только из реестра квартир.

const NOW = new Date("2026-10-21T12:00:00Z"); // среда
const send = (id: string, created: string, over: Partial<{ apartmentId: string; openedAt: Date | null; status: string }> = {}) =>
  ({ id, apartmentId: "flat215", createdAt: new Date(created), openedAt: null, status: "sent", ...over });

describe("отчёт застройщику", () => {
  it("неделя считается по поясу застройщика: воскресенье 22:00 UTC — уже понедельник в Москве", () => {
    expect(weekOf(new Date("2026-10-18T22:00:00Z"), "Europe/Moscow")).toBe("2026-10-19");
    expect(weekOf(new Date("2026-10-18T22:00:00Z"), "Europe/London")).toBe("2026-10-12");
    expect(mondayOf("2026-10-25")).toBe("2026-10-19");
  });

  it("окно — ровно N недель: более ранние отправки и счётчики отсекаются", () => {
    expect(firstWeek(NOW, "Europe/Moscow", 12)).toBe("2026-08-03");
    const r = buildReport({
      sends: [send("old", "2026-08-02T10:00:00Z"), send("in", "2026-08-03T10:00:00Z")], events: [], savedSendIds: [],
      counters: [{ day: "2026-08-02", apartmentId: "flat215", kind: "designer_open", n: 9 }],
      timezone: "Europe/Moscow", now: NOW, fromWeek: firstWeek(NOW, "Europe/Moscow", 12),
    });
    expect(r.total.sent).toBe(1);
    expect(r.direct).toEqual([]);
  });

  it("шаги — по отправкам, неделя — по дате отправки, статус менеджера — текущий", () => {
    const r = buildReport({
      sends: [
        send("a", "2026-10-13T10:00:00Z", { openedAt: new Date("2026-10-20T10:00:00Z"), status: "meeting" }), // открыл на след. неделе — строка недели отправки
        send("b", "2026-10-14T10:00:00Z", { status: "engaged" }),
        send("c", "2026-10-20T10:00:00Z", { apartmentId: "uk1" }),
      ],
      events: [{ sendId: "a", kind: "designer_open" }, { sendId: "a", kind: "manager_contact_click" }, { sendId: "b", kind: "designer_open" },
        { sendId: "b", kind: "item_swap" }, { sendId: "b", kind: "flat3d_open" }, { sendId: "b", kind: "item_move" }, { sendId: "a", kind: "share" }],
      savedSendIds: ["a"],
      counters: [{ day: "2026-10-20", apartmentId: "flat215", kind: "designer_open", n: 3 }, { day: "2026-10-21", apartmentId: "flat215", kind: "designer_open", n: 2 }],
      timezone: "Europe/Moscow", now: NOW,
    });
    const w13 = r.weeks.find((w) => w.week === "2026-10-12")!;
    expect(w13).toMatchObject({ sent: 2, opened: 2, engaged: 2, saved: 1, contactClick: 1, flat3d: 1, moved: 1, shared: 1, fresh: false });
    expect(w13.status).toEqual({ contacted: 0, meeting: 1, deal: 0, lost: 0 });
    expect(r.weeks[0]).toMatchObject({ week: "2026-10-19", sent: 1, opened: 0, fresh: true });
    expect(r.total.sent).toBe(3);
    expect(r.byApartment.map((x) => [x.apartmentId, x.sent])).toEqual([["flat215", 2], ["uk1", 1]]);
    expect(r.direct).toEqual([{ week: "2026-10-19", apartmentId: "flat215", designerOpen: 5, variantView: 0, itemSwap: 0, flat3dOpen: 0, itemMove: 0, share: 0, staleLink: 0, floorPick: 0 }]);
  });

  it("имена событий на демо-странице — из словарей контрактов", () => {
    const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
    const used = (re: RegExp) => [...html.matchAll(re)].map((m) => m[1]!);
    const hits = used(/\bhit\('([a-z0-9_]+)'\)/g);
    const evs = used(/\bev\('([a-z0-9_]+)'/g);
    expect(hits.length).toBeGreaterThan(0);
    expect(evs.length).toBeGreaterThan(0);
    for (const k of hits) expect(pageCounterKind.options).toContain(k);
    for (const k of evs) expect(buyerEventKind.options).toContain(k);
  });
});

describe("ручки отчёта", () => {
  let repo: MemoryReportRepo;
  beforeEach(async () => {
    repo = new MemoryReportRepo();
    (globalThis as unknown as { __remlabReport?: unknown }).__remlabReport = repo;
  });

  it("счётчик: квартира только из реестра, застройщик — из реестра; мусор — 400", async () => {
    const { POST } = await import("@/app/api/events/route");
    const req = (b: unknown) => new Request("http://x/api/events", { method: "POST", body: JSON.stringify(b), headers: { "x-forwarded-for": "10.0.0.1" } });
    expect((await POST(req({ apartmentId: "flat215", kind: "designer_open", lang: "en" }))).status).toBe(204);
    expect([...repo.counters.keys()][0]).toMatch(/^\d{4}-\d{2}-\d{2}\|demo\|flat215\|designer_open\|en$/);
    expect((await POST(req({ apartmentId: "nope", kind: "designer_open" }))).status).toBe(400);
    expect((await POST(req({ apartmentId: "flat215", kind: "collection_save" }))).status).toBe(400);
  });

  it("отчёт: без ключа или с чужим ключом — 403, с ключом — данные своего застройщика", async () => {
    const { GET } = await import("@/app/api/partner/report/route");
    const key = "A".repeat(22);
    repo.keys.set(keyHash(key), "demo");
    const get = (k: string) => GET(new Request("http://x/api/partner/report", { headers: { "x-partner-key": k, "x-forwarded-for": "10.0.0.2" } }));
    expect((await get("")).status).toBe(403);
    expect((await get("B".repeat(22))).status).toBe(403);
    repo.data.set("demo", { sends: [send("a", new Date().toISOString())], events: [], savedSendIds: [], counters: [] });
    repo.data.set("other", { sends: [send("x", new Date().toISOString()), send("y", new Date().toISOString())], events: [], savedSendIds: [], counters: [] });
    const res = await get(key);
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const j = (await res.json()) as { partner: { id: string }; total: { sent: number }; apartments: Record<string, string> };
    expect(j.partner.id).toBe("demo");
    expect(j.total.sent).toBe(1);
    expect(j.apartments.flat215).toBe("кв. 215");
  });
});
