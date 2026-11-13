import { describe, expect, it } from "vitest";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { sceneSlotIndex } from "@/lib/viewer3d/demo-scene";

// КАРТИНА-ТОВАР ВЫБИРАЕТСЯ В 3D, КАК МЕБЕЛЬ (T-20261112-45, владелец TG 1062): место движка картины ↔ номер страницы
// `items.length` + номер в декоре; id мест — те же, что строит мост (`fromDemo.ts:wallPlanes`), иначе клик, ценник и рамка разойдутся

const CTX = { apartmentId: "t", partnerId: "demo", currency: "RUB" as const, basePrice: 0, assetBase: "/demo/demo-data.json" };
const BED = { role: "кровать", x: 200, y: 106, rot: 0, w: 180, d: 210, h: 110, sku: { name: "Кровать", price: 40000, msid: "b_1" } };
const SOFA = { role: "диван", x: 200, y: 305, rot: 180, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, msid: "s_1" } };
const RUG = { role: "ковёр", strategy: "procedural_plane", x: 200, y: 200, rot: 0, w: 200, d: 140, h: 1, sku: { name: "Ковёр", price: 9000, msid: "r_1" } };
const MIRROR = { role: "зеркало", strategy: "procedural_plane", x: 10, y: 50, rot: 90, w: 60, d: 3, h: 150, sku: { name: "Зеркало", price: 7000 } };
const art = (k: number) => ({ role: k ? `картина ${k + 1}` : "картина", strategy: "procedural_plane",
  sku: { name: `Картина ${k + 1}`, price: 3990 + k, sid: `p${k}`, img: `img/p${k}.jpg`, w: 60, h: 80 } });
const VASE = { role: "ваза", sku: { name: "Ваза", price: 1500, msid: "v_1", w: 15, d: 15, h: 30 } };

const bridgeIds = (items: object[], decor: object[]): Set<string> => {
  const data = { room: { w: 400, d: 350, title: "Комната", height_cm: 270, openings: [] }, variants: [{ id: "v", style: "сканди", items, decor }] };
  return new Set(fromDemoVariant(data, "v", CTX)!.apartment.slots.map((s) => s.id));
};

describe("номера мест сцены: мебель и картины декора", () => {
  it("картина и ваза — items.length + номер в декоре; ковёр и зеркало не выбираются", () => {
    const items = [BED, RUG, SOFA, MIRROR];
    const decor = [VASE, art(0), art(1)];
    const m = sceneSlotIndex(items, decor, true);
    // ваза на столике (T-20261112-111, владелец TG 1276): свой ценник, тап и карточка — место моста `decor:ваза#0`
    expect([...m]).toEqual([["кровать#0", 0], ["диван#0", 2], ["decor:ваза#0", 4], ["картина#0", 5], ["картина 2#0", 6]]);
    // те же id, что у моста — иначе `pick`/`pins`/`select` не найдут место
    const ids = bridgeIds(items, decor);
    for (const id of m.keys()) expect(ids.has(id)).toBe(true);
  });

  it("без картин в сцене (?art=0) — только мебель, как прежде", () => {
    expect([...sceneSlotIndex([BED, SOFA], [art(0)], false)]).toEqual([["кровать#0", 0], ["диван#0", 1]]);
  });

  it("ваза без модели или «только в списке» — не место сцены (в 3D её нет)", () => {
    const noMesh = { ...VASE, sku: { ...VASE.sku, msid: "" } }, listOnly = { ...VASE, list_only: true };
    expect([...sceneSlotIndex([BED], [noMesh, listOnly], false)]).toEqual([["кровать#0", 0]]);
  });

  it("картина без размеров товара и «только в списке» — не место сцены", () => {
    const noSize = { ...art(0), sku: { ...art(0).sku, w: 0 } };
    const listOnly = { ...art(1), list_only: true };
    expect([...sceneSlotIndex([BED], [noSize, listOnly], true)]).toEqual([["кровать#0", 0]]);
  });
});
