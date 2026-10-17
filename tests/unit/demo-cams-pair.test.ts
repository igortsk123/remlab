import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ДВЕ ТОЧКИ СЪЁМКИ ПОДБИРАЮТСЯ ПАРОЙ (план demo-12). Функции — прямо из блока CAMFIT страницы демо (его же исполняет
// `tools/flat3d/demo-cams.mjs`), расстановки — слепок пяти вариантов 17.10. Подбор парой включён флагом окружения
// (`CAMS_PAIR=1`), как у сборки демо до приёмки владельцем.
type It = { role: string; x: number; y: number; rot: number; w: number; d: number; h: number | null };
type Cam = { name: string; x: number; y: number; rot: number; fov: number; pshift?: number };
type Stats = { ceil: number; floor: number; empty: number; nearWall: number; fore: number; midY: number; win: boolean; bins: Set<number> };
const fx = JSON.parse(readFileSync("tests/fixtures/demo-layouts-1710.json", "utf8")) as {
  room: { w: number; d: number; openings: unknown[] }; variants: { id: string; style: string; items: It[] }[];
};
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
process.env.CAMS_PAIR = "1";
const api = new Function("D", `${block};return {camPair,camPairCorner,camStats,camSeen,camMask,camAtWindow,camNear,CAM_B_CLEAR};`)({ room: fx.room }) as {
  camPair: (its: It[], W: number, H: number, cs: { x: number; y: number }[]) => { level: number; cams: Cam[]; how: string };
  camPairCorner: (its: It[], W: number, H: number, cs: { x: number; y: number }[]) => { level: number; cams: Cam[] };
  camStats: (c: Cam, its: It[], W: number, H: number, o?: { w?: number; h?: number; sn?: number }) => Stats;
  camMask: (c: Cam, its: It[], W: number, H: number, o?: { w?: number; h?: number }) => { cls: Uint8Array };
  camSeen: (c: Cam, its: It[], st: Stats, part?: boolean) => Set<number>;
  camAtWindow: (x: number, y: number, W: number, H: number) => boolean;
  camNear: (c: Cam, it: It) => number;
  CAM_B_CLEAR: number;
};
const { w: W, d: H } = fx.room;
const cs = [{ x: 3, y: 3 }, { x: W - 3, y: 3 }, { x: W - 3, y: H - 3 }, { x: 3, y: H - 3 }];
const its = (v: { items: It[] }) => v.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));

describe("камеры демо: пара", () => {
  it("маска: в пустой комнате пол и потолок симметричны при сдвиге 0, у стены в упор — стена у края", () => {
    const c = { name: "t", x: W / 2, y: H / 2, rot: 0, fov: 72 };
    const s0 = api.camStats(c, [], W, H, { w: 64, h: 88, sn: 0 });
    expect(Math.abs(s0.floor - s0.ceil)).toBeLessThan(0.02);
    expect(api.camStats({ name: "t", x: 10, y: 10, rot: 20, fov: 72 }, [], W, H).nearWall).toBeGreaterThan(0.02);
  });
  for (const v of fx.variants)
    it(`${v.style}: оба кадра без стены у края и без крупного плана, второй дополняет первый, стоят по правилам`, () => {
      const list = its(v), pr = api.camPair(list, W, H, cs);
      expect(pr.how, pr.how).toMatch(/^пара/);
      const st = pr.cams.map((c) => api.camStats(c, list, W, H));
      for (const [i, s] of st.entries()) {
        expect(s.nearWall, `${v.style} C${i + 1} стена у края`).toBeLessThanOrEqual(0.02);
        expect(s.fore, `${v.style} C${i + 1} крупный план`).toBeLessThanOrEqual(0.12);
        expect(s.ceil, `${v.style} C${i + 1} потолок`).toBeLessThanOrEqual(0.3);
      }
      const seen = new Set(pr.cams.flatMap((c, k) => [...api.camSeen(c, list, st[k]!)]));
      const wt = (i: number) => (list[i]!.role === "ковёр" ? 0 : 1);
      expect([...seen].reduce((a, i) => a + wt(i), 0), `${v.style}: предметов целиком вдвоём`).toBeGreaterThanOrEqual(0.7 * list.filter((it) => it.role !== "ковёр").length);
      for (const c of pr.cams) {
        expect(api.camAtWindow(c.x, c.y, W, H), `${v.style} ${c.name} у окна`).toBe(false);
        for (const it of list) if ((it.h ?? 10) > 2 && it.role !== "ковёр") expect(api.camNear(c, it)).toBeGreaterThanOrEqual(api.CAM_B_CLEAR);
      }
      // второй вид — с другой стороны: направления расходятся хотя бы на 60°
      const d = Math.abs(((pr.cams[0]!.rot - pr.cams[1]!.rot) % 360 + 540) % 360 - 180);
      expect(d).toBeGreaterThanOrEqual(60);
      // мебель вдвоём — почти вся (≥ 0.95 веса), стен — не меньше 90 % прежней пары «угол + противоположный угол»
      // (мебель важнее стен — магазин мебели; живое 3D 17.10)
      const bins = (cams: Cam[]) => new Set(cams.flatMap((c) => [...api.camStats(c, list, W, H).bins])).size;
      expect(bins(pr.cams)).toBeGreaterThanOrEqual(0.9 * bins(api.camPairCorner(list, W, H, cs).cams));
    });
  it("портрет телефона: подобранный сдвиг ставит пол и потолок примерно поровну, пол не больше 0.35", () => {
    for (const v of fx.variants) {
      const list = its(v);
      for (const c of api.camPair(list, W, H, cs).cams) {
        expect(c.pshift, `${v.style} ${c.name}`).toBeGreaterThanOrEqual(-0.15);
        expect(c.pshift!).toBeLessThanOrEqual(0.05);
        const s = api.camStats(c, list, W, H, { w: 64, h: 88, sn: -2 * c.pshift! });
        expect(Math.abs(s.floor - s.ceil), `${v.style} ${c.name} пол/потолок`).toBeLessThanOrEqual(0.06);
        // мебель низкая, глаз на 135 см: поднять её медиану в среднюю треть можно лишь ценой пола > 0.35 (замер 17.10) —
        // приоритет «пол и потолок поровну», медиана мебели — выше 4/5 высоты кадра (у вида от окна вниз тянет близкий столик)
        expect(s.floor, `${v.style} ${c.name} пол`).toBeLessThanOrEqual(0.35);
        expect(s.midY, `${v.style} ${c.name} мебель по высоте`).toBeGreaterThan(1 / 3);
        expect(s.midY).toBeLessThan(0.8);
      }
    }
  });
  it("подбор парой — по умолчанию (владелец «включай» 17.10), и без флага окружения", () => {
    delete process.env.CAMS_PAIR;
    const api0 = new Function("D", `${block};return {camPair};`)({ room: fx.room }) as typeof api;
    const v = fx.variants[0]!, list = its(v);
    expect(api0.camPair(list, W, H, cs).how).toMatch(/^пара/);
    process.env.CAMS_PAIR = "1";
  });
});
