import { describe, expect, it } from "vitest";

import { collectionAsVariant, fromDemoVariant } from "@/lib/configurator/fromDemo";

// 3D из коллекции покупателя (b2b-05 п.5): расстановка коллекции, текущие цены, пропавший товар — не в сумме, разворот из витрины.
const data = {
  room: { w: 439, d: 325, title: "Гостиная", height_cm: 270, openings: [] },
  variants: [{ id: "set16", title: "Джапанди", style: "джапанди", items: [
    { role: "диван", x: 100, y: 100, rot: 0, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, sid: "1_1", msid: "1_1", yaw: 180 } },
  ] }],
};
const coll = { baseVariant: "set16", style: "джапанди", items: [
  { role: "диван", x: 300, y: 150, rot: 90, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 40000, sid: "1_1", msid: "1_1" } },
  { role: "кресло", x: 50, y: 50, rot: 0, w: 80, d: 80, h: 90, sku: { name: "Кресло", price: 20000, sid: "1_2", msid: "1_2" } },
] };
const CTX = { apartmentId: "flat215", partnerId: "demo", currency: "RUB" as const, basePrice: 1 };

describe("коллекция → 3D", () => {
  it("расстановка из коллекции, цена текущая, пропавшее — 0, разворот из витрины", () => {
    const d = collectionAsVariant(data, coll, { "1_1": { price: 55000, unavailable: false }, "1_2": { price: null, unavailable: true } });
    const r = fromDemoVariant(d, "set16", CTX)!;
    expect(r.apartment.slots[0]!.placement).toMatchObject({ x: 300, y: 150, rot: 90 });
    expect(r.catalogue.options.filter((o) => o.category === "furniture").map((o) => o.price)).toEqual([55000, 0]);
    expect((r.catalogue.options[0]!.asset as { yawDeg?: number }).yawDeg).toBe(180);
  });
});
