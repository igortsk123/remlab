import { describe, expect, it } from "vitest";

import { perM2Amount, settle, settlementOf } from "@/lib/configurator/settlement";

// demo-06 п.2: мебель — в сертификат, отделка — отдельно (RF доплата застройщику, UK цена квартиры); «по запросу» — не ноль.
describe("куда идёт деньга выбора", () => {
  it("мебель в сертификат, пол RF — доплата застройщику, сверх лимита — доплата покупателя", () => {
    const t = settle([
      { amount: 300_000, settlement: "allowance" },
      { amount: 250_000, settlement: "allowance" },
      { amount: 54_000, settlement: "developer_surcharge" },
    ], 470_000);
    expect(t).toMatchObject({ allowanceEligible: 550_000, allowanceCovered: 470_000, allowanceOverage: 80_000, developerSurcharge: 54_000, propertyPriceDelta: 0 });
  });

  it("UK: пол — в цену квартиры; «по запросу» — отдельно, не ноль", () => {
    const t = settle([{ amount: 1150, settlement: "property_price" }, { amount: 0, settlement: "allowance", onRequest: true, label: "Кухня Comfort" }], 0);
    expect(t.propertyPriceDelta).toBe(1150);
    expect(t.onRequest).toEqual(["Кухня Comfort"]);
    expect(t.allowanceEligible).toBe(0);
  });

  it("умолчания по рынку и виду: кухня — сертификат, пол RF — застройщику, UK — всё в пакет; явное — главнее", () => {
    expect(settlementOf("kitchen", "ru")).toBe("allowance");
    expect(settlementOf("flooring", "ru")).toBe("developer_surcharge");
    expect(settlementOf("walls", "ru")).toBe("developer_surcharge");
    expect(settlementOf("flooring", "ru", "allowance")).toBe("allowance");
    // demo-23 шаг 3 (владелец TG 878): опции застройщика UK — в пакет, а не в цену квартиры (было ADR-0298)
    for (const k of ["flooring", "walls", "bathroom", "kitchen", "wardrobe", "appliances"]) expect(settlementOf(k, "uk")).toBe("allowance");
    expect(settlementOf("flooring", "uk", "property_price")).toBe("property_price");   // партнёр может задать явно
    expect(settlementOf("wardrobe", "ru")).toBe("allowance");
  });

  it("за м² — округление один раз", () => {
    expect(perM2Amount(1249.5, 14.4)).toBe(17993);
  });
});
