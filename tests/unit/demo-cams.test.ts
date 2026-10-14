import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// КАМЕРА ПО УМОЛЧАНИЮ НЕ УПИРАЕТСЯ В БЛИЗКИЙ ПРЕДМЕТ (план demo-03, карта сценариев 2.8). Функции берём прямо из
// страницы демо (блок CAMFIT), расстановки — слепок пяти опубликованных вариантов 14.10.
type It = { role: string; x: number; y: number; rot: number; w: number; d: number; h: number | null };
type Cam = { x: number; y: number; rot: number; fov: number; cov: number; shift: number };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const api = new Function(`${block};return {camBlock,camFit,CAM_BLOCK};`)() as {
  camBlock: (c: { x: number; y: number; rot: number; fov: number }, its: It[]) => { cov: number; who: string };
  camFit: (cx: number, cy: number, its: It[], W: number, H: number) => Cam;
  CAM_BLOCK: number;
};
const fx = JSON.parse(readFileSync("tests/fixtures/demo-layouts-1410.json", "utf8")) as {
  room: { w: number; d: number }; variants: { id: string; items: It[] }[];
};
const { w: W, d: H } = fx.room;
const aim = (x: number, y: number) => Math.round((Math.atan2(W / 2 - x, y - H / 2) * 180) / Math.PI);

describe("камеры демо: отступ от близких предметов", () => {
  it("торшер в углу сканди закрывает прежнюю точку C2 — правило это видит", () => {
    const set2 = fx.variants.find((v) => v.id === "set2")!;
    const b = api.camBlock({ x: 3, y: 3, rot: aim(3, 3), fov: 72 }, set2.items);
    expect(b.who).toBe("торшер");
    expect(b.cov).toBeGreaterThan(api.CAM_BLOCK);
  });
  it("во всех вариантах и во всех четырёх углах (смена ракурса по кругу) находится открытая точка у стены", () => {
    const corners: [number, number][] = [[3, 3], [W - 3, 3], [W - 3, H - 3], [3, H - 3]];
    for (const v of fx.variants)
      for (const [x, y] of corners) {
        const c = api.camFit(x, y, v.items, W, H);
        expect(c.cov, `${v.id} угол ${x},${y}`).toBeLessThanOrEqual(api.CAM_BLOCK);
        expect(c.shift, `${v.id} угол ${x},${y}: сдвиг`).toBeLessThanOrEqual(150);
        expect(c.x === 3 || c.x === W - 3 || c.y === 3 || c.y === H - 3, `${v.id}: камера у стены`).toBe(true);
      }
  });
  it("ковёр и дальний диван — не помеха", () => {
    const rug: It = { role: "ковёр", x: 60, y: 60, rot: 0, w: 230, d: 160, h: null };
    const sofa: It = { role: "диван", x: 300, y: 250, rot: 0, w: 200, d: 90, h: 85 };
    expect(api.camBlock({ x: 3, y: 3, rot: aim(3, 3), fov: 72 }, [rug, sofa]).cov).toBe(0);
  });
});
