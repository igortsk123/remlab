import { describe, it, expect } from "vitest";
import { computeRoom } from "@/lib/calc/formulas";
import type { Room } from "@/contracts/calc";

const wall = (id: string, lengthM: number, heightM: number): Room["surfaces"][number] => ({ id, label: "", lengthM, heightM, openings: [] });

describe("calc formulas — количество материала", () => {
  it("обои: периметр 12, высота 2.5 → 8 рулонов (0.53×10.05)", () => {
    const room: Room = {
      id: "r", name: "", material: {},
      surfaces: [wall("a", 4, 2.5), wall("b", 2, 2.5), wall("c", 4, 2.5), wall("d", 2, 2.5)],
    };
    const out = computeRoom(room, "oboi");
    expect(out.qty).toBe(8);
    expect(out.unit).toBe("рулон");
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

  it("ламинат: пол 20 м², прямая укладка +5%, 2.13 м²/упак → 10 упак", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [],
      floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] },
      material: { direction: "length" },
    };
    expect(computeRoom(room, "laminat").qty).toBe(10);
  });

  it("ламинат: диагональ добавляет запас (20 м² → 11 упак)", () => {
    const room: Room = {
      id: "r", name: "", surfaces: [],
      floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] },
      material: { direction: "diag45" },
    };
    expect(computeRoom(room, "laminat").qty).toBe(11);
  });
});
