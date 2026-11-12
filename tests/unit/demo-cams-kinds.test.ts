import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ПАРА РАКУРСОВ ПО ТИПУ КОМНАТЫ (T-20261112-76/2, владелец TG 1061: «выгодный ракурс автоматом, зависит от комнаты»; разбор Codex
// `_intake/codex/2026-11-12-cam-auto-answer.md`). Одна функция на все экраны — `camPairAll` блока CAMFIT страницы (её же исполняет
// `tools/flat3d/demo-cams.mjs` при сборке /demo и туров): профиль вида — по типу коробки (`camZ`), без типа — гостиная, детская — спальня,
// неизвестный тип — «прочие», не гостиная. Плюс свой вид окошка: взгляд живой сцены → точка съёмки (`camFromView`).
type It = { role: string; x: number; y: number; rot: number; w: number; d: number; h: number | null };
type Cam = { name: string; x: number; y: number; rot: number; fov: number; pose?: number; user?: boolean };
type Door = { kind: string; wall: string; offset_cm: number; width_cm: number; is_entrance?: boolean };
type Room = { w: number; d: number; kind?: string; openings: Door[] };
type Zone = { intent?: { c2: string[] } };
type Api = {
  camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[], o?: object) => { cams: Cam[]; how: string; warns?: string[] };
  camZ: () => Zone;
  CAM_ZONES: Record<string, Zone>;
  camFromView: (p: { x: number; y: number; yaw: number } | null, k: number, base: { fov?: number } | undefined, poseVer: number) => Cam | null;
};
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const apiOf = (room: Room) => new Function("D", `${block};return {camPairAll,camZ,CAM_ZONES,camFromView};`)({ room }) as Api;
const corners = (W: number, H: number) => [{ x: 3, y: 3 }, { x: W - 3, y: 3 }, { x: W - 3, y: H - 3 }, { x: 3, y: H - 3 }];
const it0 = (role: string, x: number, y: number, w: number, d: number, h: number, rot = 0): It => ({ role, x, y, w, d, h, rot });
const door: Door = { kind: "door", wall: "south", offset_cm: 20, width_cm: 80, is_entrance: true };
const win = (wall: string, offset_cm: number): Door => ({ kind: "window", wall, offset_cm, width_cm: 120 });

// комнаты-эталоны по типам (Codex п.6): кухня-галерея, санузел 170×150, детская со столом у окна, комната без распознанного типа
const ROOMS: Record<string, { room: Room; items: It[] }> = {
  kitchen: { room: { w: 360, d: 280, kind: "kitchen", openings: [door, win("north", 120)] },
    items: [it0("кухня-ряд", 180, 250, 300, 60, 90, 180), it0("холодильник", 330, 250, 60, 65, 200, 180), it0("стол обеденный", 230, 110, 110, 70, 75),
      it0("стул", 230, 60, 45, 45, 90), it0("стул", 230, 160, 45, 45, 90, 180)] },
  bathroom: { room: { w: 170, d: 150, kind: "bathroom", openings: [door] },
    items: [it0("ванна", 85, 115, 170, 70, 60, 180), it0("раковина", 140, 35, 50, 45, 85, 270), it0("унитаз", 30, 40, 40, 65, 75, 90)] },
  kids: { room: { w: 330, d: 300, kind: "kids", openings: [door, win("north", 100)] },
    items: [it0("кровать", 70, 180, 90, 200, 45, 90), it0("стол рабочий", 230, 260, 110, 60, 75, 180), it0("стул рабочий", 230, 215, 45, 45, 90),
      it0("шкаф", 290, 90, 60, 120, 200, 270), it0("тумба прикроватная", 30, 60, 40, 40, 50, 90)] },
  other: { room: { w: 300, d: 260, kind: "storage", openings: [door] },
    items: [it0("шкаф", 150, 230, 160, 60, 210, 180), it0("стол рабочий", 250, 90, 100, 60, 75, 270)] },
  living: { room: { w: 420, d: 340, openings: [door, win("north", 150)] },
    items: [it0("диван", 210, 300, 220, 95, 85, 180), it0("столик", 210, 200, 100, 60, 45), it0("тв-тумба", 210, 25, 180, 40, 55)] },
};

describe("профиль видов по типу комнаты (camZ)", () => {
  it("без типа — гостиная, детская — спальня, санузел и кухня — свои, неизвестный — «прочие», у каждого есть смысл видов", () => {
    const z = (kind?: string) => apiOf({ w: 300, d: 300, kind, openings: [door] });
    const a = z();
    expect(a.camZ()).toBe(a.CAM_ZONES.living);
    const kids = z("kids"), bath = z("bathroom"), other = z("storage"), wc = z("wc");
    expect(kids.camZ()).toBe(kids.CAM_ZONES.bedroom);
    expect(bath.camZ()).toBe(bath.CAM_ZONES.bathroom);
    expect(wc.camZ()).toBe(wc.CAM_ZONES.bathroom);
    expect(other.camZ()).toBe(other.CAM_ZONES.other);
    for (const k of ["living", "bedroom", "kitchen", "hall", "bathroom", "other"]) expect(a.CAM_ZONES[k]!.intent, k).toBeTruthy();
  });
});

describe("пара ракурсов по типу комнаты (camPairAll)", () => {
  for (const [kind, { room, items }] of Object.entries(ROOMS)) {
    it(`${kind}: две точки C1/C2 внутри комнаты, не одна и та же`, () => {
      const api = apiOf(room);
      const r = api.camPairAll([items], room.w, room.d, corners(room.w, room.d));
      expect(r && r.cams.length, `${kind}: ${r && r.how}`).toBe(2);
      expect(r.cams.map((c) => c.name)).toEqual(["C1", "C2"]);
      for (const c of r.cams) {
        expect(c.x, `${kind} x`).toBeGreaterThanOrEqual(0); expect(c.x).toBeLessThanOrEqual(room.w);
        expect(c.y, `${kind} y`).toBeGreaterThanOrEqual(0); expect(c.y).toBeLessThanOrEqual(room.d);
      }
      const [a, b] = r.cams as [Cam, Cam];
      expect(Math.hypot(a.x - b.x, a.y - b.y) > 20 || Math.abs(((a.rot - b.rot + 540) % 360) - 180) > 30, `${kind}: пара не дубль`).toBe(true);
    }, 60000);
  }
});

describe("свой вид окошка — точка съёмки из взгляда живой сцены (camFromView)", () => {
  const api = apiOf(ROOMS.living!.room);
  it("rot — обратное к yaw `viewer.ts:viewPose` (yaw = (540 − rot) mod 360) по всему кругу", () => {
    for (const rot of [0, 45, 90, 135, 180, 225, 270, 315, 359]) {
      const yaw = (((540 - rot) % 360) + 360) % 360;
      expect(api.camFromView({ x: 100.4, y: 50.6, yaw }, 0, { fov: 90 }, 3)).toEqual({ name: "C1", x: 100, y: 51, rot, fov: 90, pose: 3, user: true });
    }
  });
  it("окошко 2 — имя C2; угла обзора нет — 72°; позы нет — null", () => {
    expect(api.camFromView({ x: 10, y: 20, yaw: 180 }, 1, undefined, 3)).toMatchObject({ name: "C2", rot: 0, fov: 72, user: true });
    expect(api.camFromView(null, 0, undefined, 3)).toBeNull();
  });
});
