import { describe, expect, it } from "vitest";

import { room as roomSchema, type Opening } from "@/contracts/apartment";
import { canStand, type Obstacle, type WalkArea } from "@/lib/viewer3d/walk";
import { WINDOW_GAP_CM, windowAtPoint, windowSpot } from "@/lib/viewer3d/window-walk";

// ПОДОЙТИ К ОКНУ (T-20261112-30, владелец TG 1731): тап по окну в «3D» — встать в 70 см от него напротив середины, взглядом наружу;
// мебель у окна — первая свободная точка дальше в комнату по нормали, не сквозь мебель. Комната 400×300, окно на южной стене.
const win: Opening = { kind: "window", wall: "south", offsetCm: 100, widthCm: 150, sillCm: 85, heightCm: 150 };
const roomOf = (openings: Opening[]) =>
  roomSchema.parse({ id: "liv", kind: "living", titleRu: "Гостиная", titleEn: "Living", x: 0, y: 0, w: 400, d: 300, openings });
const areaOf = (openings: Opening[], obstacles: Obstacle[] = []): WalkArea => ({ rooms: [roomOf(openings)], passages: [], marginCm: 28, obstacles, bodyCm: 30 });

describe("подойти к окну: попадание", () => {
  const rooms = [roomOf([win])];
  it("стекло, подоконник и вид за окном — окно; середина выреза и нормаль внутрь", () => {
    for (const [x, y, h] of [[175, 1, 150], [120, 12, 86], [230, -40, 200]] as const) {
      expect(windowAtPoint(rooms, x, y, h), `${x},${y},${h}`).toMatchObject({ roomId: "liv", cx: 175, cy: 0, nx: 0, ny: 1, sill: 85, top: 235 });
    }
  });
  it("пол у окна, стена над и сбоку от выреза — не окно (тап туда — как раньше)", () => {
    for (const [x, y, h] of [[175, 10, 0], [175, 1, 250], [60, 1, 150], [175, 120, 150]] as const) expect(windowAtPoint(rooms, x, y, h), `${x},${y},${h}`).toBeNull();
  });
  it("балконная дверь: стекло — окно, пол у порога — пол", () => {
    const bal: Opening = { kind: "balcony", wall: "east", offsetCm: 100, widthCm: 90, heightCm: 220 };
    const r = [roomOf([bal])];
    expect(windowAtPoint(r, 399, 145, 120)).toMatchObject({ cx: 400, cy: 145, nx: -1, ny: 0, sill: 0 });
    expect(windowAtPoint(r, 390, 145, 0)).toBeNull();
  });
});

describe("подойти к окну: где встать", () => {
  it("пустая комната — 70 см от окна напротив середины, взгляд наружу", () => {
    const s = windowSpot(areaOf([win]), windowAtPoint([roomOf([win])], 175, 1, 150)!)!;
    expect(s).toMatchObject({ x: 175, y: WINDOW_GAP_CM, heading: 180, gapCm: WINDOW_GAP_CM });
    // взгляд прогулки (sin heading, cos heading) — к окну (−y)
    expect(Math.cos((s.heading * Math.PI) / 180)).toBeCloseTo(-1, 6);
  });
  it("диван спинкой к окну шире окна — не сквозь него: дальше в комнату по нормали, напротив середины", () => {
    const sofa: Obstacle = { x: 175, y: 45, w: 220, d: 90, rot: 0 };
    const area = areaOf([win], [sofa]), s = windowSpot(area, windowAtPoint(area.rooms, 175, 1, 150)!)!;
    expect(s.x).toBe(175);
    expect(s.y).toBeGreaterThanOrEqual(90 + 30);
    expect(canStand(area, s.x, s.y)).toBe(true);
  });
  it("окно в углу (западная стена у южной), узкий проход — точка в комнате, не в стене", () => {
    const corner: Opening = { kind: "window", wall: "west", offsetCm: 0, widthCm: 100, sillCm: 85, heightCm: 150 };
    const area = areaOf([corner]), w = windowAtPoint(area.rooms, 1, 50, 150)!, s = windowSpot(area, w)!;
    expect([s.x, s.heading]).toEqual([WINDOW_GAP_CM, 270]);
    expect(canStand(area, s.x, s.y)).toBe(true);
    expect(Math.abs(s.y - 50)).toBeLessThanOrEqual(50);
  });
  it("всё у окна занято — null (остаёмся на месте)", () => {
    const wall: Obstacle = { x: 200, y: 150, w: 400, d: 300, rot: 0 };
    const area = areaOf([win], [wall]);
    expect(windowSpot(area, windowAtPoint(area.rooms, 175, 1, 150)!)).toBeNull();
  });
});
