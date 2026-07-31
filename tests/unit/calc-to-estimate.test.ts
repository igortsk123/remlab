import { describe, it, expect } from "vitest";
import { calcToItems } from "@/lib/calc/to-estimate";
import { estimateItem } from "@/contracts/estimate";
import type { CalcProject } from "@/contracts/calc";

let n = 0;
const mkId = () => `i${++n}`;

describe("calc → estimate", () => {
  it("комнаты → только расчётные позиции (сопутка — чек-лист на /e, не позиции; ADR-0040)", () => {
    const project: CalcProject = {
      version: 1, kind: "laminat", updatedAt: "",
      rooms: [
        { id: "r1", name: "Гостиная", surfaces: [], floor: { lengthM: 5, widthM: 4, extraZones: [], excludedZones: [] }, material: { pricePerPackRub: 1500 } },
      ],
    };
    const items = calcToItems(project, mkId);
    expect(items.length).toBe(1);
    expect(items[0]!.title).toContain("Гостиная");
    expect(items[0]!.source).toBe("calc");
    for (const it of items) expect(estimateItem.safeParse(it).success).toBe(true);
  });

  it("комнаты с нулевым расчётом → пустой список (сохранение такого расчёта не пройдёт)", () => {
    const project: CalcProject = {
      version: 1, kind: "oboi", updatedAt: "",
      rooms: [{ id: "r1", name: "Пустая", surfaces: [], material: {} }],
    };
    expect(calcToItems(project, mkId)).toEqual([]);
  });
});
