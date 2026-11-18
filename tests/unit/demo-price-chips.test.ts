import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ЧИПЫ ЦЕНЫ «ЗАМЕНИТЬ» — СТУПЕНИ РОЛИ (T-20261118-61/5, план price-segments-01 шаг 2): окно читает `price_segments` из demo-data.json
// (границы строит `tools/scout/price_segments_build.py`) и `price_segment` товара (ставит сборка). Блок `PRICESEG` страницы — тот же код.
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// PRICESEG START"), html.indexOf("// PRICESEG END"));
type Seg = { roles: Record<string, { boundaries_rub: number[] | null }>; labels: Record<string, Record<string, string>> };
const page = new Function(`${block};return {segBounds,segOf,segChips};`)() as {
  segBounds: (base: string, seg: Seg) => number[] | null;
  segOf: (base: string, p: { price?: number; price_segment?: string }, seg: Seg) => string | null;
  segChips: (base: string, seg: Seg, en: boolean, fmt: (v: number) => string) => { key: string; txt: string }[];
};

const seg: Seg = {
  roles: { "шкаф": { boundaries_rub: [22999, 41990] }, "прихожая": { boundaries_rub: null }, "диван": { boundaries_rub: [65990, 116400] } },
  labels: { ru: { lo: "эконом", mid: "комфорт", hi: "премиум" }, en: { lo: "economy", mid: "comfort", hi: "premium" } },
};
const rub = (v: number) => `${Math.round(v).toLocaleString("ru-RU")} ₽`;
const gbp = (v: number) => `£${Math.round(v / 100)}`;

describe("чипы цены: ступени роли из данных", () => {
  it("по-русски: три чипа с диапазоном этой роли, у премиума «от», у эконома «до»", () => {
    const c = page.segChips("шкаф", seg, false, rub);
    const txt = (i: number) => c[i]?.txt ?? "";
    expect(c.map((x) => x.key)).toEqual(["lo", "mid", "hi"]);
    expect(txt(0)).toBe(`Эконом · до ${rub(22999)}`);
    expect(txt(1)).toBe(`Комфорт · ${Math.round(22999).toLocaleString("ru-RU")}–${rub(41990)}`);
    expect(txt(2)).toBe(`Премиум · от ${rub(41990)}`);
    expect(txt(1).match(/₽/g)?.length).toBe(1);   // единица — один раз, в конце диапазона
  });

  it("по-английски: своя пара, цена в валюте страницы (£)", () => {
    const c = page.segChips("шкаф", seg, true, gbp);
    expect(c.map((x) => x.txt)).toEqual(["Economy · under £230", "Comfort · £230–£420", "Premium · from £420"]);
    expect(c.every((x) => !/[А-Яа-яЁё₽]/.test(x.txt))).toBe(true);
  });

  it("границы у каждой роли свои: диван — не шкаф", () => {
    expect(page.segChips("диван", seg, false, rub)[1]?.txt).toBe(`Комфорт · ${Math.round(65990).toLocaleString("ru-RU")}–${rub(116400)}`);
  });

  it("роль без границ или без записи — чипов нет", () => {
    expect(page.segChips("прихожая", seg, false, rub)).toEqual([]);
    expect(page.segChips("кроватка", seg, false, rub)).toEqual([]);
    expect(page.segBounds("шкаф", { roles: { "шкаф": { boundaries_rub: [5, 3] } }, labels: {} })).toBeNull();
  });

  it("ступень товара — по метке сборки (семейство), нет метки — по цене; граница — в верхней ступени", () => {
    expect(page.segOf("шкаф", { price: 10000, price_segment: "hi" }, seg)).toBe("hi");
    expect(page.segOf("шкаф", { price: 22998 }, seg)).toBe("lo");
    expect(page.segOf("шкаф", { price: 22999 }, seg)).toBe("mid");
    expect(page.segOf("шкаф", { price: 41990 }, seg)).toBe("hi");
    expect(page.segOf("шкаф", {}, seg)).toBeNull();
    expect(page.segOf("прихожая", { price: 5000 }, seg)).toBeNull();
  });

  it("страница: фильтр по ступени — когда есть price_segments, прежние 30/60 тыс. — только запасной путь без данных", () => {
    expect(html).toMatch(/if\(F\.price&&D&&D\.price_segments\)\{if\(segOf\(base,p,D\.price_segments\)!==F\.price\)return false;\}\s*else\{/);
    expect(html).toMatch(/if\(D&&D\.price_segments\)segChips\(base,D\.price_segments,EN,money\)/);
  });
});
