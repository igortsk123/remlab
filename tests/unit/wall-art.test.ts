import { describe, expect, it } from "vitest";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { placeWallArt, WALL_ART_RULES } from "@/lib/configurator/wall-art";
import { wallArtWhere } from "@/lib/viewer3d/demo-scene";
import type { Configuration } from "@/contracts/configurator";

// КАРТИНЫ НАД МЕБЕЛЬЮ (viz-decor-01 шаг 3, T-20261112-26): место — от ТЕКУЩЕЙ опоры после перестановок; нет места — `unplaced`,
// а товар остаётся в составе и в сумме (строка списка = предмет сцены = цена)

const CTX = { apartmentId: "t", partnerId: "demo", currency: "RUB" as const, basePrice: 0, assetBase: "/demo/demo-data.json" };
type Opening = { kind: string; wall: string; offset_cm: number; width_cm: number; swing_cm?: number; sill_cm?: number };

const BED = { role: "кровать", x: 200, y: 106, rot: 0, w: 180, d: 210, h: 110, sku: { name: "Кровать", price: 40000, msid: "b_1" } };
const SOFA = { role: "диван", x: 200, y: 305, rot: 180, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, msid: "s_1" } };
const CHEST = { role: "комод", x: 23.5, y: 175, rot: 90, w: 100, d: 45, h: 85, sku: { name: "Комод", price: 15000, msid: "c_1" } };
const art = (k: number, w = 60, h = 80) => ({ role: k ? `картина ${k + 1}` : "картина", strategy: "procedural_plane",
  sku: { name: `Картина ${k + 1}`, price: 3990 + k, sid: `p${k}`, img: `img/p${k}.jpg`, img_art: `img/p${k}-art.jpg`, w, h } });

function scene(items: object[], decor: object[], o: { openings?: Opening[]; height?: number; config?: Partial<Configuration> } = {}) {
  const data = { room: { w: 400, d: 350, title: "Комната", height_cm: o.height ?? 270, openings: o.openings ?? [] },
    variants: [{ id: "v", style: "сканди", items, decor }] };
  const r = fromDemoVariant(data, "v", CTX)!;
  const sc = resolveScene(r.apartment, r.catalogue, { ...defaultConfiguration(r.apartment, r.catalogue), ...o.config });
  const pics = sc.items.filter((i) => r.apartment.slots.find((s) => s.id === i.slotId)?.wallArt);
  return { r, sc, pics };
}

