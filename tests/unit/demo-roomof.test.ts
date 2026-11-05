import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ОСНОВА НЕСКОЛЬКИХ КОМНАТ (onb-07, ADR-0330 п.3): вариант витрины → геометрия его комнаты. Функции страницы берём прямо из неё
// (блок ROOMOF), камеры — из блока CAMFIT: вне страницы он читает `D.room` той комнаты, что ему дали (`demo-cams.mjs`).
type Geo = { w: number; d: number; title?: string; openings?: { kind: string; wall: string; offset_cm: number; width_cm: number }[] };
type V = { id?: string; room_id?: string; room?: string; style?: string };
type Data = { room: Geo; rooms_geo?: Record<string, Geo>; variants: V[] };
type Api = {
  roomIdOf: (v: V | undefined) => string;
  roomGeoOf: (v: V | undefined) => Geo | null;
  roomOf: (v: V | undefined) => Geo | null;
  curRoom: () => Geo | null;
  roomStateKey: (v: V | undefined, stateId: string) => string;
  roomsAlias: (d: Data | null) => Data | null;
};
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const cut = (n: string) => {
  const a = html.indexOf(`// ${n} START`), b = html.indexOf(`// ${n} END`);
  if (a < 0 || b < a) throw new Error(`в странице нет блока ${n}`);
  return html.slice(a, b);
};
const block = cut("ROOMOF");
// страница: `D`, открытый вариант `cur`, `allVariants()` (каталог + коллекции), MAXV — как в `index.html`
const page = (D: Data | null, cur = 0, mine: V[] = []) =>
  new Function("D", "cur", "MAXV", "allVariants", `${block};return {roomIdOf,roomGeoOf,roomOf,curRoom,roomStateKey,roomsAlias};`)(
    D, cur, 6, () => (D?.variants ?? []).slice(0, 6).concat(mine)) as Api;

const LIV: Geo = { w: 439, d: 325, title: "Гостиная", openings: [{ kind: "door", wall: "south", offset_cm: 10, width_cm: 80 }] };
const BED: Geo = { w: 618, d: 293, title: "Спальня 1", openings: [{ kind: "door", wall: "west", offset_cm: 20, width_cm: 80 }] };

describe("roomOf — комната варианта", () => {
  it("вариант спальни со своей геометрией — своя геометрия; гостиная — D.room", () => {
    const D: Data = { room: LIV, rooms_geo: { living: LIV, "bedroom-1": BED },
      variants: [{ id: "set1", room_id: "living" }, { id: "b1", room_id: "bedroom-1" }] };
    const p = page(D);
    expect(p.roomOf(D.variants[1])).toBe(BED);
    expect(p.roomOf(D.variants[0])).toBe(LIV);
    expect(p.roomIdOf(D.variants[1])).toBe("bedroom-1");
  });
  it("без rooms_geo (данные до onb-07) — D.room, и у варианта без комнаты тоже", () => {
    const D: Data = { room: LIV, variants: [{ id: "set1", room_id: "living" }, { id: "x" }, { id: "b1", room_id: "bedroom-1" }] };
    const p = page(D);
    expect(p.roomOf(D.variants[0])).toBe(LIV);
    expect(p.roomOf(D.variants[1])).toBe(LIV);
    expect(p.roomIdOf(D.variants[1])).toBe("living");
    expect(p.roomGeoOf(D.variants[2])).toBe(LIV);   // старые данные: комнат не различали — открываем как раньше
  });
  it("комнаты варианта нет в rooms_geo — roomGeoOf пусто (главная его не покажет), roomOf не падает", () => {
    const D: Data = { room: LIV, rooms_geo: { living: LIV }, variants: [{ id: "k1", room_id: "kitchen" }] };
    const p = page(D);
    expect(p.roomGeoOf(D.variants[0])).toBeNull();
    expect(p.roomOf(D.variants[0])).toBe(LIV);
  });
  it("коллекция несёт комнату строкой `room` (index.html:asVariant) — её геометрия", () => {
    const D: Data = { room: LIV, rooms_geo: { living: LIV, "bedroom-1": BED }, variants: [{ id: "set1", room_id: "living" }] };
    const coll: V = { id: "c:AAAAAAAAAAAAAAAAAAAAAA", room: "bedroom-1" };
    const p = page(D, 1, [coll]);
    expect(p.roomOf(coll)).toBe(BED);
    expect(p.curRoom()).toBe(BED);
  });
  it("curRoom — комната открытого варианта; данных нет — null", () => {
    const D: Data = { room: LIV, rooms_geo: { living: LIV, "bedroom-1": BED },
      variants: [{ id: "set1", room_id: "living" }, { id: "b1", room_id: "bedroom-1" }] };
    expect(page(D, 0).curRoom()).toBe(LIV);
    expect(page(D, 1).curRoom()).toBe(BED);
    expect(page(null).curRoom()).toBeNull();
  });
  it("ключ состояния — комната + вариант + номер: одинаковый номер в двух комнатах различается", () => {
    const p = page({ room: LIV, variants: [] });
    const a = p.roomStateKey({ id: "set1", room_id: "living" }, "s2-x"), b = p.roomStateKey({ id: "b1", room_id: "bedroom-1" }, "s2-x");
    expect(a).toBe("living|set1|s2-x");
    expect(a).not.toBe(b);
  });
});

