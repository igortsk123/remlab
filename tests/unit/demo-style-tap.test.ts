import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { NO_ZOOM_JS } from "@/lib/page/no-zoom";

// ВЫБОР СТИЛЯ ОДНИМ КАСАНИЕМ (T-20261113-16, владелец TG 1527–1530, iPhone): в окне «Другой стиль для комнаты» тап по фото плитки не
// выбирал стиль. Касание решает `tapTiles` по touchend: выбор — только если палец за всё касание не ушёл дальше 10 px, касание одним
// пальцем и окно не прокрутилось (прокрутка ≠ выбор); тогда preventDefault — click не придёт, двойного выбора нет. Функцию берём со
// страницы демо (от `function tapTiles(` до `function mixRender(`), окружение — заглушки. И запрет масштаба (no-zoom) одиночный тап не гасит
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("function tapTiles("), html.indexOf("function mixRender("));

type Touch = { clientX: number; clientY: number };
type Ev = { target?: unknown; touches: Touch[]; changedTouches?: Touch[]; prevented: boolean; preventDefault: () => void };
const ev = (touches: Touch[], extra: Partial<Ev> = {}): Ev => {
  const e: Ev = { touches, prevented: false, preventDefault: () => { e.prevented = true; }, ...extra };
  return e;
};

function load() {
  const on: Record<string, (e: Ev) => void> = {};
  const card = { scrollTop: 0 };
  const tile = { disabled: false, isConnected: true, closest: () => tile };
  const box = { querySelector: () => card, addEventListener: (t: string, f: (e: Ev) => void) => { on[t] = f; } };
  const picked: unknown[] = [];
  const win = { scrollY: 0 };
  const tapTiles = new Function("window", `${block};return tapTiles;`)(win) as (b: unknown, s: string, f: (t: unknown) => void) => void;
  tapTiles(box, "[data-mx-ph]", (t) => picked.push(t));
  const at = (x: number, y: number): Touch => ({ clientX: x, clientY: y });
  const start = (x = 100, y = 200) => on.touchstart?.(ev([at(x, y)], { target: tile }));
  const move = (x: number, y: number, n = 1) => on.touchmove?.(ev(Array(n).fill(at(x, y))));
  const end = (x = 100, y = 200) => { const e = ev([], { changedTouches: [at(x, y)] }); on.touchend?.(e); return e; };
  return { picked, card, tile, win, start, move, end };
}

describe("плитка стиля: одно касание пальцем = выбор, прокрутка ≠ выбор", () => {
  it("тап на месте (сдвиг 3 px) — выбор один раз, click браузера погашен", () => {
    const t = load();
    t.start(); t.move(102, 201);
    const e = t.end(103, 200);
    expect(t.picked).toEqual([t.tile]);
    expect(e.prevented).toBe(true);
  });
  it("палец ушёл на 15 px и вернулся — не выбор (сдвиг считается за всё касание)", () => {
    const t = load();
    t.start(); t.move(100, 215);
    const e = t.end(100, 200);
    expect(t.picked).toEqual([]);
    expect(e.prevented).toBe(false);
  });
  it("окно прокрутилось (палец почти на месте) — не выбор: прокрутка окна стиль не выбирает", () => {
    const t = load();
    t.start(); t.card.scrollTop = 40;
    expect(t.end(100, 205).prevented).toBe(false);
    expect(t.picked).toEqual([]);
  });
  it("страница прокрутилась — тоже не выбор", () => {
    const t = load();
    t.start(); t.win.scrollY = 30;
    t.end();
    expect(t.picked).toEqual([]);
  });
  it("два пальца — не выбор", () => {
    const t = load();
    t.start(); t.move(100, 200, 2);
    t.end();
    expect(t.picked).toEqual([]);
  });
  it("плитка недоступна (кадры ещё не пришли) — не выбор", () => {
    const t = load();
    t.tile.disabled = true;
    t.start(); t.end();
    expect(t.picked).toEqual([]);
  });
});

describe("запрет масштаба (no-zoom) одиночный тап не гасит", () => {
  const on: Record<string, (e: Ev & { scale?: number }) => void> = {};
  new Function("window", "document", NO_ZOOM_JS)({}, { addEventListener: (t: string, f: (e: Ev) => void) => { on[t] = f; } });
  it("слушает только жесты и touchmove — не touchstart, touchend и click", () => {
    expect(Object.keys(on).sort()).toEqual(["gesturechange", "gestureend", "gesturestart", "touchmove"]);
  });
  it("touchmove одним пальцем (scale 1 или без scale) — не гасит; двумя пальцами — гасит", () => {
    const one = ev([{ clientX: 1, clientY: 1 }]);
    on.touchmove?.(Object.assign(one, { scale: 1 }));
    expect(one.prevented).toBe(false);
    const bare = ev([{ clientX: 1, clientY: 1 }]);
    on.touchmove?.(bare);
    expect(bare.prevented).toBe(false);
    const two = ev([{ clientX: 1, clientY: 1 }, { clientX: 9, clientY: 9 }]);
    on.touchmove?.(two);
    expect(two.prevented).toBe(true);
  });
});

describe("плитки `.qz-ph`: цель касания — вся кнопка", () => {
  it("содержимое плитки касание не ловит, двойной тап не увеличивает, у картинки нет меню удержания", () => {
    expect(html).toContain(".qz-ph{touch-action:manipulation;");
    expect(html).toContain("-webkit-touch-callout:none");
    expect(html).toContain(".qz-ph *{pointer-events:none");
  });
  it("окно «Другой стиль» выбирает касанием через tapTiles, повторно не применяет", () => {
    expect(html).toContain("tapTiles(b, '[data-mx-ph]', mixTilePick)");
    expect(html).toMatch(/function mixTilePick\(t\)\{\s*if\(!MIX\.open\|\|!t\|\|t\.disabled\)return;/);
  });
});
