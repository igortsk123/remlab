import { describe, expect, it } from "vitest";

import { blocksWalk, OVERHEAD_CM } from "@/lib/viewer3d/walk";

// T-20261119-115/3 (живая 2.19, set7): подвес выше головы (люстра) не препятствие для прогулки и старта; всё, что стоит или висит ниже, — препятствие.
describe("blocksWalk — препятствие по высоте низа", () => {
  it("люстра: низ 244 см, высота 26 — не препятствие", () => {
    expect(blocksWalk({ hCm: 26.3, elevCm: 243.7 })).toBe(false);
  });
  it("предмет на полу — препятствие, торшер тоже", () => {
    expect(blocksWalk({ hCm: 87 })).toBe(true);
    expect(blocksWalk({ hCm: 157, elevCm: 0 })).toBe(true);
  });
  it("висящий на уровне головы и ниже (полка, бра на 150 см) — препятствие", () => {
    expect(blocksWalk({ hCm: 30, elevCm: 150 })).toBe(true);
    expect(blocksWalk({ hCm: 30, elevCm: OVERHEAD_CM - 1 })).toBe(true);
  });
  it("граница: низ ровно на пороге головы — уже над головой", () => {
    expect(blocksWalk({ hCm: 30, elevCm: OVERHEAD_CM })).toBe(false);
  });
  it("низкое (коврик, ≤10 см) — не препятствие, как прежде", () => {
    expect(blocksWalk({ hCm: 1 })).toBe(false);
    expect(blocksWalk({ hCm: 10 })).toBe(false);
  });
});
