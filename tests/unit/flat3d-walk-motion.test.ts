import { describe, expect, it } from "vitest";

import { loadFlat3d } from "@/lib/configurator/data";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { isExtra, planObjects } from "@/lib/viewer3d/build-scene";
import { canStand, passages, walkArea, type Obstacle, type Passage, type WalkArea } from "@/lib/viewer3d/walk";
import { followRoute, newRoute, planRoute, slideStep, type Pt } from "@/lib/viewer3d/walk-motion";

// СТОРОЖ ПЛАВНОСТИ ПРОГУЛКИ (T-20261111-14, владелец TG 1023: «с компьютера дёргается в проходах»). Прежний шаг у косяка и у
// гарнитура рядом с дверью качался «вперёд — назад» каждый кадр (/flat, дверь кухни: 499,251 ↔ 500,255 сотни кадров подряд).
// Сторож: у каждой двери квартиры с мебелью по умолчанию ходим клавишей «вперёд» и тапом «за дверь» при 60 и 20 кадрах в
// секунду; шаг, развёрнутый против предыдущего, допустим только микроскопический (< 0,5 см — касание угла).

const { apartment, catalogue } = loadFlat3d();

function furniture(): Obstacle[] {
  const scene = resolveScene(apartment, catalogue, defaultConfiguration(apartment, catalogue));
  return planObjects(apartment, catalogue, scene)
    .filter((sp) => sp.kind !== "rug" && sp.kind !== "bathroom" && !isExtra(sp.slotId) && sp.placement.hCm > 10)
    .map((sp) => ({ x: sp.placement.x, y: sp.placement.y, w: sp.placement.wCm, d: sp.placement.dCm, rot: sp.placement.rot }));
}

