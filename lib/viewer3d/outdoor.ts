// БАЛКОН В 3D КОМНАТЫ (T-20261111-20/2, владелец TG 1624: «все элементы, как на плане, должны быть сделаны»).
//
// Уличное помещение за наружной стеной комнаты (`contracts/apartment.ts:annex`, `outdoor: true`; считает
// `tools/scout/trial_bundle.py:outdoor_of`) — плита и металлическое ограждение по трём сторонам, без стен, потолка и
// люстры: над ним небо панорамы (`rooms.ts:buildSurroundings`), поэтому жилой комнатой он не читается. Сторона, которой
// плита примыкает к комнате (`wall` — сторона КОМНАТЫ), — без ограждения: там стена дома с дверью из комнаты.
// Единицы и оси — как в `rooms.ts`: данные в см, сцена в метрах, план y → сцена Z.

import * as THREE from "three";

import type { Annex, Room, WallSide } from "@/contracts/apartment";

const CM = 0.01;
/** Плита — толщина под полом (верх — на уровне пола комнаты). */
export const SLAB_CM = 14;
/** Ограждение: высота поручня по норме для балконов (СП 54: не ниже 1,0 м), отступ от края плиты, шаг стоек и прутьев. */
export const RAIL_H_CM = 100;
const RAIL_INSET_CM = 3;
const POST_STEP_CM = 120;
const BAR_STEP_CM = 12;
const HOUSE_GAP_CM = 6;

const OPPOSITE: Record<WallSide, WallSide> = { south: "north", north: "south", west: "east", east: "west" };

/** Сторона комнаты, к которой примыкает плита: из данных, иначе по положению пристройки относительно комнаты. */
export function roomSideOf(room: Pick<Room, "w" | "d">, a: Pick<Annex, "x" | "y" | "w" | "d" | "wall">): WallSide {
  if (a.wall) return a.wall;
  if (a.y + a.d <= 0) return "south";
  if (a.y >= room.d) return "north";
  if (a.x + a.w <= 0) return "west";
  return "east";
}

/** Прямоугольник в координатах квартиры, см. */
export interface Rect { x: number; y: number; w: number; d: number }

/** Балконы комнаты в координатах квартиры (пристройки `outdoor`). */
export const outdoorRects = (room: Pick<Room, "x" | "y" | "annexes">): Rect[] =>
  (room.annexes ?? []).filter((a) => a.outdoor).map((a) => ({ x: room.x + a.x, y: room.y + a.y, w: a.w, d: a.d }));

const TOUCH_CM = 2;

/** Стена `side` коробки (комнаты или её пристройки) выходит на балкон: плита примыкает к ней вплотную и перекрывает её по длине.
 *  Такой стене не нужна картинка вида за окном (`openings.ts:noView`) — за ней сама сцена. */
export function touchesOutdoor(box: Rect, side: WallSide, outs: Rect[]): boolean {
  return outs.some((o) => {
    const alongX = Math.min(o.x + o.w, box.x + box.w) - Math.max(o.x, box.x);
    const alongY = Math.min(o.y + o.d, box.y + box.d) - Math.max(o.y, box.y);
    switch (side) {
      case "south": return alongX > 0 && Math.abs(o.y + o.d - box.y) <= TOUCH_CM;
      case "north": return alongX > 0 && Math.abs(o.y - (box.y + box.d)) <= TOUCH_CM;
      case "west": return alongY > 0 && Math.abs(o.x + o.w - box.x) <= TOUCH_CM;
      case "east": return alongY > 0 && Math.abs(o.x - (box.x + box.w)) <= TOUCH_CM;
    }
  });
}

/** Брус ограждения в осях плана: центр (x, y), высота центра z, размеры вдоль x, y и вверх — см. */
export interface RailBox { x: number; y: number; z: number; sx: number; sy: number; sz: number }

/**
 * Ограждение плиты `x0..x1 × y0..y1` (координаты квартиры, см) по всем сторонам, кроме `open` (стена дома): поручень, нижняя
 * перекладина, стойки на углах и не реже `POST_STEP_CM`, прутья с шагом `BAR_STEP_CM`. Чистая функция — её сверяет тест.
 */
