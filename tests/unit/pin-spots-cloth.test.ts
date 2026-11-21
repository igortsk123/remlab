// ЯРЛЫК ШТОР: якорь по ВИДИМОЙ части рамки (T-20261120-122, П1.77, директор 20.11: ярлык штор «4 599 ₽» висел посреди стены у картин, далеко от штор).
// Причина: рамка шторы — от пола до потолка и вдоль всей стены окна, середина рамки уходила за правый край кадра, все места «на ткани»
// упирались в панель справа (`PINS.busy`), и ярлык падал на запасное «слева от рамки». Здесь — функция `pinSpots` страницы, вынутая из
// `tools/scout/flat215-demo/index.html`, и копия правила «занято» (`free` в `vwPinsTick`): кадр, края, зоны управления.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

type Box = [number, number, number, number];
type PinSpots = (p: { box: Box | null; x: number; y: number }, w: number, h: number, fw: number, pad: number, fh: number, onBody: boolean, onSpot: number) => [number, number][];

const html = readFileSync(resolve(__dirname, "../../tools/scout/flat215-demo/index.html"), "utf8");
const m = /function pinSpots\([\s\S]*?\n\}\n(?=\/\/ ПРЕДМЕТ НА ДРУГОМ)/.exec(html);
if (!m) throw new Error("в index.html нет pinSpots");
const pinSpots = new Function("PIN_GAP", `${m[0]}; return pinSpots;`)(6) as PinSpots;

const W = 96, H = 44, PAD = 4, FW = 910, FH = 828;
const hit = (a: { l: number; r: number; t: number; b: number }, o: { l: number; r: number; t: number; b: number }) => a.l < o.r && a.r > o.l && a.t < o.b && a.b > o.t;
// как `free` в `vwPinsTick`: внутри кадра с отступом и мимо зон управления
const firstFree = (spots: [number, number][], busy: { l: number; r: number; t: number; b: number }[]): [number, number] | undefined =>
  spots.find(([x, y]) => {
    const r = { l: x, r: x + W, t: y, b: y + H };
    return !(r.l < PAD || r.r > FW - PAD || r.t < PAD || r.b > FH - PAD || busy.some((o) => hit(r, o)));
  });
// панель справа (`#vside`) с зазором 8 px: в координатах кадра 3D она начинается ровно за его правым краем минус 8
const SIDE = { l: FW - 8, r: FW + 410, t: 0, b: 900 };
const HIDE_PRICES = { l: 771 - 8, r: 898 + 8, t: 12 - 8, b: 50 + 8 };

describe("ярлык штор: якорь по видимой части рамки (pinSpots)", () => {
  // кадр директора, Сканди гостиная 1440×900: рамка шторы [557…1567]×[−294…484] в координатах страницы, кадр 3D начинается с x=60
  const CLIPPED: Box = [497, -294, 1507, 484];

  it("рамка вылезает за правый и верхний край кадра: ярлык встаёт на видимую ткань, а не слева от рамки у картин", () => {
    const at = firstFree(pinSpots({ box: CLIPPED, x: 0, y: 0 }, W, H, FW, PAD, FH, true, 0.12), [SIDE, HIDE_PRICES]);
    expect(at, "место нашлось").toBeDefined();
    const [x, y] = at!;
    expect(x + W / 2, "середина ярлыка — над тканью (не левее рамки)").toBeGreaterThanOrEqual(CLIPPED[0]);
    expect(x + W, "целиком в кадре, мимо панели справа").toBeLessThanOrEqual(FW - 8);
    expect(y, "у видимого верха, не за краем кадра").toBeGreaterThanOrEqual(PAD);
    expect(y, "в верхней трети видимой ткани («у карниза», 12 %)").toBeLessThan(FH / 3);
  });

  it("то же без места у карниза (занято): остаётся на ткани — на высоте глаз, — а не слева от рамки", () => {
    const all = pinSpots({ box: CLIPPED, x: 0, y: 0 }, W, H, FW, PAD, FH, true, 0.12);
    const aboveEye = { l: 0, r: FW, t: 0, b: 200 };   // всё выше 200 px занято (картины, кнопки, другие ярлыки)
    const at = firstFree(all, [SIDE, HIDE_PRICES, aboveEye]);
    expect(at).toBeDefined();
    expect(at![0] + W / 2).toBeGreaterThanOrEqual(CLIPPED[0]);
    expect(at![1]).toBeGreaterThanOrEqual(200);
  });

  it("рамка целиком в кадре: прежнее место — середина ширины, середина ярлыка на 12 % высоты от верха рамки с подъёмом 6 px", () => {
    const box: Box = [300, 20, 420, 400];
    const first = pinSpots({ box, x: 0, y: 0 }, W, H, FW, PAD, FH, true, 0.12)[0]!;
    expect(first).toEqual([Math.round(360 - W / 2), Math.round(20 + 0.12 * 380 - H / 2 - 6)]);
  });

  it("плед (не штора): рамка в кадре — ярлык по центру рамки, как раньше; рамка у правого края — ярлык не уезжает за кадр", () => {
    const box: Box = [300, 100, 400, 160];
    expect(pinSpots({ box, x: 0, y: 0 }, W, H, FW, PAD, FH, false, 0.5)[0]).toEqual([Math.round(350 - W / 2), Math.round(130 - H / 2 - 6)]);
    const edge: Box = [880, 100, 980, 160];   // половина рамки за правым краем
    const at = firstFree(pinSpots({ box: edge, x: 0, y: 0 }, W, H, FW, PAD, FH, false, 0.5), []);
    expect(at, "место нашлось").toBeDefined();
    expect(at![0] + W).toBeLessThanOrEqual(FW - PAD);
  });

  it("обычный ценник (не ткань): порядок мест прежний — над рамкой, середина по ширине рамки", () => {
    const box: Box = [300, 200, 420, 400];
    expect(pinSpots({ box, x: 0, y: 0 }, W, H, FW, PAD, FH, false, 0)[0]).toEqual([Math.round(360 - W / 2), Math.round(200 - 6 - H)]);
  });

  it("рамка целиком за кадром по горизонтали: видимой ткани нет — места считаются от самой рамки, функция не падает", () => {
    const spots = pinSpots({ box: [1000, 100, 1300, 700], x: 0, y: 0 }, W, H, FW, PAD, FH, true, 0.12);
    expect(spots.length).toBeGreaterThan(0);
    for (const [x, y] of spots) expect(Number.isFinite(x) && Number.isFinite(y)).toBe(true);
  });
});
