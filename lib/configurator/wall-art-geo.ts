// ГЕОМЕТРИЯ СТЕНЫ ДЛЯ КАРТИНЫ (viz-decor-01 шаг 3): у какой стены стоит опора, где по стене проёмы и створки дверей, что ещё
// стоит у стены. Чистые функции в координатах квартиры (см): x вправо, y вглубь, rot по часовой, 0 — лицом на +y
// (`contracts/apartment.ts`). Отступ проёма `offsetCm` — от начала стены: запад→восток у south/north, юг→север у west/east.

import type { Placement, Room, WallSide } from "@/contracts/apartment";

/** Поверхность стены отстоит от линии комнаты на 1 см (`lib/viewer3d/rooms.ts:INSET_CM`). */
export const WALL_INSET_CM = 1;

/** Прямоугольник на полу, см: [x0, y0, x1, y1]. */
export type Rect = [number, number, number, number];

/** Стена за спинкой: rot 0 смотрит на +y — спинка к южной стене, 90 — к западной, 180 — к северной, 270 — к восточной. */
const BACK: Record<number, WallSide> = { 0: "south", 90: "west", 180: "north", 270: "east" };

/** Поворот, кратный 90° (с допуском 1°), → 0/90/180/270; косо стоящая мебель — null (картина над ней не висит). */
export function rightAngle(rot: number): number | null {
  const r = ((rot % 360) + 360) % 360;
  const k = Math.round(r / 90) % 4;
  return Math.abs(r - Math.round(r / 90) * 90) <= 1 ? k * 90 : null;
}

/** Длина стены и положение центра предмета вдоль неё (от начала стены). */
export function wallLength(room: Room, wall: WallSide): number {
  return wall === "south" || wall === "north" ? room.w : room.d;
}
export function alongOf(room: Room, wall: WallSide, x: number, y: number): number {
  return wall === "south" || wall === "north" ? x - room.x : y - room.y;
}

/** Стена за спинкой предмета и зазор спинки до неё, см; предмет косо — null. */
export function backWall(room: Room, p: Placement): { wall: WallSide; gap: number } | null {
  const r = rightAngle(p.rot);
  if (r === null) return null;
  const wall = BACK[r]!;
  const half = p.dCm / 2;
  const gap = wall === "south" ? p.y - half - room.y : wall === "north" ? room.y + room.d - (p.y + half)
    : wall === "west" ? p.x - half - room.x : room.x + room.w - (p.x + half);
  return { wall, gap };
}

/** Полоса у стены: отрезок [a0, a1] вдоль стены и глубина от стены в комнату → прямоугольник на полу. */
export function stripRect(room: Room, wall: WallSide, a0: number, a1: number, depth: number): Rect {
  if (wall === "south") return [room.x + a0, room.y, room.x + a1, room.y + depth];
  if (wall === "north") return [room.x + a0, room.y + room.d - depth, room.x + a1, room.y + room.d];
  if (wall === "west") return [room.x, room.y + a0, room.x + depth, room.y + a1];
  return [room.x + room.w - depth, room.y + a0, room.x + room.w, room.y + a1];
}

/** Центр предмета глубиной `dCm`, повешенного на стену в точке `along`. */
export function onWall(room: Room, wall: WallSide, along: number, dCm: number): { x: number; y: number } {
  const off = WALL_INSET_CM + dCm / 2;
  if (wall === "south") return { x: room.x + along, y: room.y + off };
  if (wall === "north") return { x: room.x + along, y: room.y + room.d - off };
  if (wall === "west") return { x: room.x + off, y: room.y + along };
  return { x: room.x + room.w - off, y: room.y + along };
}

/** След предмета на полу (поворот кратный 90° — точно, косой — описанным квадратом). */
export function footprint(p: Placement): Rect {
  const r = rightAngle(p.rot);
  const [hw, hd] = r === null ? [Math.hypot(p.wCm, p.dCm) / 2, Math.hypot(p.wCm, p.dCm) / 2]
    : r === 90 || r === 270 ? [p.dCm / 2, p.wCm / 2] : [p.wCm / 2, p.dCm / 2];
  return [p.x - hw, p.y - hd, p.x + hw, p.y + hd];
}

export const overlaps = (a: Rect, b: Rect): boolean => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

/**
 * Зоны открывания дверей комнаты (створка внутрь, `swingCm` ≠ 0; глубина — `swingCm`, нет — ширина полотна): картина на соседней
 * стене в такой зоне мешала бы двери.
 */
export function swingZones(room: Room): Rect[] {
  return room.openings.filter((o) => (o.kind === "door" || o.kind === "balcony") && o.swingCm !== 0)
    .map((o) => stripRect(room, o.wall, o.offsetCm, o.offsetCm + o.widthCm, o.swingCm ?? o.widthCm));
}
