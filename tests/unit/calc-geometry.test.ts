import { describe, it, expect } from "vitest";
import { floorNet, roomAreas, surfaceNet } from "@/lib/calc/geometry";
import type { Floor, Room, Surface } from "@/contracts/calc";

describe("calc geometry — площади с проёмами и зонами", () => {
  it("surfaceNet вычитает проёмы (4×2.5 − окно 1.5×1.4 = 7.9)", () => {
    const s: Surface = {
      id: "s1", label: "", lengthM: 4, heightM: 2.5,
      openings: [{ id: "o1", kind: "window", widthM: 1.5, heightM: 1.4, count: 1 }],
    };
    expect(surfaceNet(s)).toBeCloseTo(7.9, 5);
  });

  it("floorNet = база + доп − исключаемые (20 + 1 − 1 = 20)", () => {
    const f: Floor = {
      lengthM: 5, widthM: 4,
      extraZones: [{ id: "z1", label: "", lengthM: 1, widthM: 1 }],
      excludedZones: [{ id: "z2", label: "", lengthM: 0.5, widthM: 2 }],
    };
    expect(floorNet(f)).toBeCloseTo(20, 5);
  });

  it("roomAreas по стенам суммирует gross/net", () => {
    const room: Room = {
      id: "r", name: "", material: {},
      surfaces: [
        { id: "s1", label: "", lengthM: 4, heightM: 2.5, openings: [] },
        { id: "s2", label: "", lengthM: 3, heightM: 2.5, openings: [{ id: "o", kind: "door", widthM: 0.9, heightM: 2, count: 1 }] },
      ],
    };
    const a = roomAreas(room, "oboi");
    expect(a.grossM2).toBeCloseTo(17.5, 2); // 10 + 7.5
    expect(a.netM2).toBeCloseTo(15.7, 2); // 10 + (7.5 − 1.8)
  });

  it("roomAreas для ламината берёт площадь пола", () => {
    const room: Room = {
      id: "r", name: "", material: {}, surfaces: [],
      floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] },
    };
    expect(roomAreas(room, "laminat").netM2).toBeCloseTo(20, 2);
  });
});
