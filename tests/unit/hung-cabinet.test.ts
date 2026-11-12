import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { planObjects, type ObjectSpec } from "@/lib/viewer3d/build-scene";
import { liveApartment } from "@/lib/viewer3d/demo-scene";
import { TV_CENTER_HIGH_CM, TV_GAP_MIN_CM, TV_MAX_STAND_FRAC, TV_STAND_HANG_CM, TV_STAND_HANG_MIN_CM, hungLiftCm } from "@/lib/viewer3d/scene-extras";

// ПОДВЕСНОЕ В ЖИВОЙ СЦЕНЕ (T-20261112-43, владелец TG 1052: «меняю на тумбу подвесную — это должно быть корректно»). Подвесная
// тумба висит низом по норме occupancy.json → hung_furniture (T-20261112-91: 25 см); телевизор над ней — на стене задом к задней плоскости тумбы, низ выше её верха на зазор нормы и не уже
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
  it("подвесная: тумба висит по норме (25, под крупным ТВ ниже), ТВ на стене над ней — зазор ≥ нормы, задом к стене, не шире 0,9 тумбы", () => {
    const specs = specsOf([sofa, hungStand]);
    const st = specs.find((s) => s.slotId.startsWith("тв-тумба"))!;
    const tv = specs.find((s) => s.kind === "tv")!;
    expect(st.placement.elevCm!).toBeLessThanOrEqual(TV_STAND_HANG_CM);
    expect(st.placement.elevCm!).toBeGreaterThanOrEqual(TV_STAND_HANG_MIN_CM);
    expect(tv.kind === "tv" && tv.hung).toBe(true);
    expect(tv.placement.elevCm!).toBeGreaterThanOrEqual(st.placement.elevCm! + 30 + TV_GAP_MIN_CM - 0.05);
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

  it("подвесная прикроватная — верхом вровень с матрасом (bedside_top_cm), не на высоте ТВ-тумбы", () => {
    const occ = JSON.parse(readFileSync("services/planner-solver/rules/occupancy.json", "utf8")) as { hung_furniture: Record<string, number> };
    const specs = specsOf([sofa, floorStand, { role: "тумба прикроватная", x: 30, y: 18, rot: 0, w: 50, d: 30, h: 20,
      sku: { msid: "112923_5", name: "Тумба прикроватная подвесная divan.ru Кимбол 50x20", price: 1, hung: true } }]);
    const bs = specs.find((s) => s.slotId.startsWith("тумба прикроватная"))!;
    expect(bs.placement.elevCm! + 20).toBe(occ.hung_furniture.bedside_top_cm);
  });
});

// ОДНО ПРАВИЛО ВЕЗДЕ (T-20261112-91, владелец 13:39: «все правила должны работать везде, конвейером»). /demo и туры строят 3D
// одной функцией (`planObjects` → `sceneExtras`), фото тура — серверный кадр `draft_render.py`. Те же предметы → те же высоты
// тумбы и ТВ, что в эталоне, который считает сам серверный кадр (`tools/assets/scene_extras_golden.py`).
type GoldenScene = { name: string; items: { role: string; x: number; y: number; rot: number; w: number; d: number; h: number; name?: string }[];
  tv: null | { elevCm: number; hCm: number; standElevCm: number | null } };
const golden = JSON.parse(readFileSync("tests/fixtures/scene-extras-golden.json", "utf8")) as { scenes: GoldenScene[] };

describe("высоты подвесной тумбы и ТВ: живая сцена (/demo и туры) = серверный кадр", () => {
  const hungScenes = golden.scenes.filter((sc) => sc.tv?.standElevCm);
  it("в эталоне есть подвесные случаи, в том числе опущенная тумба под крупный ТВ", () => {
    expect(hungScenes.length).toBeGreaterThanOrEqual(3);
    expect(hungScenes.some((sc) => sc.tv!.standElevCm! < TV_STAND_HANG_CM)).toBe(true);
  });
  for (const sc of hungScenes) {
    it(sc.name, () => {
      const specs = specsOf(sc.items.map((it, i) => ({ ...it, sku: { msid: `91_${i}`, name: it.name ?? it.role, price: 1 } })));
      const st = specs.find((s) => s.slotId.startsWith("тв-тумба"))!;
      const tv = specs.find((s) => s.kind === "tv")!;
      expect(Math.abs(st.placement.elevCm! - sc.tv!.standElevCm!)).toBeLessThan(0.05);
      expect(Math.abs(tv.placement.elevCm! - sc.tv!.elevCm)).toBeLessThan(0.05);
      // центр экрана — не выше коридора нормы, пока тумбу есть куда опускать
      if (st.placement.elevCm! > TV_STAND_HANG_MIN_CM) expect(tv.placement.elevCm! + tv.placement.hCm / 2).toBeLessThanOrEqual(TV_CENTER_HIGH_CM + 0.05);
    });
  }
});
