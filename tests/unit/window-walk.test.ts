import { describe, expect, it } from "vitest";

import { room as roomSchema, type Opening } from "@/contracts/apartment";
import { canStand, type Obstacle, type WalkArea } from "@/lib/viewer3d/walk";
import { WINDOW_GAP_CM, windowAtPoint, windowGap, windowSpot } from "@/lib/viewer3d/window-walk";

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
  it("расстояние по углу обзора: окно + 25 см стены с боков по ширине кадра, не ближе 70 и не дальше середины комнаты (T-30/2)", () => {
    // телефон: ~46° по горизонтали — окну 150 см нужно ≈ 236 см; комната 300 — середина 150; 600 — 240
    expect(windowGap({ widthCm: 150, depthCm: 600 }, 46)).toBe(240);
    expect(windowGap({ widthCm: 150, depthCm: 300 }, 46)).toBe(150);
    // компьютер, широкий кадр 90°: (75 + 25) / tan 45° = 100
    expect(windowGap({ widthCm: 150, depthCm: 600 }, 90)).toBe(100);
    // узкое окно и широкий кадр — не ближе 70; маленькая комната — тоже 70
    expect(windowGap({ widthCm: 60, depthCm: 600 }, 100)).toBe(WINDOW_GAP_CM);
    expect(windowGap({ widthCm: 150, depthCm: 100 }, 46)).toBe(WINDOW_GAP_CM);
  });
  it("точка на нужном расстоянии; мебель там — ближе к окну, а не сквозь неё", () => {
    const w = windowAtPoint([roomOf([win])], 175, 1, 150)!;
    expect(w.depthCm).toBe(300);
    expect(windowSpot(areaOf([win]), w, 150)).toMatchObject({ x: 175, y: 150, gapCm: 150 });
    const table: Obstacle = { x: 175, y: 160, w: 120, d: 60, rot: 0 };
    const area = areaOf([win], [table]), s = windowSpot(area, w, 150)!;
    expect(s.x).toBe(175);
    expect(s.gapCm).toBeGreaterThanOrEqual(WINDOW_GAP_CM);
    expect(s.gapCm).toBeLessThan(150);
    expect(canStand(area, s.x, s.y)).toBe(true);
  });
  it("перед окном кровать во всю ширину окна — встать сбоку на нужном расстоянии и смотреть на окно наискось (T-30/2)", () => {
    const bed: Obstacle = { x: 175, y: 180, w: 180, d: 240, rot: 0 };
    const area = areaOf([win], [bed]), w = windowAtPoint(area.rooms, 175, 1, 150)!, s = windowSpot(area, w, 150)!;
    expect(s.gapCm).toBe(150);
    expect(Math.abs(s.x - 175)).toBeGreaterThan(75);
    expect(canStand(area, s.x, s.y)).toBe(true);
    // взгляд (sin, cos) — на середину окна (175, 0)
    const h = (s.heading * Math.PI) / 180, len = Math.hypot(175 - s.x, s.y);
    expect(Math.sin(h)).toBeCloseTo((175 - s.x) / len, 6);
    expect(Math.cos(h)).toBeCloseTo(-s.y / len, 6);
  });
  it("узкий кадр телефона: напротив окна свободно только вплотную (кровать) — сбоку на нужном расстоянии лучше, чем одно небо", () => {
    const bed: Obstacle = { x: 175, y: 220, w: 180, d: 160, rot: 0 };
    const area = areaOf([win], [bed]), w = windowAtPoint(area.rooms, 175, 1, 150)!, gap = windowGap(w, 46);
    const near = windowSpot(area, w, gap)!, phone = windowSpot(area, w, gap, 46)!;
    // без угла обзора — как раньше: напротив середины, вплотную к кровати
    expect(near.x).toBe(175);
    expect(near.gapCm).toBeLessThan(gap);
    // с углом обзора телефона — сбоку, дальше от окна, окно наискось
    expect(Math.abs(phone.x - 175)).toBeGreaterThan(75);
    expect(phone.gapCm).toBeGreaterThan(near.gapCm);
    expect(canStand(area, phone.x, phone.y)).toBe(true);
  });
  it("всё у окна занято — null (остаёмся на месте)", () => {
    const wall: Obstacle = { x: 200, y: 150, w: 400, d: 300, rot: 0 };
    const area = areaOf([win], [wall]);
    expect(windowSpot(area, windowAtPoint(area.rooms, 175, 1, 150)!)).toBeNull();
  });
});
