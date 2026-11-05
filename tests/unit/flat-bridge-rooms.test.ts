import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { fromDemoVariant, type DemoContext, type DemoData } from "@/lib/configurator/fromDemo";
import { ROOM_GAP_CM } from "@/lib/configurator/demo-rooms";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { loadFlat3d } from "@/lib/configurator/data";
import { VIEW_BACK_CM } from "@/lib/viewer3d/opening-ir";
import { isIsolatedRoom } from "@/contracts/apartment";

// МОСТ /flat ПО КОМНАТАМ (onb-11, T-20261105-12): места, цены и отделка — по `room_id` варианта витрины, итог — по комнатам и общий.
// Образец — живая витрина 05.11 (урезаны ленты), эталон — вывод моста ДО onb-11 на нём же (sha256), контексты квартир заморожены:
// правка реестра застройщиков не должна краснить проверку «гостиная без изменений».
const live = JSON.parse(readFileSync("tests/fixtures/flat-bridge-live-0511.json", "utf8")) as DemoData;
const gold = JSON.parse(readFileSync("tests/fixtures/flat-bridge-live-0511.golden.json", "utf8")) as {
  golden: Record<string, { sha256: string; slots: number; options: number; total: number; byRoom: Record<string, number> }>;
  contexts: Record<string, DemoContext>;
};

const build = (data: DemoData, variantId: string, ctx: DemoContext) => {
  const r = fromDemoVariant(data, variantId, ctx)!;
  const totals = resolveScene(r.apartment, r.catalogue, defaultConfiguration(r.apartment, r.catalogue)).totals;
  return { ...r, totals };
};

describe("гостиная без изменений (живые данные 05.11)", () => {
  for (const [key, want] of Object.entries(gold.golden)) {
    it(key, () => {
      const [flat, variant] = key.split("/") as [string, string];
      const r = build(live, variant, gold.contexts[flat]!);
      // сначала понятная сводка (что разошлось), потом отпечаток всего вывода
      expect({ slots: r.apartment.slots.length, options: r.catalogue.options.length, total: r.totals.total, byRoom: r.totals.byRoom })
        .toEqual({ slots: want.slots, options: want.options, total: want.total, byRoom: want.byRoom });
      expect(createHash("sha256").update(JSON.stringify({ apartment: r.apartment, catalogue: r.catalogue, totals: r.totals })).digest("hex"))
        .toBe(want.sha256);
    });
  }
});