export function railingBoxes(x0: number, y0: number, x1: number, y1: number, open: WallSide): RailBox[] {
  const i = RAIL_INSET_CM;
  // у стены дома боковое ограждение кончается, не доходя до неё на HOUSE_GAP_CM: стойка в стене прошла бы сквозь неё в комнату
  // (стена комнаты — плоскость в 1 см от края, `rooms.ts:INSET_CM`)
  const g = HOUSE_GAP_CM;
  const sx0 = x0 + (open === "west" ? g : 0), sx1 = x1 - (open === "east" ? g : 0);
  const sy0 = y0 + (open === "south" ? g : 0), sy1 = y1 - (open === "north" ? g : 0);
  const sides: Record<WallSide, [number, number, number, number]> = {
    south: [sx0, y0 + i, sx1, y0 + i], north: [sx0, y1 - i, sx1, y1 - i],
    west: [x0 + i, sy0, x0 + i, sy1], east: [x1 - i, sy0, x1 - i, sy1],
  };
  const out: RailBox[] = [];
  for (const side of ["south", "north", "west", "east"] as WallSide[]) {
    if (side === open) continue;
    const [ax, ay, bx, by] = sides[side];
    const along = ax === bx ? "y" : "x";
    const len = along === "x" ? bx - ax : by - ay;
    if (len <= 0) continue;
    const at = (u: number, z: number, s: number, h: number): RailBox => along === "x"
      ? { x: ax + u, y: ay, z, sx: s, sy: s, sz: h }
      : { x: ax, y: ay + u, z, sx: s, sy: s, sz: h };
    const rail = (z: number, t: number): RailBox => along === "x"
      ? { x: ax + len / 2, y: ay, z, sx: len, sy: t, sz: t }
      : { x: ax, y: ay + len / 2, z, sx: t, sy: len, sz: t };
    out.push(rail(RAIL_H_CM - 2.5, 5), rail(10, 4));
    const posts = Math.max(1, Math.ceil(len / POST_STEP_CM));
    for (let k = 0; k <= posts; k++) out.push(at((len * k) / posts, RAIL_H_CM / 2, 5, RAIL_H_CM));
    const bars = Math.floor(len / BAR_STEP_CM);
    for (let k = 1; k < bars; k++) out.push(at((len * k) / bars, (12 + RAIL_H_CM - 5) / 2, 2, RAIL_H_CM - 5 - 12));
  }
  return out;
}

/** Плита и ограждение балкона `a` комнаты `room` — группа в координатах квартиры. */
export function buildOutdoor(room: Room, a: Annex, i: number): THREE.Group {
  const g = new THREE.Group();
  g.name = `outdoor:${room.id}~${i}`;
  const x0 = room.x + a.x, y0 = room.y + a.y, x1 = x0 + a.w, y1 = y0 + a.d;

  const slab = new THREE.Mesh(
    new THREE.BoxGeometry(a.w * CM, SLAB_CM * CM, a.d * CM),
    new THREE.MeshStandardMaterial({ color: 0xb9b4aa, roughness: 0.92 }),   // бетон / уличный керамогранит, не паркет комнаты
  );
  slab.position.set(((x0 + x1) / 2) * CM, (-SLAB_CM / 2) * CM, ((y0 + y1) / 2) * CM);
  slab.name = `outdoor:${room.id}~${i}:slab`;
  slab.receiveShadow = true;
  g.add(slab);

  const boxes = railingBoxes(x0, y0, x1, y1, OPPOSITE[roomSideOf(room, a)]);
  if (boxes.length) {
    const rail = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshStandardMaterial({ color: 0x2f3336, metalness: 0.55, roughness: 0.45 }),
      boxes.length,
    );
    const m = new THREE.Matrix4();
    boxes.forEach((b, k) => {
      m.compose(new THREE.Vector3(b.x * CM, b.z * CM, b.y * CM), new THREE.Quaternion(), new THREE.Vector3(b.sx * CM, b.sz * CM, b.sy * CM));
      rail.setMatrixAt(k, m);
    });
    rail.instanceMatrix.needsUpdate = true;
    rail.castShadow = true;
    rail.name = `outdoor:${room.id}~${i}:railing`;
    g.add(rail);
  }
  return g;
}
