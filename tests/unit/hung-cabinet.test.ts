import { describe, expect, it } from "vitest";

import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { planObjects, type ObjectSpec } from "@/lib/viewer3d/build-scene";
import { liveApartment } from "@/lib/viewer3d/demo-scene";
import { TV_MAX_STAND_FRAC, TV_STAND_HANG_CM, hungLiftCm } from "@/lib/viewer3d/scene-extras";

// ПОДВЕСНОЕ В ЖИВОЙ СЦЕНЕ (T-20261112-43, владелец TG 1052: «меняю на тумбу подвесную — это должно быть корректно»). Подвесная
// тумба висит низом на 40 см; телевизор над ней — на стене задом к задней плоскости тумбы, низ на 10 см выше её верха и не уже
// правила 0,9 ширины тумбы; напольная — телевизор на тумбе; подвесной комод тоже висит. Ничего не проходит сквозь другое.
const room = { w: 439, d: 325, title: "Гостиная", openings: [] };
const sofa = { role: "диван", x: 220, y: 270, rot: 180, w: 220, d: 95, h: 85, sku: { msid: "112923_1", name: "Диван", price: 1 } };
const hungStand = { role: "тв-тумба", x: 155, y: 16, rot: 0, w: 160, d: 32, h: 30,
  sku: { msid: "112923_2", name: "ТВ-тумба подвесная divan.ru Енссон 160x30 Латте", price: 1, hung: true } };
const floorStand = { role: "тв-тумба", x: 155, y: 25, rot: 0, w: 139, d: 50, h: 62, sku: { msid: "112923_3", name: "ТВ-тумба divan.ru Теджонс 139x62", price: 1 } };

function specsOf(items: object[]): ObjectSpec[] {
  const b = liveApartment(room, items as never, "https://remont-lab.online/demo/")!;
  const sc = resolveScene(b.apartment, b.catalogue, defaultConfiguration(b.apartment, b.catalogue));
  return planObjects(b.apartment, b.catalogue, sc);
}
const back = (s: ObjectSpec): number => s.placement.y - s.placement.dCm / 2;   // rot 0 — задом к южной стене (y = 0)

describe("подвесная тумба и телевизор в живой сцене", () => {
  it("подвесная: тумба висит на 40 см, ТВ на стене над ней — зазор ≥ 10 см, задом к стене, не шире 0,9 тумбы", () => {
    const specs = specsOf([sofa, hungStand]);
    const st = specs.find((s) => s.slotId.startsWith("тв-тумба"))!;
    const tv = specs.find((s) => s.kind === "tv")!;
    expect(st.placement.elevCm).toBe(TV_STAND_HANG_CM);
    expect(tv.kind === "tv" && tv.hung).toBe(true);
    expect(tv.placement.elevCm!).toBeGreaterThanOrEqual(TV_STAND_HANG_CM + 30 + 10);
    expect(tv.placement.wCm).toBeLessThanOrEqual(160 * TV_MAX_STAND_FRAC + 0.05);
    expect(back(tv)).toBeCloseTo(back(st), 5);
    expect(back(st)).toBeCloseTo(0, 5);
  });
  it("напольная: телевизор на тумбе, по её середине, с подставкой", () => {
    const specs = specsOf([sofa, floorStand]);
    const st = specs.find((s) => s.slotId.startsWith("тв-тумба"))!;
    const tv = specs.find((s) => s.kind === "tv")!;
    expect(st.placement.elevCm ?? 0).toBe(0);
    expect(tv.kind === "tv" && tv.hung).toBe(false);
    expect(tv.placement.elevCm).toBe(62);
    expect(tv.placement.y).toBe(st.placement.y);
  });
  it("подвесной комод висит, как подвесная тумба; напольный — на полу; полка и кашпо «настенные» — не тумбы", () => {
    expect(hungLiftCm("комод", "Тумба подвесная divan.ru Сайрис 98x25 Черный")).toBe(TV_STAND_HANG_CM);
    expect(hungLiftCm("тумба прикроватная 2", "Тумба прикроватная подвесная divan.ru Кимбол 50x20")).toBe(TV_STAND_HANG_CM);
    expect(hungLiftCm("комод", "Комод divan.ru Сайрис")).toBe(0);
    expect(hungLiftCm("кашпо", "Кашпо настенное Glasar 35х18х44 см")).toBe(0);
    const specs = specsOf([sofa, floorStand, { role: "комод", x: 380, y: 18, rot: 0, w: 98, d: 35, h: 25,
      sku: { msid: "112923_4", name: "Тумба подвесная divan.ru Сайрис 98x25 Черный", price: 1, hung: true } }]);
    expect(specs.find((s) => s.slotId.startsWith("комод"))!.placement.elevCm).toBe(TV_STAND_HANG_CM);
  });
});
