import { describe, expect, it } from "vitest";

import { fromDemoVariant, isCeilingDecor } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";

// T-20261112-66: люстра — в точке, которую прислал решатель паспорта (`place`, `planner/dependents.py:resolve`); своего расчёта
// центра у сцены нет. Размер в сцене — `sku.hang` (по мешу), в подписи — каталог
const CTX = { apartmentId: "t", partnerId: "demo", currency: "RUB" as const, basePrice: 0, assetBase: "/demo/demo-data.json" };
const SOFA = { role: "диван", x: 200, y: 305, rot: 180, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, msid: "s_1" } };
const TABLE = { role: "столик", x: 150, y: 180, rot: 0, w: 80, d: 50, h: 45, sku: { name: "Столик", price: 9000, msid: "t_1" } };
const hang = { w: 64, d: 57, h: 98 };
const place = { x: 210, y: 190, bottom_cm: 210, slot_instance_id: "ceiling.chandelier#0" };
const LAMP = { role: "люстра", strategy: "ceiling_over", place,
  sku: { name: "Люстра", price: 12000, msid: "l_1", w: 64, d: 64, h: 32, dia: 64, hang } };

describe("люстра из декора — по размерам сцены (`sku.hang`) и месту решателя (`place`)", () => {
  const sku = { msid: "m1", w: 64, d: 64, h: 32 };
  it("без размеров по мешу или без места — не люстра сцены", () => {
    expect(isCeilingDecor({ strategy: "ceiling_over", sku, place })).toBe(false);
    expect(isCeilingDecor({ strategy: "ceiling_over", sku: { ...sku, hang } })).toBe(false);
    expect(isCeilingDecor({ strategy: "ceiling_over", sku: { ...sku, hang }, place })).toBe(true);
    expect(isCeilingDecor({ strategy: "ceiling_over", list_only: true, sku: { ...sku, hang }, place })).toBe(false);
  });

  it("сцена ставит люстру в присланную точку и низ, не над столиком", () => {
    const data = { room: { w: 400, d: 350, title: "Комната", height_cm: 270, openings: [] },
      variants: [{ id: "v", style: "сканди", items: [SOFA, TABLE], decor: [LAMP] }] };
    const built = fromDemoVariant(data, "v", CTX)!;
    const slot = built.apartment.slots.find((s) => s.ceilingOver)!;
    expect(slot.ceilingOver).toEqual({ placeId: "ceiling.chandelier#0" });
    const sc = resolveScene(built.apartment, built.catalogue, defaultConfiguration(built.apartment, built.catalogue));
    const lamp = sc.items.find((i) => i.slotId === slot.id)!;
    const table = sc.items.find((i) => i.photoRole === "столик")!;
    // те же оси, что у мебели варианта: смещение комнаты в квартире одно на всех
    expect(lamp.placement.x - table.placement.x).toBeCloseTo(place.x - TABLE.x);
    expect(lamp.placement.y - table.placement.y).toBeCloseTo(place.y - TABLE.y);
    expect(lamp.placement).toMatchObject({ rot: 0, elevCm: 210, wCm: 64, dCm: 57, hCm: 98 });
    expect(lamp.unplaced).toBeUndefined();
  });
});