describe("вторая комната по room_id", () => {
  const RU = gold.contexts.flat215!;
  const set16 = live.variants!.find((v) => v.id === "set16")!;
  // выдуманная спальня: та же мебель, что у set16, но в комнате bedroom-1 (геометрии rooms_geo у неё нет — фолбэк на гостиную)
  const bed = { ...structuredClone(set16), id: "bed1", room_id: "bedroom-1" };
  const withBed: DemoData = { ...live, variants: [...live.variants!, bed] };
  const livingW = live.room!.w!, livingD = live.room!.d!;

  it("комната появляется со своими местами, сдвигом и суммой; гостиная — та же", () => {
    const r = build(withBed, "set16", RU);
    const alone = build(live, "set16", RU);
    expect(r.apartment.rooms.map((x) => [x.id, x.kind, x.titleRu, x.x, x.y])).toEqual([
      ["living", "living", live.room!.title, 0, 0],
      ["bedroom-1", "bedroom", "Спальня 1", livingW + ROOM_GAP_CM, livingD + ROOM_GAP_CM],
    ]);
    // гостиная: те же места, те же опции и та же сумма, что без спальни
    expect(r.apartment.slots.filter((s) => s.roomId === "living")).toEqual(alone.apartment.slots);
    expect(r.catalogue.options.slice(0, alone.catalogue.options.length)).toEqual(alone.catalogue.options);
    expect(r.totals.byRoom.living).toBe(alone.totals.byRoom.living);
    // спальня: все места и их опции — со своей приставкой (сохранённый выбор гостиной не переезжает)
    const bedSlots = r.apartment.slots.filter((s) => s.roomId === "bedroom-1");
    expect(bedSlots.length).toBe(alone.apartment.slots.length);
    for (const s of bedSlots) {
      expect(s.id.startsWith("bedroom-1/")).toBe(true);
      for (const o of s.optionIds) expect(o).toMatch(/^(opt|feed):bedroom-1\//);
      if (s.selectionGroup) expect(s.selectionGroup.startsWith("bedroom-1/")).toBe(true);
      if (s.placement && !s.tabletop) {
        const twin = alone.apartment.slots.find((x) => `bedroom-1/${x.id}` === s.id)!;
        expect(s.placement.x).toBe(twin.placement!.x + livingW + ROOM_GAP_CM);
        expect(s.placement.y).toBe(twin.placement!.y + livingD + ROOM_GAP_CM);
      }
    }
    expect(new Set(r.apartment.slots.map((s) => s.id)).size).toBe(r.apartment.slots.length);
    expect(new Set(r.catalogue.options.map((o) => o.id)).size).toBe(r.catalogue.options.length);
    // сумма спальни — мебель её варианта (отделка паспорта без доплаты); общий итог — квартира + обе комнаты
    const noChoice = { ...RU, floorChoice: undefined, wallChoice: undefined };
    expect(r.totals.byRoom["bedroom-1"]).toBe(build(live, "set16", noChoice).totals.upgrades);
    expect(r.totals.byRoom["bedroom-1"]).toBeGreaterThan(0);
    expect(r.totals.total).toBe(RU.basePrice + r.totals.byRoom.living! + r.totals.byRoom["bedroom-1"]!);
    // ракурсы спальни — в её комнате
    expect(r.apartment.cameras.filter((c) => c.roomId === "bedroom-1").every((c) => c.id.startsWith("bedroom-1/"))).toBe(true);
  });

  it("открыли вариант спальни: старт в спальне, в гостиной — вариант того же стиля", () => {
    const r = build(withBed, "bed1", RU);
    const b = r.apartment.rooms.find((x) => x.id === "bedroom-1")!;
    expect(r.apartment.spawn.x).toBe(b.x + b.w / 2);
    expect(r.apartment.titleRu).toBe("Джапанди — Спальня 1");
    expect(r.apartment.slots.filter((s) => s.roomId === "living")).toEqual(build(live, "set16", RU).apartment.slots);
  });

  it("комнаты без вариантов нет; вариант без мебели с моделью комнату не создаёт", () => {
    const empty = { ...bed, id: "bed2", room_id: "bedroom-2", items: bed.items!.map((it) => ({ ...it, sku: { ...it.sku, msid: undefined } })) };
    const r = build({ ...withBed, variants: [...withBed.variants!, empty] }, "set1", RU);
    expect(r.apartment.rooms.map((x) => x.id)).toEqual(["living", "bedroom-1"]);   // кухни, прихожей, санузлов, спальни 2 — нет
  });

  it("лесенка: вид за окном любой комнаты не входит в соседнюю, двери без соседей закрыты", () => {
    const three = { ...withBed, variants: [...withBed.variants!, { ...bed, id: "k1", room_id: "kitchen" }] };
    const a = build(three, "set16", RU).apartment;
    expect(a.rooms.map((x) => x.id)).toEqual(["living", "kitchen", "bedroom-1"]);   // порядок — по ordinal реестра
    // плоскость вида — на VIEW_BACK_CM (+ кайма ≤ 2 см) за стеной, параллельно ей: у соседа по каждой оси зазор больше
    for (const p of a.rooms) for (const q of a.rooms) if (p !== q) {
      const gapX = Math.max(q.x - (p.x + p.w), p.x - (q.x + q.w)), gapY = Math.max(q.y - (p.y + p.d), p.y - (q.y + q.d));
      expect(Math.min(gapX, gapY)).toBeGreaterThan(VIEW_BACK_CM + 2);
    }
    expect(a.rooms.every((x) => isIsolatedRoom(a, x))).toBe(true);
    // у квартиры 3D (британская, смежные комнаты) двери по-прежнему открыты
    const flat3d = loadFlat3d().apartment;
    expect(flat3d.rooms.some((x) => isIsolatedRoom(flat3d, x))).toBe(false);
  });

  it("своя геометрия комнаты — из rooms_geo", () => {
    const geo = { w: 618, d: 293, title: "Спальня 1 18.1 м²", finish: { wall: { id: "paint-white", colorHex: "#e8e4dc" } },
      openings: [{ kind: "window", wall: "north", offset_cm: 200, width_cm: 150, sill_cm: 85, height_cm: 150 }] };
    const r = build({ ...withBed, rooms_geo: { "bedroom-1": geo } }, "set16", RU);
    const b = r.apartment.rooms.find((x) => x.id === "bedroom-1")!;
    expect([b.w, b.d, b.titleRu, b.openings.length]).toEqual([618, 293, "Спальня 1 18.1 м²", 1]);
    // цвет стен спальни — её паспорт, отдельным материалом (тот же id паспорта у гостиной цвета не меняет)
    const wallOpt = r.catalogue.options.find((o) => o.id === "opt:bedroom-1/wall")!;
    const mat = r.catalogue.materials.find((m) => wallOpt.asset.kind === "material" && m.id === wallOpt.asset.materialId)!;
    expect(mat.colorHex).toBe("#e8e4dc");
    expect(r.apartment.areaM2).toBe(Math.round(((livingW * live.room!.d! + 618 * 293) / 10000) * 10) / 10);
  });
});
