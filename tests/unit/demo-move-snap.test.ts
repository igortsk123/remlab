import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ПЕРЕНОС КАК В SIMS (T-20261111-05/8): у стены ближе 10 см предмет встаёт вплотную. Функцию берём прямо из страницы демо (блок MOVESNAP).
type B = { x0: number; y0: number; x1: number; y1: number };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// MOVESNAP START"), html.indexOf("// MOVESNAP END"));
const api = new Function(`${block};return {snapWall,SNAP_CM};`)() as {
  snapWall: (b: B, W: number, D: number, tol?: number) => { dx: number; dy: number };
  SNAP_CM: number;
};
const W = 335, D = 380;

describe("перенос предмета в 3D: прилипание к стене", () => {
  it("порог — 10 см", () => expect(api.SNAP_CM).toBe(10));
  it("в 8 см от левой стены — встаёт к ней вплотную", () => {
    expect(api.snapWall({ x0: 8, y0: 100, x1: 208, y1: 190 }, W, D)).toEqual({ dx: -8, dy: 0 });
  });
  it("зашёл за правую стену на 6 см — возвращается вплотную; угол — к обеим стенам", () => {
    expect(api.snapWall({ x0: 241, y0: 100, x1: 341, y1: 150 }, W, D)).toEqual({ dx: -6, dy: 0 });
    expect(api.snapWall({ x0: 3, y0: 283, x1: 103, y1: 375 }, W, D)).toEqual({ dx: -3, dy: 5 });
  });
  it("дальше 10 см — не трогаем (посреди комнаты и заметно за стеной)", () => {
    expect(api.snapWall({ x0: 40, y0: 60, x1: 240, y1: 150 }, W, D)).toEqual({ dx: 0, dy: 0 });
    expect(api.snapWall({ x0: -30, y0: 60, x1: 170, y1: 150 }, W, D)).toEqual({ dx: 0, dy: 0 });
  });
});