/** Двери без повторов (проём виден из обеих комнат) и сторона прохода: стена на `cy` — идём по y. */
function doors(area: WalkArea): { c: Pt; alongY: boolean }[] {
  const seen = new Set<string>();
  const out: { c: Pt; alongY: boolean }[] = [];
  for (const p of passages(apartment) as Passage[]) {
    const key = `${p.x0},${p.x1},${p.y0},${p.y1}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const c = { x: (p.x0 + p.x1) / 2, y: (p.y0 + p.y1) / 2 };
    const alongY = area.rooms.some((r) => (r.y === c.y || r.y + r.d === c.y) && r.x <= p.x0 && r.x + r.w >= p.x1);
    out.push({ c, alongY });
  }
  return out;
}

/** Рывки: шаг, развёрнутый против предыдущего (скалярное < 0), длиной ≥ 0,5 см. */
function reversals(path: Pt[]): number {
  let n = 0;
  let prev: Pt | null = null;
  for (let i = 1; i < path.length; i++) {
    const s = { x: path[i]!.x - path[i - 1]!.x, y: path[i]!.y - path[i - 1]!.y };
    if (Math.hypot(s.x, s.y) < 0.5) continue;
    if (prev && s.x * prev.x + s.y * prev.y < 0) n++;
    prev = s;
  }
  return n;
}

/** Метания вбок: смены стороны поперечной составляющей шага (≥ 0,5 см) относительно курса `dir`. */
function zigzags(path: Pt[], dir: Pt): number {
  let n = 0;
  let last = 0;
  for (let i = 1; i < path.length; i++) {
    const lat = (path[i]!.x - path[i - 1]!.x) * dir.y - (path[i]!.y - path[i - 1]!.y) * dir.x;
    if (Math.abs(lat) < 0.5) continue;
    const s = Math.sign(lat);
    if (last && s !== last) n++;
    last = s;
  }
  return n;
}

describe("плавность прогулки у дверей (walk-motion)", () => {
  const area = walkArea(apartment, 28, furniture());
  const cases: { name: string; start: Pt; goal: Pt; door: Pt }[] = [];
  for (const { c, alongY } of doors(area)) {
    for (const side of [-1, 1]) {
      for (const lat of [-40, 0, 40]) {
        const start = alongY ? { x: c.x + lat, y: c.y + side * 150 } : { x: c.x + side * 150, y: c.y + lat };
        const goal = alongY ? { x: c.x, y: c.y - side * 150 } : { x: c.x - side * 150, y: c.y };
        if (canStand(area, start.x, start.y)) cases.push({ name: `${c.x},${c.y} ${side} ${lat}`, start, goal, door: c });
      }
    }
  }

  it("сценариев у дверей достаточно (иначе сторож пустой)", () => {
    expect(cases.length).toBeGreaterThanOrEqual(12);
  });

  for (const fps of [60, 20]) {
    it(`клавиша «вперёд» к двери (${fps} к/с): ни одного шага назад, стоим только в проходимом`, () => {
      const bad: string[] = [];
      for (const k of cases) {
        for (const tilt of [-20, 0, 20]) {
          const h = Math.atan2(k.door.x - k.start.x, k.door.y - k.start.y) + (tilt * Math.PI) / 180;
          const step = 240 / fps;
          let p = { ...k.start };
          const path = [p];
          const memo = { side: 0, free: 0 };
          for (let f = 0; f < 3 * fps; f++) {
            p = slideStep(area, p, Math.sin(h) * step, Math.cos(h) * step, memo);
            if (!canStand(area, p.x, p.y)) bad.push(`${k.name} ${tilt}°: встали в непроходимое ${p.x.toFixed(0)},${p.y.toFixed(0)}`);
            path.push(p);
          }
          const r = reversals(path);
          if (r) bad.push(`${k.name} ${tilt}°: рывков назад ${r}`);
          const z = zigzags(path, { x: Math.sin(h), y: Math.cos(h) });
          if (z > 2) bad.push(`${k.name} ${tilt}°: метаний вбок ${z}`);
        }
      }
      expect(bad).toEqual([]);
    });

    it(`тап «за дверь» (${fps} к/с): доходим, без рывков назад`, () => {
      const bad: string[] = [];
      let tried = 0;
      for (const k of cases) {
        if (!canStand(area, k.goal.x, k.goal.y)) continue;
        tried++;
        let p = { ...k.start };
        const route = newRoute(planRoute(area, p, k.goal) ?? [k.goal]);
        const path = [p];
        for (let f = 0; f < 6 * fps; f++) {
          const r = followRoute(area, p, route, 260 / fps);
          p = r.pos;
          path.push(p);
          if (r.done) break;
        }
        const left = Math.hypot(p.x - k.goal.x, p.y - k.goal.y);
        if (left > 10) bad.push(`${k.name}: не дошли, осталось ${left.toFixed(0)} см`);
        const r = reversals(path);
        if (r) bad.push(`${k.name}: рывков назад ${r}`);
      }
      expect(tried).toBeGreaterThanOrEqual(8);
      expect(bad).toEqual([]);
    });
  }

  it("тап туда, куда не пройти (пятачок, обнесённый мебелью): доходим до ближайшей точки и встаём, без качелей", () => {
    const living = apartment.rooms.find((r) => r.id === "living")!;
    const g = { x: living.x + living.w / 2, y: living.y + living.d / 2 };
    const ring: Obstacle[] = [
      { x: g.x + 70, y: g.y, w: 20, d: 140, rot: 0 }, { x: g.x - 70, y: g.y, w: 20, d: 140, rot: 0 },
      { x: g.x, y: g.y + 70, w: 140, d: 20, rot: 0 }, { x: g.x, y: g.y - 70, w: 140, d: 20, rot: 0 },
    ];
    const a = walkArea(apartment, 28, ring);
    expect(canStand(a, g.x, g.y), "внутри пятачка стоять можно").toBe(true);
    const from = { x: g.x - 250, y: g.y + 20 };
    expect(canStand(a, from.x, from.y)).toBe(true);
    const route = newRoute(planRoute(a, from, g) ?? [g]);
    let p = { ...from };
    const path = [p];
    let done = false;
    for (let f = 0; f < 400 && !done; f++) {
      const r = followRoute(a, p, route, 4);
      p = r.pos;
      path.push(p);
      done = r.done;
    }
    expect(done, "остановились сами").toBe(true);
    expect(reversals(path)).toBe(0);
    expect(Math.hypot(p.x - g.x, p.y - g.y), "встали у ограды, ближе, чем начинали").toBeLessThan(150);
  });

  it("пустая квартира: клавиша «вперёд» на середину двери со смещением до 40 см — проходим в соседнюю комнату", () => {
    // косяк не должен ни останавливать, ни отбрасывать: смещённый взгляд скользит по косяку в проём (прежний шаг тут качался)
    const empty = walkArea(apartment);
    const stuck: string[] = [];
    for (const { c, alongY } of doors(empty)) {
      for (const side of [-1, 1]) {
        for (const lat of [-40, 0, 40]) {
          const s = alongY ? { x: c.x + lat, y: c.y + side * 120 } : { x: c.x + side * 120, y: c.y + lat };
          if (!canStand(empty, s.x, s.y)) continue;
          const h = Math.atan2(c.x - s.x, c.y - s.y);
          let p = { ...s };
          for (let f = 0; f < 120; f++) p = slideStep(empty, p, Math.sin(h) * 4, Math.cos(h) * 4);
          const crossed = alongY ? Math.sign(p.y - c.y) === -side : Math.sign(p.x - c.x) === -side;
          if (!crossed) stuck.push(`${c.x},${c.y} ${side} ${lat}: встали у ${p.x.toFixed(0)},${p.y.toFixed(0)}`);
        }
      }
    }
    expect(stuck).toEqual([]);
  });
});
