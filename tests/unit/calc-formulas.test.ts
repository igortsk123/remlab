import { describe, it, expect } from "vitest";
import { computeRoom, computeRoomParts } from "@/lib/calc/formulas";
import type { Room } from "@/contracts/calc";

const wall = (id: string, lengthM: number, heightM: number): Room["surfaces"][number] => ({ id, label: "", lengthM, heightM, openings: [] });

describe("calc formulas — количество материала", () => {
  const box = (h: number) => [wall("a", 4, h), wall("b", 2, h), wall("c", 4, h), wall("d", 2, h)];

  it("обои: периметр 12, высота 2.5, рулон 0.53×10.05 → 8 рулонов", () => {
    const room: Room = {
      id: "r", name: "", material: { rollWidthM: 0.53, rollLengthM: 10.05 },
      surfaces: box(2.5),
    };
    const out = computeRoom(room, "oboi");
    expect(out.qty).toBe(8);
    expect(out.unit).toBe("рулон");
    expect(out.qtyUnknown).toBeFalsy();
  });

  // Правило «без выдумок» (ADR-0034): без параметров материала количество не считаем ни в одном виде.
  it("обои: размер рулона не задан → количество неизвестно, а не 8 рулонов по дефолту", () => {
    const out = computeRoom({ id: "r", name: "", material: {}, surfaces: box(2.5) }, "oboi");
    expect(out.qtyUnknown).toBe(true);
    expect(out.qty).toBe(0);
    expect(out.unit).toBe("рулон");
    expect(out.ask).toContain("размер рулона");
    expect(out.areaNetM2).toBeGreaterThan(0); // площадь считается всегда
  });

  it("краска: тип и расход не заданы → количество неизвестно", () => {
    const out = computeRoom({ id: "r", name: "", material: {}, surfaces: [wall("a", 4, 2.5)] }, "kraska");
    expect(out.qtyUnknown).toBe(true);
    expect(out.ask).toContain("тип краски");
  });

  it("ламинат: размеры панели не заданы → упаковки неизвестны", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [], material: { direction: "length" },
      floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] },
    };
    const out = computeRoom(room, "laminat");
    expect(out.qtyUnknown).toBe(true);
    expect(out.ask).toContain("размер панели");
  });

  it("плитка: 10 м², 300×300, шов 3мм, +10%, 10 шт/упак → 120 шт / 12 упак", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [wall("a", 4, 2.5)],
      material: { tileLengthMm: 300, tileWidthMm: 300, seamMm: 3, tilesPerPack: 10 },
    };
    const out = computeRoom(room, "plitka");
    expect(out.qty).toBe(120);
    expect(out.packs).toBe(12);
  });

  it("краска: 10 м², 2 слоя, расход 10, упак 0.9 л → 2 л / 3 упак", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [wall("a", 4, 2.5)],
      material: { coats: 2, consumptionM2PerL: 10, packVolumeL: 0.9 },
    };
    const out = computeRoom(room, "kraska");
    expect(out.qty).toBeCloseTo(2, 5);
    expect(out.packs).toBe(3);
  });

  // Панель 1380×193, 8 шт/упак = 2.13 м²/упак — тот же размер упаковки, что был дефолтом.
  const PANEL = { panelLengthMm: 1380, panelWidthMm: 193, panelsPerPack: 8 } as const;

  it("ламинат: пол 20 м², прямая укладка +5%, 2.13 м²/упак → 10 упак", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [],
      floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] },
      material: { direction: "length", ...PANEL },
    };
    expect(computeRoom(room, "laminat").qty).toBe(10);
  });

  it("ламинат: диагональ добавляет запас (20 м² → 11 упак)", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [],
      floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] },
      material: { direction: "diag45", ...PANEL },
    };
    expect(computeRoom(room, "laminat").qty).toBe(11);
  });

  it("ламинат: цена за м² приоритетна, стоимость — через целые упаковки", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [],
      floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] }, // 20 м²
      material: {
        direction: "length", panelLengthMm: 1380, panelWidthMm: 193, panelsPerPack: 8,
        pricePerM2Rub: 832.48, pricePerPackRub: 999_999, // м² должна победить упаковку
      },
    };
    const out = computeRoom(room, "laminat");
    expect(out.qty).toBe(10); // 20 × 1.05 ÷ 2.13072 → 10 упаковок
    expect(out.costRub).toBe(Math.round(10 * 1.38 * 0.193 * 8 * 832.48)); // 17738
  });

  it("плитка: стены и пол — РАЗНЫЕ плитки, две части", () => {
    const room: Room = {
      id: "r", name: "Коридор",
      surfaces: [wall("a", 4, 2.5)], // стены 10 м²
      material: { tileLengthMm: 300, tileWidthMm: 300, seamMm: 3, tilesPerPack: 10 }, // плитка стен
      floor: { lengthM: 2, widthM: 2, extraZones: [], excludedZones: [] }, // пол 4 м²
      floorMaterial: { tileLengthMm: 600, tileWidthMm: 600, seamMm: 2, tilesPerPack: 4 }, // ДРУГАЯ плитка пола
    };
    const parts = computeRoomParts(room, "plitka");
    expect(parts.map((p) => p.key)).toEqual(["walls", "floor"]);
    expect(parts[0]!.label).toBe("Стены");
    expect(parts[1]!.label).toBe("Пол");
    expect(parts[0]!.out.areaNetM2).toBeCloseTo(10, 2);
    expect(parts[1]!.out.areaNetM2).toBeCloseTo(4, 2);
    // разные размеры плитки → разные счётчики, не спутаны
    expect(parts[0]!.out.qty).toBe(120); // 10 м² плиткой 300×300
    expect(parts[1]!.out.qty).toBeGreaterThan(0);
    expect(parts[1]!.material.tileLengthMm).toBe(600);
  });

  it("плитка без пола → одна часть без метки", () => {
    const room: Room = { id: "r", name: "", surfaces: [wall("a", 4, 2.5)], material: {} };
    const parts = computeRoomParts(room, "plitka");
    expect(parts).toHaveLength(1);
    expect(parts[0]!.label).toBe("");
  });

  it("плитка: проём вычитается только при countOpenings", () => {
    const base: Room = {
      id: "r", name: "", material: {},
      surfaces: [{ id: "s", label: "", lengthM: 4, heightM: 2.5, openings: [{ id: "o", kind: "window", widthM: 1.5, heightM: 1.4, count: 1 }] }],
    };
    expect(computeRoomParts({ ...base, countOpenings: false }, "plitka")[0]!.out.areaNetM2).toBeCloseTo(10, 2); // полная
    expect(computeRoomParts({ ...base, countOpenings: true }, "plitka")[0]!.out.areaNetM2).toBeCloseTo(7.9, 2); // 10 − 2.1
  });

  it("плитка: крупная 600×1200 (мм) на ~20 м² → ~31 шт (не тысячи — контроль единиц)", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [wall("a", 8, 2.5)], // 20 м²
      material: { tileLengthMm: 600, tileWidthMm: 1200, seamMm: 3 },
    };
    const out = computeRoom(room, "plitka");
    expect(out.qty).toBe(31);
  });

  it("плитка: цена за м² → стоимость по площади+запасу; за шт → по числу плиток", () => {
    const room: Room = { id: "r", name: "", surfaces: [wall("a", 8, 2.5)], material: { tileLengthMm: 600, tileWidthMm: 1200, seamMm: 3 } };
    const perM2 = computeRoom({ ...room, material: { ...room.material, pricePerM2Rub: 1000 } }, "plitka");
    expect(perM2.costRub).toBe(Math.round(20 * 1.1 * 1000)); // 22000
    const perPiece = computeRoom({ ...room, material: { ...room.material, pricePerPieceRub: 500 } }, "plitka");
    expect(perPiece.costRub).toBe(31 * 500); // 15500
  });

  it("краска: проём вычитается только при countOpenings", () => {
    const base: Room = {
      id: "r", name: "", material: { consumptionM2PerL: 10, coats: 1 },
      surfaces: [{ id: "s", label: "", lengthM: 4, heightM: 2.5, openings: [{ id: "o", kind: "door", widthM: 1, heightM: 2, count: 1 }] }],
    };
    expect(computeRoom({ ...base, countOpenings: false }, "kraska").areaNetM2).toBeCloseTo(10, 2); // полная
    expect(computeRoom({ ...base, countOpenings: true }, "kraska").areaNetM2).toBeCloseTo(8, 2); // 10 − 2
  });
});
