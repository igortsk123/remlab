import { describe, expect, it } from "vitest";

import { loadFlat3d } from "@/lib/configurator/data";
import { canStand, passages, walkArea } from "@/lib/viewer3d/walk";

// СТОРОЖ ПРОХОДИМОСТИ. Из гостиной нельзя было выйти в коридор (жалоба владельца 30.09): между
// «внутри комнаты с отступом 28 см» и «в проёме ±20 см» оставалась мёртвая полоса 8 см, и шаг в
// неё не попадал. Тест заливает квартиру от точки старта и требует, чтобы дошли ДО КАЖДОЙ комнаты.

const { apartment } = loadFlat3d();

describe("прогулка по квартире", () => {
  it("полоса проёма перекрывает отступ от стен — иначе дверь «залипает»", () => {
    const area = walkArea(apartment);
    const p = passages(apartment)[0]!;
    const half = Math.min((p.x1 - p.x0) / 2, (p.y1 - p.y0) / 2);
    expect(half, "половина толщины проёма").toBeGreaterThan(area.marginCm);
  });

  it("от точки старта можно дойти в КАЖДУЮ комнату", () => {
    const area = walkArea(apartment);
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
