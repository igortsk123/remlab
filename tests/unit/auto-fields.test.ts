import { describe, it, expect } from "vitest";
import { applyAutoSpec, manualKeys } from "@/lib/calc/auto-fields";

describe("auto-fields — источник значений (авто из ссылки / вручную)", () => {
  it("новая ссылка стирает ТОЛЬКО авто-значения, ручные остаются", () => {
    // было: ширина авто (из прошлой ссылки), цена — руками
    const r1 = applyAutoSpec({ rollWidthM: 1.06, pricePerRollRub: 2000 }, ["rollWidthM"], { rollLengthM: 10 });
    expect(r1.spec).toEqual({ pricePerRollRub: 2000, rollLengthM: 10 }); // авто-ширина стёрта, ручная цена жива
    expect(r1.autoKeys).toEqual(["rollLengthM"]);
  });

  it("ручная правка снимает пометку «авто» со своего поля", () => {
    expect(manualKeys(["rollWidthM", "rollLengthM"], { rollWidthM: 0.53 })).toEqual(["rollLengthM"]);
    expect(manualKeys(undefined, { seamMm: 2 })).toEqual([]);
  });

  it("повторная ссылка перезаписывает авто-поля новыми значениями", () => {
    const r = applyAutoSpec({ rollWidthM: 1.06, rollLengthM: 10 }, ["rollWidthM", "rollLengthM"], { rollWidthM: 0.53 });
    expect(r.spec).toEqual({ rollWidthM: 0.53 });
    expect(r.autoKeys).toEqual(["rollWidthM"]);
  });
});
