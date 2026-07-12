import { describe, it, expect } from "vitest";
import { calcToItems } from "@/lib/calc/to-estimate";
import { estimateItem } from "@/contracts/estimate";
import type { CalcProject } from "@/contracts/calc";

let n = 0;
const mkId = () => `i${++n}`;

describe("calc → estimate", () => {
  it("комнаты → позиции + сопутствующие, все валидны по схеме", () => {
    const project: CalcProject = {
      version: 1, kind: "laminat", updatedAt: "",
      rooms: [
        { id: "r1", name: "Гостиная", surfaces: [], floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] }, material: { pricePerPackRub: 1500 } },
      ],
    };
    const items = calcToItems(project, mkId);
    expect(items[0]!.title).toContain("Гостиная");
    expect(items[0]!.source).toBe("calc");
    expect(items.length).toBeGreaterThan(1); // + сопутствующие
    for (const it of items) expect(estimateItem.safeParse(it).success).toBe(true);
  });

  it("комнаты с нулевым расчётом пропускаются", () => {
    const project: CalcProject = {
      version: 1, kind: "oboi", updatedAt: "",
      rooms: [{ id: "r1", name: "Пустая", surfaces: [], material: {} }],
    };
    const items = calcToItems(project, mkId);
    // расчётных позиций нет (площадь 0), только сопутствующие
    expect(items.every((i) => i.source !== "calc")).toBe(true);
  });
});
