import { describe, expect, it } from "vitest";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";

const data = {
  room: { w: 439, d: 325, title: "Гостиная 14.4 м²", height_cm: 270,
    openings: [{ kind: "window", wall: "west", offset_cm: 70, width_cm: 150, sill_cm: 85, height_cm: 150 }] },
  variants: [{ id: "set16", title: "Джапанди", style: "джапанди", items: [
    { role: "диван", x: 166.1, y: 280, rot: 180, w: 162, d: 90, h: 79,
      sku: { name: "Диван X", msid: "112923_1", url: "https://xf.gdeslon.ru/cm/x", shop: "divan.ru" } },
    { role: "столик", x: 200, y: 180, rot: 0, w: 80, d: 80, h: 45, sku: { name: "Столик Y", msid: "99272_2" } },
    { role: "ковёр", x: 200, y: 200, rot: 0, w: 200, d: 150, h: 1, sku: { name: "Без меша" } },
  ] }],
};

describe("мост витрина → конфигуратор", () => {
  it("собирает комнату и мебель того же варианта", () => {
    const r = fromDemoVariant(data, "set16");
    expect(r).not.toBeNull();
    expect(r!.apartment.rooms).toHaveLength(1);
    expect(r!.apartment.rooms[0]!.w).toBe(439);
    // предмет без меша в сцену не попадает: серая коробка хуже отсутствия
    expect(r!.apartment.slots).toHaveLength(2);
    expect(r!.catalogue.options).toHaveLength(2);
  });

  it("сохраняет координаты и поворот как есть — конвенции совпадают", () => {
    const r = fromDemoVariant(data, "set16")!;
    const sofa = r.apartment.slots[0]!;
    expect(sofa.placement).toMatchObject({ x: 166.1, y: 280, rot: 180, wCm: 162, dCm: 90, hCm: 79 });
  });

  it("ведёт в магазин партнёрской ссылкой", () => {
    const r = fromDemoVariant(data, "set16")!;
    expect(r.catalogue.options[0]!.shopUrl).toContain("gdeslon.ru");
  });

  it("неизвестный вариант — null, страница откроет обычную квартиру", () => {
    expect(fromDemoVariant(data, "setX")).toBeNull();
  });
});
