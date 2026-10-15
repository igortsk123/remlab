import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { autoTv, decorLayout, tvSpec, type DecorIn, type ExtraItem } from "@/lib/viewer3d/scene-extras";

// ТВ И ДЕКОР ЖИВОЙ СЦЕНЫ = СЕРВЕРНЫЙ КАДР (план demo-05 п.9). Эталон считает сам `draft_render.py`
// (`tools/assets/scene_extras_golden.py`); порт обязан совпасть до 0,05 см.
type Golden = {
  tv: { in: [number, number, number, boolean]; out: { inch: number; wCm: number; hCm: number; elevCm: number; how: string } }[];
  scenes: { name: string; items: ExtraItem[]; tv: null | { x: number; y: number; rot: number; wCm: number; dCm: number; hCm: number; elevCm: number; standElevCm: number | null } }[];
  decor: { name: string; items: ExtraItem[]; decor: DecorIn[]; placed: ({ i: number } & Record<"x" | "y" | "rot" | "elev" | "w" | "d" | "h", number>)[]; rest: number[] }[];
};
const golden = JSON.parse(readFileSync("tests/fixtures/scene-extras-golden.json", "utf8")) as Golden;
const close = (a: number, b: number): void => expect(Math.abs(a - b)).toBeLessThan(0.05);

describe("авто-ТВ и декор — как серверный кадр", () => {
  it("размер и подвес телевизора (tv_spec)", () => {
    for (const c of golden.tv) {
      const s = tvSpec(...c.in);
      expect([s.inch, s.how], JSON.stringify(c.in)).toEqual([c.out.inch, c.out.how]);
      close(s.wCm, c.out.wCm);
      close(s.hCm, c.out.hCm);
      close(s.elevCm, c.out.elevCm);
    }
  });

  it("авто-ТВ над тумбой: место, глубина, подвесная тумба", () => {
    for (const sc of golden.scenes) {
      const tv = autoTv(sc.items);
      if (!sc.tv) {
        expect(tv, sc.name).toBeNull();
        continue;
      }
      expect(tv, sc.name).not.toBeNull();
      for (const k of ["x", "y", "rot", "wCm", "dCm", "hCm", "elevCm"] as const) close(tv![k], sc.tv[k]);
      expect(tv!.standElevCm ?? null, sc.name).toEqual(sc.tv.standElevCm);
    }
  });

  it("настольный декор: опора, ряд, не влезло — не в сцене", () => {
    for (const c of golden.decor) {
      const { placed, rest } = decorLayout(c.items, c.decor);
      expect(placed.map((p) => c.decor.indexOf(p.decor)), c.name).toEqual(c.placed.map((p) => p.i));
      expect(rest.map((r) => c.decor.indexOf(r)), c.name).toEqual(c.rest);
      placed.forEach((p, k) => {
        for (const key of ["x", "y", "rot", "elev", "w", "d", "h"] as const) close(p[key], c.placed[k]![key]);
      });
    }
  });
});
