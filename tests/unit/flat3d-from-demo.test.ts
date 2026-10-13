import { describe, expect, it } from "vitest";
import { baseSnapshotOf, fromDemoVariant, staleSlots } from "@/lib/configurator/fromDemo";

const CTX = { apartmentId: "flat215", partnerId: "demo", currency: "RUB" as const, basePrice: 9_578_200 };

const data = {
  room: { w: 439, d: 325, title: "Гостиная 14.4 м²", height_cm: 270,
    openings: [{ kind: "window", wall: "west", offset_cm: 70, width_cm: 150, sill_cm: 85, height_cm: 150 }] },
  variants: [{ id: "set16", title: "Джапанди", style: "джапанди", items: [
    { role: "диван", x: 166.1, y: 280, rot: 180, w: 162, d: 90, h: 79,
      sku: { name: "Диван X", price: 54990, msid: "112923_1", url: "https://xf.gdeslon.ru/cm/x", shop: "divan.ru" } },
    { role: "столик", x: 200, y: 180, rot: 0, w: 80, d: 80, h: 45, sku: { name: "Столик Y", msid: "99272_2" } },
    { role: "ковёр", x: 200, y: 200, rot: 0, w: 200, d: 150, h: 1, sku: { name: "Без меша" } },
  ] }],
};

describe("мост витрина → конфигуратор", () => {
  it("собирает комнату и мебель того же варианта", () => {
    const r = fromDemoVariant(data, "set16", CTX);
    expect(r).not.toBeNull();
    expect(r!.apartment.rooms).toHaveLength(1);
    expect(r!.apartment.rooms[0]!.w).toBe(439);
    // предмет без меша в сцену не попадает: серая коробка хуже отсутствия
    expect(r!.apartment.slots).toHaveLength(2);
    expect(r!.catalogue.options).toHaveLength(2);
  });

  it("сохраняет координаты и поворот как есть — конвенции совпадают", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    const sofa = r.apartment.slots[0]!;
    expect(sofa.placement).toMatchObject({ x: 166.1, y: 280, rot: 180, wCm: 162, dCm: 90, hCm: 79 });
  });

  it("ведёт в магазин партнёрской ссылкой", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    expect(r.catalogue.options[0]!.shopUrl).toContain("gdeslon.ru");
  });

  it("квартира — из реестра (id, застройщик, цена), набор — отдельным полем, цены товаров настоящие", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    expect(r.apartment).toMatchObject({ id: "flat215", baseVariant: "set16", style: "джапанди", developerId: "demo", basePrice: 9_578_200 });
    expect(r.catalogue.currency).toBe("RUB");
    expect(r.catalogue.options[0]!.price).toBe(54990);
  });

  it("имя места — роль и номер в роли: пересборка с другим порядком не сдвигает выбор", () => {
    const r1 = fromDemoVariant(data, "set16", CTX)!;
    const swapped = { ...data, variants: [{ ...data.variants[0]!, items: [...data.variants[0]!.items].reverse() }] };
    const r2 = fromDemoVariant(swapped, "set16", CTX)!;
    expect(r1.apartment.slots.map((s) => s.id).sort()).toEqual(r2.apartment.slots.map((s) => s.id).sort());
    expect(r1.apartment.slots[0]!.id).toBe("диван#0");
  });

  it("снимок набора: сменилась модель на месте — место помечается, а не подменяется молча", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    const snap = baseSnapshotOf(r.apartment, r.catalogue);
    expect(snap).toEqual({ "диван#0": "112923_1", "столик#0": "99272_2" });
    const saved = { version: 3 as const, apartmentId: "flat215", developerId: "demo", selections: {}, placements: {}, baseSnapshot: snap };
    expect(staleSlots(saved, { ...snap, "диван#0": "777_1" })).toEqual(["диван#0"]);
    expect(staleSlots(saved, snap)).toEqual([]);
  });

  it("упаковка: два стула из упаковки «2 шт.» — одна покупка, как в списке витрины", () => {
    const chairs = { ...data, variants: [{ id: "set1", style: "сканди", items: [
      { role: "стул", x: 10, y: 10, rot: 0, w: 45, d: 50, h: 85, sku: { name: "Стул А 2 шт.", price: 9000, pack: 2, msid: "1_1", url: "u" } },
      { role: "стул 2", x: 60, y: 10, rot: 0, w: 45, d: 50, h: 85, sku: { name: "Стул А 2 шт.", price: 9000, pack: 2, msid: "1_1", url: "u" } },
    ] }] };
    const r = fromDemoVariant(chairs, "set1", CTX)!;
    expect(r.catalogue.options.reduce((t, o) => t + o.price, 0)).toBe(9000);
  });

  it("неизвестный вариант — null, страница откроет обычную квартиру", () => {
    expect(fromDemoVariant(data, "setX", CTX)).toBeNull();
  });
});