describe("catalogVariants — до шести вариантов на комнату", () => {
  it("семь гостиных и спальня: седьмая гостиная отрезана, спальня остаётся; без комнат — как прежний slice(0,6)", () => {
    const liv = Array.from({ length: 7 }, (_, i) => ({ id: `set${i}`, room_id: "living" }));
    const D: Data = { room: LIV, rooms_geo: { living: LIV, "bedroom-1": BED }, variants: [...liv, { id: "b1", room_id: "bedroom-1" }] };
    const cap = (d: Data) => new Function("D", "cur", "MAXV", `${block};return catalogVariants();`)(d, 0, 6) as V[];
    expect(cap(D).map((v) => v.id)).toEqual(["set0", "set1", "set2", "set3", "set4", "set5", "b1"]);
    const old: Data = { room: LIV, variants: Array.from({ length: 8 }, (_, i) => ({ id: `v${i}` })) };
    expect(cap(old)).toEqual(old.variants.slice(0, 6));
  });
});

describe("roomsAlias — гостиная на странице одним объектом", () => {
  it("rooms_geo.living из файла (копия) становится тем же объектом, что D.room; спальня не трогается", () => {
    const d: Data = JSON.parse(JSON.stringify({ room: LIV, rooms_geo: { living: LIV, "bedroom-1": BED }, variants: [] }));
    const p = page(null);
    expect(d.rooms_geo!.living).not.toBe(d.room);
    p.roomsAlias(d);
    expect(d.rooms_geo!.living).toBe(d.room);
    expect(d.rooms_geo!["bedroom-1"]).toEqual(BED);
    expect(p.roomsAlias(null)).toBeNull();
  });
});

describe("CAMFIT вне страницы — комната из D.room того, кто исполняет блок", () => {
  // `demo-cams.mjs` и тесты кадра дают блоку `D = {room}` нужной комнаты: правило «не у двери» видит её проёмы
  const cam = (room: Geo) =>
    new Function("D", `${cut("CAMFIT")};return {camRoom, wallSeg};`)({ room }) as { camRoom: () => Geo; wallSeg: (w: string, o: number, l: number) => { x1: number; y1: number; x2: number; y2: number } };
  it("camRoom — D.room; стена — по её размерам", () => {
    expect(cam(BED).camRoom()).toBe(BED);
    expect(cam(BED).wallSeg("east", 10, 50)).toEqual({ x1: 618, y1: 10, x2: 618, y2: 60 });
    expect(cam(LIV).wallSeg("north", 0, 100)).toEqual({ x1: 0, y1: 325, x2: 100, y2: 325 });
  });
});
