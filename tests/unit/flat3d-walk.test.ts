import { describe, expect, it } from "vitest";

import { loadFlat3d } from "@/lib/configurator/data";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { isExtra, planObjects } from "@/lib/viewer3d/build-scene";
import { canStand, nearestStandable, passages, stepWithSlide, walkArea, type Obstacle } from "@/lib/viewer3d/walk";

// СТОРОЖ ПРОХОДИМОСТИ. Из гостиной нельзя было выйти в коридор (жалоба владельца 30.09): между
// «внутри комнаты с отступом 28 см» и «в проёме ±20 см» оставалась мёртвая полоса 8 см, и шаг в
// неё не попадал. Тест заливает квартиру от точки старта и требует, чтобы дошли ДО КАЖДОЙ комнаты.

const { apartment, catalogue } = loadFlat3d();

/** Мебель по умолчанию — те же препятствия, что ставит движок (`viewer.syncObjects`). */
function furniture(): Obstacle[] {
  const scene = resolveScene(apartment, catalogue, defaultConfiguration(apartment, catalogue));
  return planObjects(apartment, catalogue, scene)
    .filter((sp) => sp.kind !== "rug" && sp.kind !== "bathroom" && !isExtra(sp.slotId) && sp.placement.hCm > 10)
    .map((sp) => ({ x: sp.placement.x, y: sp.placement.y, w: sp.placement.wCm, d: sp.placement.dCm, rot: sp.placement.rot }));
}

describe("прогулка по квартире", () => {
  it("полоса проёма перекрывает отступ от стен — иначе дверь «залипает»", () => {
    const area = walkArea(apartment);
    const p = passages(apartment)[0]!;
    const half = Math.min((p.x1 - p.x0) / 2, (p.y1 - p.y0) / 2);
    expect(half, "половина толщины проёма").toBeGreaterThan(area.marginCm);
  });

  it("сквозь мебель не ходят: внутри следа предмета и в 20 см от него стоять нельзя (demo-05 п.5)", () => {
    const sofa: Obstacle = { x: 300, y: 200, w: 200, d: 90, rot: 0 };
    const area = walkArea(apartment, 28, [sofa]);
    expect(canStand(area, 300, 200)).toBe(false);
    expect(canStand(area, 300, 200 + 45 + 15)).toBe(false); // в 15 см от спинки — меньше полуширины человека
    const turned = walkArea(apartment, 28, [{ ...sofa, rot: 90 }]);
    expect(canStand(turned, 300, 200 + 90)).toBe(false); // повёрнутый — длинной стороной вдоль y
    const spot = nearestStandable(area, 300, 200)!;
    expect(canStand(area, spot.x, spot.y)).toBe(true);
  });

  it("из следа предмета можно выйти; к цели за столиком человек его огибает, а не стоит перед ним", () => {
    const living = apartment.rooms.find((r) => r.id === "living")!;
    const cx = living.x + living.w / 2;
    const cy = living.y + living.d / 2;
    const table: Obstacle = { x: cx, y: cy, w: 120, d: 60, rot: 0 };
    const area = walkArea(apartment, 28, [table]);
    const out = stepWithSlide(area, { x: cx, y: cy }, 0, -5);
    expect(out.y).toBeLessThan(cy); // из центра столика шагнули наружу
    // идём «прямо сквозь» столик к точке за ним: должны оказаться за ним, а не застрять перед
    let p = { x: cx, y: cy + 90 };
    const goal = { x: cx, y: cy - 90 };
    for (let i = 0; i < 300 && Math.hypot(goal.x - p.x, goal.y - p.y) > 6; i++) {
      const a = Math.atan2(goal.x - p.x, goal.y - p.y);
      p = stepWithSlide(area, p, Math.sin(a) * 4, Math.cos(a) * 4);
    }
    expect(p.y, "обошли столик и вышли по ту сторону").toBeLessThan(cy - 30 - 20);
  });

  for (const withFurniture of [false, true])
  it(`от точки старта можно дойти в КАЖДУЮ комнату${withFurniture ? " — и с мебелью по умолчанию" : ""}`, () => {
    const area = walkArea(apartment, 28, withFurniture ? furniture() : []);
    const step = 5;
    const minX = Math.min(...apartment.rooms.map((r) => r.x));
    const maxX = Math.max(...apartment.rooms.map((r) => r.x + r.w));
    const minY = Math.min(...apartment.rooms.map((r) => r.y));
    const maxY = Math.max(...apartment.rooms.map((r) => r.y + r.d));

    const seen = new Set<string>();
    const reached = new Set<string>();
    const queue: [number, number][] = [
      [Math.round(apartment.spawn.x / step) * step, Math.round(apartment.spawn.y / step) * step],
    ];
    while (queue.length) {
      const [x, y] = queue.pop()!;
      if (x < minX || x > maxX || y < minY || y > maxY) continue;
      const key = `${x},${y}`;
      if (seen.has(key)) continue;
      if (!canStand(area, x, y)) continue;
      seen.add(key);
      const room = apartment.rooms.find((r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.d);
      if (room) reached.add(room.id);
      queue.push([x + step, y], [x - step, y], [x, y + step], [x, y - step]);
    }

    const missing = apartment.rooms.map((r) => r.id).filter((id) => !reached.has(id));
    expect(missing, `недостижимые комнаты: ${missing.join(", ")}`).toEqual([]);
  });
});
