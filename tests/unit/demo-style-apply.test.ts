import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// СМЕНА СТИЛЯ БЕЗ ОЖИДАНИЯ (T-20261113-16, владелец 08:55 голосом: «при переключении стиля он зависает»). Замер на живом /demo
// (375, CPU ×4): окно выбора закрывалось через 1,0–1,3 с — вся смена (новая расстановка, список дважды, коллекция трижды, место картины
// у каждой строки) шла до того, как браузер нарисует закрытое окно. Функции берём со страницы демо, окружение — заглушки
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const cut = (from: string, to: string) => {
  const a = html.indexOf(from), b = html.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error(`нет блока ${from}`);
  return html.slice(a, b);
};

describe("тап по стилю: окно закрывается сразу, смена — после кадра", () => {
  const block = cut("function mixTilePick(", "function tapTiles(");
  function load() {
    const log: string[] = [], raf: (() => void)[] = [], timers: (() => void)[] = [];
    const MIX = { open: true, room: "living" as string | null };
    const mixClose = () => { log.push("close"); MIX.open = false; MIX.room = null; };
    const api = new Function("MIX", "mixClose", "mixRoomApply", "mixApply", "document", "requestAnimationFrame", "setTimeout", "performance", "location",
      `${block};return {mixTilePick};`)(
      MIX, mixClose, (r: string, id: string) => log.push(`room:${r}:${id}`), (ids: string[]) => log.push(`flat:${ids.join()}`),
      { hidden: false }, (f: () => void) => raf.push(f), (f: () => void) => timers.push(f), { now: () => 0 }, { search: "" },
    ) as { mixTilePick: (t: unknown) => void };
    const run = (q: (() => void)[]) => q.splice(0).forEach((f) => f());
    return { api, MIX, log, raf: () => run(raf), timers: () => run(timers) };
  }
  const tile = (id: string) => ({ disabled: false, dataset: { mxPh: id } });
  it("окно комнаты: закрытие — в той же задаче, смена стиля — только после кадра и отдельной задачей", () => {
    const t = load();
    t.api.mixTilePick(tile("modern"));
    expect(t.log).toEqual(["close"]);
    t.raf();
    expect(t.log).toEqual(["close"]);   // в кадре — ещё нет: браузер рисует закрытое окно
    t.timers();
    expect(t.log).toEqual(["close", "room:living:modern"]);
  });
  it("второй тап по закрытому окну — не применяется", () => {
    const t = load();
    t.api.mixTilePick(tile("modern"));
    t.api.mixTilePick(tile("loft"));
    t.raf(); t.timers();
    expect(t.log).toEqual(["close", "room:living:modern"]);
  });
  it("окно квартиры (без комнаты) — тот же порядок, стиль квартиры", () => {
    const t = load(); t.MIX.room = null;
    t.api.mixTilePick(tile("loft"));
    t.raf(); t.timers();
    expect(t.log).toEqual(["close", "flat:loft"]);
  });
});

describe("смена варианта без повторной работы", () => {
  const block = cut("function pickVariant(", "// ЛЮБОЙ ПОЛНОЭКРАННЫЙ СЛОЙ");
  it("список рисуется один раз (его рисует `load` → `draw`), коллекция — не повторно", () => {
    const n = { basket: 0, coll: 0 };
    const pick = new Function("cur", "load", "basket", "drawColl", "syncHash", "document", "allVariants", "baseRev", "items", "revision",
      `${block};return pickVariant;`)(
      0, () => { n.basket++; n.coll++; }, () => { n.basket++; }, () => { n.coll++; }, () => {},
      { getElementById: () => ({ hidden: false, textContent: "" }) }, () => [{}, { style: "лофт" }], "", [], () => "",
    ) as (i: number) => void;
    pick(1);
    expect(n).toEqual({ basket: 1, coll: 1 });
  });
});

describe("место картины и лампы — из памяти по входу", () => {
  const block = cut("const WHERE_MEMO", "// настольный декор");
  it("тот же вход — сцена не считает заново; мебель сдвинули — считает", () => {
    let calls = 0;
    const items = [{ role: "диван", x: 1 }];
    const win = { RemlabScene: { wallArtWhere: () => { calls++; return { картина: "диван" }; } } };
    const art = new Function("window", "curRoom", "liveDecor", "items", "clone", "location", `${block};return artWhere;`)(
      win, () => ({ w: 400, d: 300 }), () => [{ role: "картина" }], items, (x: unknown) => JSON.parse(JSON.stringify(x)), { href: "x" },
    ) as () => unknown;
    expect(art()).toEqual({ картина: "диван" });
    art();
    expect(calls).toBe(1);
    items[0]!.x = 50;
    art();
    expect(calls).toBe(2);
  });
});
