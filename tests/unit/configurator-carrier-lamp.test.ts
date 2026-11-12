import { describe, expect, it } from "vitest";

import { isCarrierDecor, onCarrier } from "@/lib/configurator/carrier-decor";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { sceneSlotIndex } from "@/lib/viewer3d/demo-scene";

// T-20261112-101: лампа на комоде — место решателя паспорта (`dependent_decor.lamp_row`), сцена пересчитывает его от ТЕКУЩЕГО комода
// (`carrier-decor.placeOnCarriers`); нет комода или не влезает — `unplaced`, цена остаётся; ряд ваз — отдельно
const CTX = { apartmentId: "t", partnerId: "demo", currency: "RUB" as const, basePrice: 0, assetBase: "/demo/demo-data.json" };
const SOFA = { role: "диван", x: 200, y: 305, rot: 180, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, msid: "s_1" } };
const TABLE = { role: "столик", x: 150, y: 180, rot: 0, w: 80, d: 50, h: 45, sku: { name: "Столик", price: 9000, msid: "t_1" } };
const DRESSER = { role: "комод", x: 60, y: 120, rot: 90, w: 120, d: 45, h: 80, sku: { name: "Комод Берг", price: 20000, msid: "c_1" } };
const fit = { edge_inset_min_cm: 8, edge_inset_over_half_base_cm: 3, max_share_of_top: 0.2 };
const place = { x: 60, y: 120, bottom_cm: 80, slot_instance_id: "light.lamp#0", parent_slot_instance_id: "light.dresser#0",
  anchor: { kind: "item_surface", surface: "top" }, local: { dx: 0, dy: 0 }, carrier: { role: "комод", ordinal: 0 }, fit };
const LAMP = { role: "лампа", strategy: "carrier_surface", place, sku: { name: "Лампа", price: 4000, msid: "lp_1", w: 25, d: 25, h: 50 } };
const VASE = { role: "ваза", sku: { name: "Ваза", price: 1500, msid: "v_1", w: 15, d: 15, h: 30 } };

const scene = (items: object[], decor: object[], moved?: Record<string, { x: number; y: number; rot: number }>) => {
  const data = { room: { w: 400, d: 350, title: "Комната", height_cm: 270, openings: [] },
    variants: [{ id: "v", style: "сканди", items, decor }] };
  const built = fromDemoVariant(data as never, "v", CTX)!;
  const cfg = defaultConfiguration(built.apartment, built.catalogue);
  const sc = resolveScene(built.apartment, built.catalogue, moved ? { ...cfg, placements: { ...cfg.placements, ...moved } } : cfg);
  const slot = built.apartment.slots.find((s) => s.onCarrier);
  return { built, sc, slot, lamp: sc.items.find((i) => i.photoRole === "лампа"), dresser: sc.items.find((i) => i.photoRole === "комод") };
};

describe("лампа на комоде — строка декора `carrier_surface`", () => {
  it("без модели, носителя или нормы — не лампа сцены", () => {
    expect(isCarrierDecor(LAMP)).toBe(true);
    expect(isCarrierDecor({ ...LAMP, sku: { ...LAMP.sku, msid: undefined } })).toBe(false);
    expect(isCarrierDecor({ ...LAMP, place: { ...place, carrier: undefined } })).toBe(false);
    expect(isCarrierDecor({ ...LAMP, place: { ...place, fit: undefined } })).toBe(false);
    expect(isCarrierDecor({ ...LAMP, list_only: true })).toBe(false);
  });

  it("встаёт на верх комода, связь с местом комода — явная; в цене", () => {
    const { slot, lamp, dresser, sc } = scene([SOFA, TABLE, DRESSER], [LAMP]);
    expect(slot!.onCarrier!.slotId).toBe(dresser!.slotId);
    expect(slot!.tabletop).toBeUndefined();
    expect(lamp!.unplaced).toBeUndefined();
    expect(lamp!.placement).toMatchObject({ x: dresser!.placement.x, y: dresser!.placement.y, rot: 90, elevCm: 80 });
    expect(lamp!.price).toBe(4000);
    expect(sc.totals.total).toBe(50000 + 9000 + 20000 + 4000);
  });

  it("✥: комод передвинули и повернули — лампа идёт за ним (поза в осях комода)", () => {
    const off = { ...LAMP, place: { ...place, local: { dx: 20, dy: 0 } } };
    const base = scene([SOFA, TABLE, DRESSER], [off]);
    const id = base.dresser!.slotId;
    const { lamp, dresser } = scene([SOFA, TABLE, DRESSER], [off], { [id]: { x: 300, y: 100, rot: 0 } });
    expect(dresser!.placement).toMatchObject({ x: 300, y: 100, rot: 0 });
    expect(lamp!.placement.x).toBeCloseTo(320);
    expect(lamp!.placement.y).toBeCloseTo(100);
    expect(lamp!.placement.rot).toBe(0);
  });

  it("маленький комод (не влезает по норме) и комода нет — в сцене нет, в цене есть", () => {
    const small = scene([SOFA, TABLE, { ...DRESSER, w: 40, d: 30 }], [LAMP]);
    expect(small.lamp!.unplaced).toBe(true);
    expect(small.lamp!.price).toBe(4000);
    const none = scene([SOFA, TABLE], [LAMP]);
    expect(none.lamp!.unplaced).toBe(true);
    expect(none.lamp!.price).toBe(4000);
  });

  it("подвесной комод — лампа на поднятом верхе (как поднимет `build-scene`: `hungLiftCm`)", () => {
    const hung = { ...DRESSER, h: 50, sku: { ...DRESSER.sku, name: "Комод подвесной Лайн" } };
    const { lamp } = scene([SOFA, TABLE, hung], [LAMP]);
    expect(lamp!.placement.elevCm).toBeGreaterThan(50);
    const at = onCarrier({ x: 0, y: 0, rot: 0, wCm: 120, dCm: 45, hCm: 50, elevCm: 0, role: "комод", name: "Комод подвесной" },
      25, 25, 0, 0, fit)!;
    expect(lamp!.placement.elevCm).toBe(at.elevCm);
  });

  it("ваза — своим рядом на столике; лампа ряд ваз не снимает и сама в него не идёт", () => {
    const { sc, lamp } = scene([SOFA, TABLE, DRESSER], [VASE, LAMP]);
    const vase = sc.items.find((i) => i.photoRole === "ваза")!;
    expect(vase.unplaced).toBeUndefined();
    expect(vase.placement.elevCm).toBe(45);
    expect(lamp!.placement.elevCm).toBe(80);
    // крупная лампа не влезает на комод — ваза всё равно на столике
    const big = { ...LAMP, sku: { ...LAMP.sku, w: 60, d: 60 } };
    const s2 = scene([SOFA, TABLE, DRESSER], [VASE, big]);
    expect(s2.sc.items.find((i) => i.photoRole === "ваза")!.unplaced).toBeUndefined();
    expect(s2.lamp!.unplaced).toBe(true);
  });

  it("ценник и клик: место сцены лампы → номер строки декора страницы", () => {
    const idx = sceneSlotIndex([SOFA, TABLE, DRESSER] as never, [VASE, LAMP] as never, false);
    expect(idx.get("carrier:лампа#0")).toBe(3 + 1);
  });
});