describe("картина над мебелью", () => {
  it("над изголовьем кровати: по центру, низ на 22 см выше спинки, лицом в комнату; фото без белого поля", () => {
    const { r, pics } = scene([BED, SOFA], [art(0)]);
    expect(pics).toHaveLength(1);
    expect(pics[0]!.unplaced).toBeUndefined();
    expect(pics[0]!.placement).toMatchObject({ x: 200, y: 2.25, rot: 0, elevCm: 132, wCm: 60, hCm: 80, dCm: 2.5 });
    expect(r.catalogue.materials.find((m) => m.id.startsWith("plane:"))!.baseColorUrl).toBe("/demo/img/p0-art.jpg");
  });

  it("нет кровати — над диваном, нет и дивана — над комодом", () => {
    expect(scene([SOFA, CHEST], [art(0)]).pics[0]!.placement).toMatchObject({ x: 200, y: 347.75, rot: 180, elevCm: 102 });
    expect(scene([CHEST], [art(0)]).pics[0]!.placement).toMatchObject({ x: 2.25, y: 175, rot: 90, elevCm: 110 });
  });

  it("окно или дверь на стене за кроватью — картина уходит к дивану; створка двери соседней стены — тоже мешает", () => {
    const win = [{ kind: "window", wall: "south", offset_cm: 150, width_cm: 120, sill_cm: 90 }];
    expect(scene([BED, SOFA], [art(0)], { openings: win }).pics[0]!.placement.rot).toBe(180);
    const door = [{ kind: "door", wall: "south", offset_cm: 120, width_cm: 90 }];
    expect(scene([BED, SOFA], [art(0)], { openings: door }).pics[0]!.placement.rot).toBe(180);
    const bed = { ...BED, x: 110 };
    // окно на той же стене в 40 см от края картины: проём не задет, но штора (43 см за край) закрыла бы её — к дивану (T-26/2)
    const nearWin = [{ kind: "window", wall: "south", offset_cm: 180, width_cm: 100, sill_cm: 90 }];
    expect(scene([bed, SOFA], [art(0)], { openings: nearWin }).pics[0]!.placement.rot).toBe(180);
    const nearDoor = [{ kind: "door", wall: "south", offset_cm: 180, width_cm: 90 }];
    expect(scene([bed, SOFA], [art(0)], { openings: nearDoor }).pics[0]!.placement.rot).toBe(0);   // у двери шторы нет
    const swing = [{ kind: "door", wall: "west", offset_cm: 0, width_cm: 90, swing_cm: 90 }];
    expect(scene([bed], [art(0)], { openings: swing }).pics[0]!.unplaced).toBe(true);
    expect(scene([bed], [art(0)], { openings: [{ ...swing[0]!, swing_cm: 0 }] }).pics[0]!.unplaced).toBeUndefined();
  });

  it("кровать передвинули и повернули к западной стене — картина за ней; убрали кровать — над диваном", () => {
    const moved = scene([BED, SOFA], [art(0)], { config: { placements: { "кровать#0": { x: 106, y: 175, rot: 90 } } } });
    expect(moved.pics[0]!.placement).toMatchObject({ x: 2.25, y: 175, rot: 90, elevCm: 132 });
    const away = scene([BED, SOFA], [art(0)], { config: { placements: { "кровать#0": { x: 200, y: 175, rot: 0 } } } });
    expect(away.pics[0]!.placement.rot).toBe(180);   // кровать посреди комнаты — не опора
    const hidden = scene([BED, SOFA], [art(0)], { config: { hidden: ["кровать#0"] } });
    expect(hidden.pics[0]!.placement).toMatchObject({ rot: 180, elevCm: 102 });
  });

  it("места нет (низкий потолок) — картина не висит, но в составе и в сумме", () => {
    const { sc, pics } = scene([BED], [art(0)], { height: 200 });
    expect(pics[0]!.unplaced).toBe(true);
    expect(pics[0]!.price).toBe(3990);
    expect(sc.totals.upgrades).toBe(40000 + 3990);
  });

  it("пара — рядом с зазором 10 см, центры на одной линии; пара шире опоры — висит одна первая", () => {
    const pair = scene([BED], [art(0, 50, 70), art(1, 50, 60)]).pics;
    expect(pair.map((p) => p.placement.x)).toEqual([170, 230]);
    expect(pair.map((p) => p.placement.elevCm)).toEqual([132, 137]);
    const wide = scene([BED], [art(0, 80), art(1, 80)]).pics;
    expect(wide.map((p) => !!p.unplaced)).toEqual([false, true]);
  });

  it("строка списка = предмет сцены = цена: опция картины с ценой товара и ссылкой магазина", () => {
    const { r, sc, pics } = scene([BED], [art(0)]);
    const opt = r.catalogue.options.find((o) => o.id === pics[0]!.optionId)!;
    expect(opt.price).toBe(3990);
    expect(opt.asset).toMatchObject({ kind: "kit", kit: "wall-plane" });
    expect(sc.totals.upgrades).toBe(40000 + 3990);
  });

  it("подпись страницы — из того же расчёта, что 3D: опора по роли картины, места нет — null (T-20261112-26/2)", () => {
    const room = { w: 400, d: 350, title: "Комната", height_cm: 270, openings: [] };
    const where = (items: object[], decor: object[], h = 270) =>
      wallArtWhere({ room: { ...room, height_cm: h } as never, items: items as never, decor: decor as never, base: "/demo/" });
    expect(where([BED, SOFA], [art(0, 50, 70), art(1, 50, 60)])).toEqual({ "картина": "кровать", "картина 2": "кровать" });
    const win = { ...room, openings: [{ kind: "window", wall: "south", offset_cm: 150, width_cm: 120, sill_cm: 90 }] };
    expect(wallArtWhere({ room: win as never, items: [BED, SOFA] as never, decor: [art(0)] as never, base: "/demo/" }))
      .toEqual({ "картина": "диван" });             // окно за кроватью — не «над кроватью», а где на самом деле
    expect(where([BED], [art(0)], 200)).toEqual({ "картина": null });
    expect(where([BED], [art(0, 80), art(1, 80)])).toEqual({ "картина": "кровать", "картина 2": null });
  });

  it("правила выключены — картины не висят нигде", () => {
    const { r, sc } = scene([BED], [art(0)]);
    placeWallArt(r.apartment, sc.items, { ...WALL_ART_RULES, enabled: false });
    expect(sc.items.find((i) => i.titleRu === "Картина 1")!.unplaced).toBe(true);
  });
});
