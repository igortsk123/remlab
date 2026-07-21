import { describe, it, expect } from "vitest";
import { plural, pluralUnit } from "@/lib/format/plural";

describe("plural — русские склонения по числу", () => {
  it("рулон: 1 / 2–4 / 5–20", () => {
    expect(pluralUnit("рулон", 1)).toBe("рулон");
    expect(pluralUnit("рулон", 2)).toBe("рулона");
    expect(pluralUnit("рулон", 4)).toBe("рулона");
    expect(pluralUnit("рулон", 5)).toBe("рулонов");
    expect(pluralUnit("рулон", 11)).toBe("рулонов");
    expect(pluralUnit("рулон", 21)).toBe("рулон");
    expect(pluralUnit("рулон", 22)).toBe("рулона");
    expect(pluralUnit("рулон", 25)).toBe("рулонов");
  });

  it("упаковка склоняется, инвариантные единицы — нет", () => {
    expect(pluralUnit("упаковка", 1)).toBe("упаковка");
    expect(pluralUnit("упаковка", 3)).toBe("упаковки");
    expect(pluralUnit("упаковка", 8)).toBe("упаковок");
    expect(pluralUnit("м²", 5)).toBe("м²");
    expect(pluralUnit("л", 5)).toBe("л");
    expect(pluralUnit("шт", 5)).toBe("шт");
  });

  it("plural — общий хелпер", () => {
    expect(plural(1, "смета", "сметы", "смет")).toBe("смета");
    expect(plural(3, "смета", "сметы", "смет")).toBe("сметы");
    expect(plural(12, "смета", "сметы", "смет")).toBe("смет");
  });
});
