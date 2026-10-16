import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// НОМЕР СОСТОЯНИЯ РАССТАНОВКИ (план demo-02 п.1, разбор Codex 14.10). Функции берём прямо со страницы демо (блок STATEID):
// кадр, список и сумма связываются этим номером, поэтому он обязан быть устойчивым к шуму и чувствительным к смыслу.
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// STATEID START"), html.indexOf("// STATEID END"));
const { stateIdOf } = new Function(`${block};return {stateIdOf};`)() as {
  stateIdOf: (items: unknown[], decor: unknown[], room: unknown, opts?: Record<string, string>) => string;
};

const room = { w: 439, d: 325, openings: [{ kind: "door", wall: "east", offset_cm: 230, width_cm: 90 }] };
const sofa = { role: "диван", x: 169.2, y: 78.4, rot: 0, w: 175, d: 155, h: 92, sku: { msid: "1_a", sid: "1_a" } };
const chairA = { role: "стул", x: 330, y: 45, rot: 90, w: 49, d: 53, h: 82, sku: { msid: "1_c", sid: "1_c" } };
const chairB = { role: "стул 2", x: 399, y: 114, rot: 180, w: 49, d: 53, h: 82, sku: { msid: "1_c", sid: "1_c" } };
const vase = [{ role: "ваза", sku: { sid: "1_v" } }];
const id = (items: unknown[], decor = vase, r = room) => stateIdOf(items, decor, r);

describe("номер состояния расстановки", () => {
  const base = id([sofa, chairA, chairB]);
  it("формат: s1- и 32 шестнадцатеричных знака", () => expect(base).toMatch(/^s1-[0-9a-f]{32}$/));
  it("порядок предметов не важен", () => expect(id([chairB, sofa, chairA])).toBe(base));
  it("шум перетаскивания меньше полсантиметра — то же состояние", () =>
    expect(id([{ ...sofa, x: 169.4, y: 78.1 }, chairA, chairB])).toBe(base));
  it("сдвиг на 2 см — другое состояние", () => expect(id([{ ...sofa, x: 171.2 }, chairA, chairB])).not.toBe(base));
  it("поворот 360 = 0, −90 = 270", () => {
    expect(id([{ ...sofa, rot: 360 }, chairA, chairB])).toBe(base);
    expect(id([sofa, { ...chairA, rot: -270 }, chairB])).toBe(base);
  });
  it("одинаковые стулья, поменянные местами, — то же состояние (номер роли не в счёт)", () => {
    const swapped = [sofa, { ...chairA, role: "стул 2" }, { ...chairB, role: "стул" }];
    expect(id(swapped)).toBe(base);
  });
  it("другой товар на том же месте, другая ваза, другая комната — другое состояние", () => {
    expect(id([{ ...sofa, sku: { msid: "1_b", sid: "1_b" } }, chairA, chairB])).not.toBe(base);
    expect(id([sofa, chairA, chairB], [{ role: "ваза", sku: { sid: "1_w" } }])).not.toBe(base);
    expect(id([sofa, chairA, chairB], vase, { ...room, w: 440 })).not.toBe(base);
  });
  it("подвесная тумба и угловой диван различаются", () => {
    expect(id([{ ...sofa, corner: true }, chairA, chairB])).not.toBe(base);
  });
  // demo-06: выбор пола застройщика — часть состояния; без выбора номер прежний (s1), кадры и коллекции не устаревают
  it("пол по умолчанию — прежний s1; выбранный пол — s2 и другой номер; порядок групп не важен", () => {
    expect(stateIdOf([sofa, chairA, chairB], vase, room, {})).toBe(base);
    const grey = stateIdOf([sofa, chairA, chairB], vase, room, { flooring: "laminate-oak-grey" });
    expect(grey).toMatch(/^s2-[0-9a-f]{32}$/);
    expect(stateIdOf([sofa, chairA, chairB], vase, room, { flooring: "parquet-herringbone" })).not.toBe(grey);
    expect(stateIdOf([sofa, chairA, chairB], vase, room, { tile: "a", flooring: "b" }))
      .toBe(stateIdOf([sofa, chairA, chairB], vase, room, { flooring: "b", tile: "a" }));
  });
});
