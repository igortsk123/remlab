import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// «ОТМЕНА» В РЕЖИМЕ «✥» — ВСЁ КАК ДО НЕГО (T-20261112-97/2): предмет на прежнем месте и шторка телефона там, где была при «✥».
// С предметом в руке шторку поднимают не выше средней — после «Отмены» она оставалась поднятой и закрывала сцену. Функции берём со
// страницы демо (блок от «ОТМЕНА» до «поставить»), окружение — заглушки
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// «ОТМЕНА» — ВСЁ КАК ДО «✥»"), html.indexOf("// поставить: на зелёном"));

type Env = { phone: boolean; vis: number | null; pos: string; edges: { min: number; max: number } };
function load(env: Env) {
  const applied: Array<[number, boolean]> = [];
  const log: string[] = [];
  const VW: Record<string, unknown> = { sheetVis: env.vis, mv: null };
  const sd = { dataset: { pos: env.pos } };
  const api = new Function(
    "VW", "LIVE", "VW_PHONE", "vwEdges", "vwSheetApply", "vwCarryEnd", "document",
    `${block};return {vwCarryCancel, vwSheetOf, vwSheetBack};`,
  )(
    VW,
    { scene: { moveEnd: (keep: boolean) => log.push(`moveEnd:${keep}`) } },
    () => env.phone,
    () => env.edges,
    (vis: number, anim: boolean) => { applied.push([vis, anim]); VW.sheetVis = vis; },
    () => { VW.mv = null; log.push("end"); },
    { getElementById: (id: string) => (id === "vside" ? sd : null) },
  ) as { vwCarryCancel: (back?: boolean) => void; vwSheetOf: () => { pos: string; vis: number } | null };
  return { api, VW, sd, applied, log };
}

describe("«Отмена» в режиме «✥»: шторка как до него", () => {
  it("свёрнутую шторку подняли с предметом в руке — «Отмена» сворачивает обратно (по текущему низу)", () => {
    const t = load({ phone: true, vis: 132, pos: "0", edges: { min: 132, max: 640 } });
    t.VW.mv = { i: 3, sheet0: t.api.vwSheetOf() };
    t.VW.sheetVis = 233; t.sd.dataset.pos = "2";            // подняли — встала на средней (предел, пока предмет в руке)
    t.api.vwCarryCancel(true);
    expect(t.log).toEqual(["moveEnd:false", "end"]);
    expect(t.applied).toEqual([[132, true]]);
  });

  it("средняя — та же высота; шапка сменила края — в пределах краёв", () => {
    const t = load({ phone: true, vis: 233, pos: "2", edges: { min: 132, max: 640 } });
    t.VW.mv = { i: 3, sheet0: t.api.vwSheetOf() };
    t.VW.sheetVis = 132;
    t.api.vwCarryCancel(true);
    expect(t.applied).toEqual([[233, true]]);
    const u = load({ phone: true, vis: 700, pos: "2", edges: { min: 132, max: 640 } });
    u.VW.mv = { i: 3, sheet0: u.api.vwSheetOf() };
    u.VW.sheetVis = 300;
    u.api.vwCarryCancel(true);
    expect(u.applied).toEqual([[640, true]]);
  });

  it("шторка не двигалась — не трогаем; служебная отмена (без back) — не трогаем", () => {
    const t = load({ phone: true, vis: 233, pos: "2", edges: { min: 132, max: 640 } });
    t.VW.mv = { i: 3, sheet0: t.api.vwSheetOf() };
    t.api.vwCarryCancel(true);
    expect(t.applied).toEqual([]);
    const u = load({ phone: true, vis: 132, pos: "0", edges: { min: 132, max: 640 } });
    u.VW.mv = { i: 3, sheet0: u.api.vwSheetOf() };
    u.VW.sheetVis = 233;
    u.api.vwCarryCancel();
    expect(u.log).toEqual(["moveEnd:false", "end"]);
    expect(u.applied).toEqual([]);
  });

  it("компьютер — шторки нет: ничего не запоминаем и не двигаем", () => {
    const t = load({ phone: false, vis: null, pos: "0", edges: { min: 0, max: 0 } });
    expect(t.api.vwSheetOf()).toBeNull();
    t.VW.mv = { i: 3, sheet0: t.api.vwSheetOf() };
    t.api.vwCarryCancel(true);
    expect(t.applied).toEqual([]);
  });

  it("явная отмена человеком — с возвратом шторки: «Отмена», Esc, второе «✥» и второе M; положение запоминают и мебель, и картина", () => {
    expect(html).toMatch(/\.vcx'\)\.addEventListener\('click',e=>\{e\.stopPropagation\(\); vwCarryCancel\(true\);\}\)/);
    expect(html).toMatch(/if\(e\.key==='Escape'\)\{\s*if\(VW\.mv\)vwCarryCancel\(true\);/);
    expect(html).toMatch(/KeyM'\)\{if\(VW\.mv\)\{e\.preventDefault\(\); vwCarryCancel\(true\); return;\}/);
    expect(html).toMatch(/if\(VW\.mv\)\{vwCarryCancel\(true\); return;\}\s*\/\/ второе нажатие «Переместить»/);
    expect(html.match(/sheet0:vwSheetOf\(\)/g)?.length).toBe(2);   // vwCarryStart (мебель) и vwArtStart (картина)
  });
});
