import { describe, expect, it } from "vitest";

import type { Room } from "@/contracts/apartment";
import { canStand, frameSpot, obstacleDistanceCm, type Obstacle, type WalkArea } from "@/lib/viewer3d/walk";

// НАВЕДЕНИЕ НА ЗАМЕНЁННЫЙ ПРЕДМЕТ (demo-15, критика Codex п.5): поворот на месте, если видно и не вплотную; иначе — точка кольца
// 1–1.8 м, где можно стоять и предмет виден, по проходимому пути; нет такой — только поворот. Комната — как гостиная демо 439×325.

const room = { id: "living", x: 0, y: 0, w: 439, d: 325 } as unknown as Room;
const area = (obstacles: Obstacle[]): WalkArea => ({ rooms: [room], passages: [], marginCm: 28, obstacles, bodyCm: 20 });
const sofa: Obstacle = { x: 155, y: 280, w: 198, d: 90, rot: 180, h: 83 };

describe("навести камеру на предмет", () => {
  it("видно и не вплотную — только поворот, взгляд на предмет", () => {
    const s = frameSpot(area([sofa]), { x: 400, y: 120 }, sofa);
    expect(s.kind).toBe("turn");
    expect(s.x).toBe(400);
    const a = (s.rot * Math.PI) / 180, fx = Math.sin(a), fy = -Math.cos(a);
    expect(fx * (sofa.x - 400) + fy * (sofa.y - 120)).toBeGreaterThan(0);          // смотрит в сторону дивана
  });

  it("стоим вплотную — переход на точку в 1–1.8 м, где можно стоять", () => {
    const ar = area([sofa]);
    const s = frameSpot(ar, { x: 155, y: 215 }, sofa);
    expect(s.kind).toBe("move");
    const d = obstacleDistanceCm(sofa, s.x, s.y);
    expect(d).toBeGreaterThanOrEqual(100);
    expect(d).toBeLessThanOrEqual(190);
    expect(canStand(ar, s.x, s.y)).toBe(true);
  });

  it("высокий шкаф между камерой и предметом — обходим, а не смотрим в шкаф; низкий столик взгляду не мешает", () => {
    const wardrobe: Obstacle = { x: 155, y: 170, w: 200, d: 40, rot: 0, h: 200 };
    const table: Obstacle = { x: 155, y: 170, w: 120, d: 60, rot: 0, h: 40 };
    expect(frameSpot(area([sofa, table]), { x: 155, y: 60 }, sofa).kind).toBe("turn");
    const s = frameSpot(area([sofa, wardrobe]), { x: 155, y: 60 }, sofa);
    expect(s.kind).toBe("move");
    expect(Math.abs(s.x - 155)).toBeGreaterThan(90);                               // ушли в сторону от шкафа
  });

  it("встать негде — только поворот на месте", () => {
    const tiny = { id: "living", x: 0, y: 0, w: 120, d: 120 } as unknown as Room;
    const box: Obstacle = { x: 60, y: 60, w: 40, d: 40, rot: 0, h: 80 };
    const s = frameSpot({ rooms: [tiny], passages: [], marginCm: 28, obstacles: [box], bodyCm: 20 }, { x: 35, y: 35 }, box);
    expect(s.kind).toBe("none");
    expect(s.x).toBe(35);
  });
});
