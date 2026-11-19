import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ПУСТАЯ ЛЕНТА «ЗАМЕНИТЬ» — ПОДСКАЗКА И КНОПКА СБРОСА НА ВСЕХ ПУТЯХ (T-20261118-61/8/1): живая проверка 18.11 — торшер + «Эконом» + «по размеру +
// стиль» давал 0 карточек и пустую шторку (после фильтров оставался только текущий товар → путь «других моделей нет» молчал). Одна функция
// `emptyFeed` на все пути; живой обход всех сочетаний «роль × ступень × размер × стиль» — `tools/ops/demo-walk/empty-feed-check.cjs`.
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const a = html.indexOf("function emptyFeed(g,msg){"), z = html.indexOf("function grid(){", a);
const gridSrc = html.slice(z, html.indexOf("function trNowCard(g,base){", z));

type Flt = { price: string | null; fitOnly: boolean; anyStyle: boolean };
function run(F: Flt, en: boolean, msg: [string, string] | null) {
  const log: string[] = [];
  const kids: { cls: string; txt: string; click?: () => void }[] = [];
  const g = {
    insertAdjacentHTML: (_w: string, h: string) => kids.push({ cls: "hint", txt: h.replace(/<[^>]+>/g, "") }),
    appendChild: (row: { kids: typeof kids }) => kids.push(...row.kids),
  };
  const doc = {
    createElement: (t: string) => {
      const e: { kids: typeof kids; className: string; textContent: string; onclick?: () => void; appendChild: (c: unknown) => void } = {
        kids: [], className: "", textContent: "", appendChild(c) { const b = c as { className: string; textContent: string; onclick?: () => void }; this.kids.push({ cls: b.className, txt: b.textContent, click: b.onclick }); },
      };
      void t;
      return e;
    },
  };
  const fn = new Function("F", "TR_EN", "document", "filters", "grid", `${html.slice(a, z)};return emptyFeed;`)(F, () => en, doc, () => log.push("filters"), () => log.push("grid")) as (g: unknown, m: unknown) => void;
  fn(g, msg);
  return { kids, log, F };
}

describe("пустая лента замены: одно правило", () => {
  it("подсказка по-русски и по-английски, без кириллицы в EN", () => {
    const ru = run({ price: "lo", fitOnly: true, anyStyle: false }, false, ["Нет.", "None."]);
    const en = run({ price: "lo", fitOnly: true, anyStyle: false }, true, ["Нет.", "None."]);
    expect(ru.kids.map((k) => k.txt)).toEqual(["Нет.", "Сбросить фильтры"]);
    expect(en.kids.map((k) => k.txt)).toEqual(["None.", "Clear filters"]);
    expect(en.kids.every((k) => !/[А-Яа-яЁё]/.test(k.txt))).toBe(true);
  });

  it("кнопка снимает цену и размер, стиль перестаёт резать, и перерисовывает окно", () => {
    const F: Flt = { price: "hi", fitOnly: true, anyStyle: false };
    const r = run(F, false, ["Нет.", "None."]);
    r.kids.find((k) => k.cls.includes("reset"))?.click?.();
    expect(F).toEqual({ price: null, fitOnly: false, anyStyle: true });
    expect(r.log).toEqual(["filters", "grid"]);
  });

  it("любое одно включённое ограничение — кнопка есть; ничего не включено — кнопки нет (сбрасывать нечего)", () => {
    for (const F of [{ price: "mid", fitOnly: false, anyStyle: true }, { price: null, fitOnly: true, anyStyle: true }, { price: null, fitOnly: false, anyStyle: false }])
      expect(run(F, false, ["Нет.", "None."]).kids.some((k) => k.cls.includes("reset"))).toBe(true);
    expect(run({ price: null, fitOnly: false, anyStyle: true }, false, ["Нет.", "None."]).kids.some((k) => k.cls.includes("reset"))).toBe(false);
  });

  it("msg=null — свою подсказку место вызова уже вывело: только кнопка", () => {
    expect(run({ price: "lo", fitOnly: true, anyStyle: false }, false, null).kids.map((k) => k.txt)).toEqual(["Сбросить фильтры"]);
  });

  it("лента: каждый путь «карточек нет» зовёт emptyFeed; старой одноязычной подсказки без кнопки нет", () => {
    // после фильтров не осталось ничего
    expect(gridSrc).toMatch(/if\(!list\.length\)\{head\(0\); if\(TRIAL\(\)\)trNowCard\(g,base\);\s*emptyFeed\(g,\[/);
    // осталась только текущая модель (цвета/ничего) — не молчим ни в /demo, ни в туре
    expect(gridSrc).toMatch(/if\(!list\.length\)emptyFeed\(g,TRIAL\(\)&&colours\.length<2\?null:\[/);
    expect(gridSrc).toContain("trNone()");   // тур: своя строка «других товаров с 3D-моделью…» + кнопка из emptyFeed(null)
    expect(html).not.toContain("Снимите ограничения");
  });
});
