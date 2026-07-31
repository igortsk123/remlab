import { describe, it, expect } from "vitest";
import { splitEstimatesBySource } from "@/lib/estimate/lab-split";
import type { Estimate } from "@/contracts/estimate";

function est(id: string, source: Estimate["source"]): Estimate {
  return {
    id,
    sessionId: "s1",
    title: `Смета ${id}`,
    source,
    items: [],
    createdAt: "2026-07-31T10:00:00.000Z",
    updatedAt: "2026-07-31T10:00:00.000Z",
  };
}

describe("splitEstimatesBySource — раскладка смет по вкладкам лаборатории", () => {
  it("remont уходит во вкладку «Ремонт», calc и manual — в «Материалы»", () => {
    const { materials, remont } = splitEstimatesBySource([
      est("a", "calc"),
      est("b", "remont"),
      est("c", "manual"),
    ]);
    expect(materials.map((e) => e.id)).toEqual(["a", "c"]);
    expect(remont.map((e) => e.id)).toEqual(["b"]);
  });

  it("пустой вход → обе вкладки пустые", () => {
    const { materials, remont } = splitEstimatesBySource([]);
    expect(materials).toEqual([]);
    expect(remont).toEqual([]);
  });

  it("сохраняет исходный порядок внутри вкладки (свежие сверху приходят из repo)", () => {
    const { materials } = splitEstimatesBySource([est("new", "calc"), est("old", "calc")]);
    expect(materials.map((e) => e.id)).toEqual(["new", "old"]);
  });
});
