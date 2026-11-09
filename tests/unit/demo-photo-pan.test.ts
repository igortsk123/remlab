import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ФОТО НА ТЕЛЕФОНЕ ДВИГАЕТСЯ ПАЛЬЦЕМ, У КРАЯ — ДРУГОЙ ВИД (план photo-swipe-pan-01, владелец 09.11). Функции берём прямо из страницы
// демо (блок VWPAN): `vwPanMove` — куда встаёт фото под пальцем, `vwPanEnd` — менять ли вид, когда палец отпустили.
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// VWPAN START"), html.indexOf("// VWPAN END"));
const api = new Function(`${block};return {vwIsSwipe,vwPanMove,vwPanEnd};`)() as {
  vwIsSwipe: (dx: number, dy: number, ms: number) => boolean;
  vwPanMove: (sl0: number, dx: number, over: number) => { sl: number; rub: number };
  vwPanEnd: (dx: number, dy: number, ms: number, sl0: number, over: number, many: boolean) => number;
};
const OVER = 336; // 375×667: фото ~711 px по ширине в области 375 px

describe("демо: фото двигается пальцем", () => {
  it("палец ведёт фото 1:1 внутри ширины", () => {
    expect(api.vwPanMove(100, -60, OVER)).toEqual({ sl: 160, rub: 0 });
    expect(api.vwPanMove(100, 40, OVER)).toEqual({ sl: 60, rub: 0 });
    expect(api.vwPanMove(0, -OVER, OVER)).toEqual({ sl: OVER, rub: 0 });
  });

  it("за краем — фото у края и резинка ×0,3 в сторону пальца", () => {
    expect(api.vwPanMove(OVER, -100, OVER)).toEqual({ sl: OVER, rub: -30 });
    expect(api.vwPanMove(0, 100, OVER)).toEqual({ sl: 0, rub: 30 });
    expect(api.vwPanMove(300, -136, OVER)).toEqual({ sl: OVER, rub: -30 });
  });

  it("фото не шире области — не двигается, только резинка", () => {
    expect(api.vwPanMove(0, -80, 0)).toEqual({ sl: 0, rub: -24 });
    expect(api.vwPanMove(0, 80, -5)).toEqual({ sl: 0, rub: 24 });
  });
});

describe("демо: смена вида — свайп у края", () => {
  const fast = 200;
  it("у правого края свайп влево — следующий вид; у левого вправо — предыдущий", () => {
    expect(api.vwPanEnd(-120, 5, fast, OVER, OVER, true)).toBe(1);
    expect(api.vwPanEnd(-120, 5, fast, OVER - 2, OVER, true)).toBe(1);
    expect(api.vwPanEnd(120, 5, fast, 0, OVER, true)).toBe(-1);
    expect(api.vwPanEnd(120, 5, fast, 2, OVER, true)).toBe(-1);
  });

  it("начат не у края — вид тот же (фото доедет до края и встанет)", () => {
    expect(api.vwPanEnd(-200, 0, fast, 150, OVER, true)).toBe(0);
    expect(api.vwPanEnd(200, 0, fast, 150, OVER, true)).toBe(0);
    expect(api.vwPanEnd(-200, 0, fast, OVER - 10, OVER, true)).toBe(0);
  });

  it("у края, но в обратную сторону — вид тот же", () => {
    expect(api.vwPanEnd(120, 0, fast, OVER, OVER, true)).toBe(0);
    expect(api.vwPanEnd(-120, 0, fast, 0, OVER, true)).toBe(0);
  });

  it("фото не шире области — свайп в любую сторону меняет вид (как было)", () => {
    expect(api.vwPanEnd(-80, 0, fast, 0, 0, true)).toBe(1);
    expect(api.vwPanEnd(80, 0, fast, 0, 0, true)).toBe(-1);
  });

  it("не свайп — короткий, медленный, вертикальный — вид тот же", () => {
    expect(api.vwPanEnd(-40, 0, fast, OVER, OVER, true)).toBe(0);
    expect(api.vwPanEnd(-150, 0, 900, OVER, OVER, true)).toBe(0);
    expect(api.vwPanEnd(-60, 80, fast, OVER, OVER, true)).toBe(0);
  });

  it("вид один — сменить не на что", () => {
    expect(api.vwPanEnd(-120, 0, fast, OVER, OVER, false)).toBe(0);
  });

  it("порог свайпа прежний: ≥ 50 px, вбок в 1,5 раза больше, ≤ 700 мс", () => {
    expect(api.vwIsSwipe(50, 0, 700)).toBe(true);
    expect(api.vwIsSwipe(49, 0, 100)).toBe(false);
    expect(api.vwIsSwipe(60, 40, 100)).toBe(false);
    expect(api.vwIsSwipe(60, 0, 701)).toBe(false);
  });
});
