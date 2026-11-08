import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// СТВОРКА ДВЕРИ В МЕРЕ ВИДОВ (T-20261108-73/7, ведущий): полотно, открытое в комнату (`rooms_geo.openings_ir`, группа `leaf` повёрнута —
// `lib/viewer3d/opening-ir.ts:doorIR`), — крупный предмет меры v2 (`camLeafIts` → `camPairV2`): ЦЕЛИКОМ / ВНЕ / СРЕЗАН во всех окнах,
// та же лестница. Закрытое лежит в плоскости стены — не предмет (демо 08.11: все двери закрыты). Оси — `opening_ir.py:world_boxes`.
type It = { role: string; x: number; y: number; rot: number; w: number; d: number; h: number | null; leaf?: boolean; elev?: number };
type Cam = { name?: string; x: number; y: number; rot: number; fov: number; view?: number };
type St = { s: number; fr: number; q: number };
type Ir = { wall: string; ir: { kind: string; boxes: { role: string; group?: string; x: number; y: number; z: number; w: number; h: number; d: number }[]; groups: Record<string, { x: number; y: number; z: number; rotYDeg: number }> } };
type Room = { w: number; d: number; kind?: string; openings: unknown[]; openings_ir: Ir[] };
type Fx = { room: Room; variants: { style: string; items: It[] }[] };
type Api = {
  camLeafIts: (W: number, H: number) => It[];
  camV2Raw: (c: Cam, its: It[], W: number, H: number, ids: number[]) => St[][];
  camV2Set: (its: It[], I: unknown) => { ids: number[] };
  camZ: () => { intent?: unknown };
  camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[]) => { cams: Cam[]; warns: string[]; relax: number; how: string };
  CAM_V2: { big: number };
  JPH: number;
};
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const apiOf = (room: Room) =>
  new Function("D", `${block};return {camLeafIts,camV2Raw,camV2Set,camZ,camPairAll,CAM_V2,JPH};`)({ room }) as Api;
const fx = JSON.parse(readFileSync("tests/fixtures/demo-bedroom-2-one-1107.json", "utf8")) as Fx;
const its = (v: { items: It[] }) => v.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
// комната спальни 2 со створкой, открытой на `deg` (как `doorIR`: в комнату −99°), дверь на стене `wall`
const roomWith = (deg: number, wall = "south") => {
  const r = structuredClone(fx.room), e = r.openings_ir.find((x) => x.ir.kind === "door")!;
  e.ir.groups.leaf!.rotYDeg = deg; e.wall = wall; return r;
};
const W = fx.room.w, H = fx.room.d;
const corners = [{ x: 3, y: 3 }, { x: W - 3, y: 3 }, { x: W - 3, y: H - 3 }, { x: 3, y: H - 3 }];

describe("створка двери в мере видов", () => {
  it("закрытая (поворот 0, как в демо) — не предмет; открытая в комнату — полотно 80×4×202,5 у петли, внутрь комнаты", () => {
    expect(apiOf(fx.room).camLeafIts(W, H)).toEqual([]);
    const [lf] = apiOf(roomWith(-99)).camLeafIts(W, H);
    // петля у начала проёма (130 + 2,5), полотно 80 см под 99° от стены: середина (132,5 − 40·0,156; 1 + 40·0,988)
    expect(lf).toMatchObject({ role: "створка двери", leaf: true, w: 80, d: 4, h: 202.5, elev: 0 });
    expect(lf!.x).toBeCloseTo(126.2, 0);
    expect(lf!.y).toBeCloseTo(40.5, 0);
    expect(Math.abs(lf!.rot)).toBeCloseTo(99, 0);
  });
  it("на любой стене открытая створка — в комнате, середина в ~40 см от стены", () => {
    for (const wall of ["south", "north", "west", "east"]) {
      const [lf] = apiOf(roomWith(-99, wall)).camLeafIts(W, H);
      const dist = Math.min(lf!.y, H - lf!.y, lf!.x, W - lf!.x);
      expect(lf!.x, wall).toBeGreaterThan(0); expect(lf!.x, wall).toBeLessThan(W);
      expect(lf!.y, wall).toBeGreaterThan(0); expect(lf!.y, wall).toBeLessThan(H);
      expect(dist, wall).toBeGreaterThan(35); expect(dist, wall).toBeLessThan(45);
    }
  });
  it("мера видит створку: из прежней точки вида 1 (40,70 → 115°) она СРЕЗАНА крупно во всех окнах", () => {
    const api = apiOf(roomWith(-99)), list = its(fx.variants[0]!).concat(api.camLeafIts(W, H)), S = api.camV2Set(list, api.camZ().intent);
    const k = S.ids.indexOf(list.length - 1);
    expect(k, "створка в наборе меры").toBeGreaterThanOrEqual(0);
    const r = api.camV2Raw({ x: 40, y: 70, rot: 115, fov: 90, view: 0 }, list, W, H, S.ids)[k]!;
    r.forEach((x, j) => { expect(x.s, `окно ${j}`).toBe(2); expect(x.fr, `окно ${j}`).toBeGreaterThanOrEqual(api.CAM_V2.big); });
  });
  it("подбор пары с открытой створкой: крупно её не режет ни один вид, иначе — WARN с её именем", () => {
    const api = apiOf(roomWith(-99)), LV = api.camLeafIts(W, H);
    for (const v of fx.variants) {
      const list = its(v), p = api.camPairAll([list], W, H, corners), all = list.concat(LV), S = api.camV2Set(all, api.camZ().intent);
      const k = S.ids.indexOf(all.length - 1), ws = p.warns.join(" ");
      for (const c of p.cams) {
        const cut = api.camV2Raw(c, all, W, H, S.ids)[k]!.some((x, j) => j !== api.JPH && x.s === 2 && x.fr >= api.CAM_V2.big);
        if (cut) expect(ws, `${v.style} ${c.name}: створка срезана крупно — WARN (${p.how})`).toMatch(/major_cut object=створка двери/);
      }
    }
  }, 600_000);
});
