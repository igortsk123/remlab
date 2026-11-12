import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ЗАМЕНА У СТЕНЫ — СПИНОЙ К СТЕНЕ (T-20261112-43, владелец TG 1052): после «Заменить» на товар другой глубины предмет, стоявший
// задом у стены, остаётся задом у стены. Функцию берём прямо из страницы демо (блок SWAPBACK), порог — SNAP_CM переноса.
type It = { x: number; y: number; rot: number; d: number };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const snap = html.slice(html.indexOf("// MOVESNAP START"), html.indexOf("// MOVESNAP END"));
const block = html.slice(html.indexOf("// SWAPBACK START"), html.indexOf("// SWAPBACK END"));
const api = new Function(`${snap};${block};return {swapKeepBack};`)() as {
  swapKeepBack: (it: It, d0: number, R: { w: number; d: number }) => void;
};
const R = { w: 439, d: 325 };
const swap = (it: It, d0: number): It => { const c = { ...it }; api.swapKeepBack(c, d0, R); return c; };

describe("замена предмета другой глубины: спиной к стене", () => {
  it("ТВ-тумба 50 → подвесная 32 у южной стены: задняя сторона остаётся у стены, и обратно", () => {
    const hung = swap({ x: 155.3, y: 25, rot: 0, d: 32 }, 50);
    expect(hung).toMatchObject({ x: 155.3, y: 16 });
    expect(swap({ ...hung, d: 50 }, 32)).toMatchObject({ x: 155.3, y: 25 });
  });
  it("все четыре стены: глубже — перёд выходит в комнату, задняя сторона на месте", () => {
    expect(swap({ x: 25, y: 160, rot: 90, d: 60 }, 50)).toMatchObject({ x: 30, y: 160 });
    expect(swap({ x: 200, y: 300, rot: 180, d: 60 }, 50)).toMatchObject({ x: 200, y: 295 });
    expect(swap({ x: 414, y: 160, rot: 270, d: 60 }, 50)).toMatchObject({ x: 409, y: 160 });
  });
  it("в 6 см от стены — задняя сторона остаётся в тех же 6 см", () => {
    expect(swap({ x: 100, y: 31, rot: 0, d: 30 }, 50)).toMatchObject({ y: 21 });
  });
  it("не у стены, не под прямым углом, та же глубина — место не трогаем", () => {
    expect(swap({ x: 220, y: 160, rot: 0, d: 30 }, 50)).toMatchObject({ x: 220, y: 160 });
    expect(swap({ x: 100, y: 25, rot: 35, d: 30 }, 50)).toMatchObject({ x: 100, y: 25 });
    expect(swap({ x: 100, y: 25, rot: 0, d: 50 }, 50)).toMatchObject({ x: 100, y: 25 });
  });
});
