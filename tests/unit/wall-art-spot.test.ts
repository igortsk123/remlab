import { describe, expect, it } from "vitest";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { WALL_ART_RULES } from "@/lib/configurator/wall-art";
import { ART_CENTRE_CM, clampSpot, hangAt, HUNG_FREE, spanProblem, spotOf } from "@/lib/configurator/wall-art-spot";

// КАРТИНУ ДВИГАЮТ ВДОЛЬ СТЕНЫ И ПЕРЕВЕШИВАЮТ НА ЛЮБУЮ СТЕНУ (T-20261112-97, владелец TG 865). Одно правило места — для авторасчёта
// над опорой и для переноса покупателем: окно/дверь/проём, створка, мебель у стены по высоте, другая картина, ТВ, край, потолок.

const CTX = { apartmentId: "t", partnerId: "demo", currency: "RUB" as const, basePrice: 0, assetBase: "/demo/demo-data.json" };
const BED = { role: "кровать", x: 200, y: 106, rot: 0, w: 180, d: 210, h: 110, sku: { name: "Кровать", price: 40000, msid: "b_1" } };
const SOFA = { role: "диван", x: 200, y: 305, rot: 180, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, msid: "s_1" } };
const CHEST = { role: "комод", x: 23.5, y: 175, rot: 90, w: 100, d: 45, h: 85, sku: { name: "Комод", price: 15000, msid: "c_1" } };
const STAND = { role: "тв-тумба", x: 376.5, y: 175, rot: 270, w: 160, d: 45, h: 50, sku: { name: "Тумба", price: 9000, msid: "t_1" } };
type Pin = { wall: string; along: number; elev: number };
const art = (k: number, at?: Pin, w = 60, h = 80) => ({ role: k ? `картина ${k + 1}` : "картина", strategy: "procedural_plane",
  sku: { name: `Картина ${k + 1}`, price: 3990 + k, sid: `p${k}`, img: `img/p${k}.jpg`, w, h, ...(at ? { wall_at: at } : {}) } });

function scene(items: object[], decor: object[], openings: object[] = []) {
  const data = { room: { w: 400, d: 350, title: "Комната", height_cm: 270, openings }, variants: [{ id: "v", style: "сканди", items, decor }] };
  const r = fromDemoVariant(data, "v", CTX)!;
  const sc = resolveScene(r.apartment, r.catalogue, defaultConfiguration(r.apartment, r.catalogue));
  const pics = sc.items.filter((i) => r.apartment.slots.find((s) => s.id === i.slotId)?.wallArt);
  return { r, sc, pics };
}
const WEST = { wall: "west", along: 175, elev: 120 };

describe("картина, перевешенная покупателем", () => {
  it("место из `wall_at` доходит до слота и сцены: западная стена, лицом в комнату, подпись «на стене»", () => {
    const { r, pics } = scene([BED, SOFA], [art(0, WEST)]);
    expect(r.apartment.slots.find((s) => s.wallArt)!.wallPin).toEqual(WEST);
    expect(pics[0]!.placement).toMatchObject({ x: 2.25, y: 175, rot: 90, elevCm: 120 });
    expect(pics[0]!.hungOver).toBe(HUNG_FREE);
  });

  it("кривое `wall_at` (нет стены, не число) — не место, картина над опорой", () => {
    const bad = { ...art(0), sku: { ...art(0).sku, wall_at: { wall: "up", along: 1, elev: 1 } } };
    expect(scene([BED], [bad]).r.apartment.slots.find((s) => s.wallArt)!.wallPin).toBeUndefined();
    expect(scene([BED], [bad]).pics[0]!.placement).toMatchObject({ rot: 0, elevCm: 132 });
  });

  it("место перестало проходить (окно, створка, комод ниже картины) — картина снова над опорой; над комодом — висит", () => {
    const win = [{ kind: "window", wall: "west", offset_cm: 130, width_cm: 90, sill_cm: 90 }];
    expect(scene([BED], [art(0, WEST)], win).pics[0]!.placement).toMatchObject({ rot: 0, elevCm: 132 });
    const door = [{ kind: "door", wall: "south", offset_cm: 0, width_cm: 90, swing_cm: 90 }];
    expect(scene([BED], [art(0, { wall: "west", along: 40, elev: 120 })], door).pics[0]!.placement.rot).toBe(0);
    expect(scene([BED, CHEST], [art(0, { ...WEST, elev: 60 })]).pics[0]!.hungOver).toBe("кровать");
    expect(scene([BED, CHEST], [art(0, { ...WEST, elev: 100 })]).pics[0]!.hungOver).toBe(HUNG_FREE);
  });

  it("одна перевешена, вторая — над опорой; две на одно место — вторая не налезает на первую", () => {
    const two = scene([BED], [art(0, WEST), art(1)]).pics;
    expect(two.map((p) => p.hungOver)).toEqual([HUNG_FREE, "кровать"]);
    const same = scene([BED], [art(0, WEST), art(1, { ...WEST, along: 200 })]).pics;
    expect(same.map((p) => p.hungOver)).toEqual([HUNG_FREE, "кровать"]);
  });

  it("телевизор над тумбой (`autoTv`) занимает стену: картину на него не повесить", () => {
    const { pics, sc } = scene([BED, SOFA, STAND], [art(0, { wall: "east", along: 175, elev: 90 })]);
    expect(sc.items.some((i) => i.photoRole === "тв")).toBe(false);
    expect(pics[0]!.hungOver).toBe("кровать");
    expect(scene([BED, SOFA, STAND], [art(0, { wall: "east", along: 60, elev: 120 })]).pics[0]!.hungOver).toBe(HUNG_FREE);
  });
});

describe("правило места на стене", () => {
  const { r } = scene([], []);
  const room = r.apartment.rooms[0]!;
  const P = { wCm: 60, dCm: 2.5, hCm: 80 };
  it("коды отказа: край, потолок, пол, проём, свободно", () => {
    const at = (a0: number, b: number, top = b + 80) => spanProblem(room, "west", a0, a0 + 60, b, top, 4, [], WALL_ART_RULES);
    expect(at(5, 120)).toBe("edge");
    expect(at(100, 200)).toBe("ceiling");
    expect(at(100, -1)).toBe("floor");
    expect(at(100, 120)).toBeNull();
    expect(hangAt(room, P, { wall: "north", along: 200, elev: 120 }, [], WALL_ART_RULES)).toMatchObject({ x: 200, y: 347.75, rot: 180 });
  });
  it("перенос держит картину на стене и не ниже нормы центра; потолок — с зазором", () => {
    const min = ART_CENTRE_CM[0] - P.hCm / 2;
    expect(clampSpot(room, P, { wall: "south", along: -50, elev: 0 }, min, WALL_ART_RULES)).toEqual({ wall: "south", along: 30, elev: min });
    expect(clampSpot(room, P, { wall: "east", along: 999, elev: 999 }, min, WALL_ART_RULES)).toEqual({ wall: "east", along: 320, elev: 170 });
  });
  it("место висящей картины читается обратно; косая — null", () => {
    expect(spotOf(room, { x: 2.25, y: 175, rot: 90, wCm: 60, dCm: 2.5, hCm: 80, elevCm: 120 })).toEqual({ wall: "west", along: 175, elev: 120 });
    expect(spotOf(room, { x: 50, y: 50, rot: 45, wCm: 60, dCm: 2.5, hCm: 80, elevCm: 120 })).toBeNull();
  });
});
