// Можно ли поставить предмет сюда. Чистая геометрия — без three.js, гоняется тестами.
//
// ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ: перетаскивание обязано отвечать на вопрос «зелёный или красный» на
// КАЖДОЕ движение пальца, то есть быстро и без обращения к сцене. Полный питоновский солвер
// расстановки сюда тащить нельзя (десятки правил и Shapely), поэтому здесь — дешёвая проверка
// геометрии, а числа отступов взяты из того же канона, что у солвера.
//
// Что считаем:
//   1) предмет не вынесен за контур своей комнаты (вплотную к стене — можно);
//   2) не налезает на другие предметы (повёрнутые прямоугольники, разделяющая ось);
//   3) не встал в дверной проём — иначе дверь не откроется и пройти нельзя.
// Исключения (иначе честная расстановка окажется «красной»): ковёр лежит ПОД мебелью, настенные
// и подвешенные предметы не спорят с напольными, стул может заезжать под стол.

import type { Apartment, Placement } from "@/contracts/apartment";
import { findRoom } from "@/contracts/apartment";
import { passages } from "@/lib/viewer3d/walk";

/**
 * Допуск выхода за контур комнаты, см. НЕ «отступ от стены»: мебель как раз ставят ВПЛОТНУЮ к
 * стене, а встроенная кухня и шкаф стоят в стену. Здесь мы ловим только грубый вынос предмета
 * наружу — за стену или в соседнюю комнату (проверка 30.09: с «отступом 4 см» кухня и ковёр
 * сразу оказывались «вне комнаты»).
 */
export const ROOM_TOLERANCE_CM = 6;
/** Насколько предмет может перекрывать другой, прежде чем это считается столкновением (см²-доля). */
const OVERLAP_TOLERANCE = 0.06;

export interface Box {
  slotId: string;
  x: number;
  y: number;
  rot: number;
  wCm: number;
  dCm: number;
  /** Лежит на полу или висит: ковёр, картина, полка — за место с мебелью не спорят. */
  flat?: boolean;
  /** Роль предмета по-русски (`photoRole` слота): «стул», «стол обеденный», «ковёр»… */
  role?: string;
}

export type Refusal = "outside-room" | "on-door" | "overlap";

export interface PlacementCheck {
  ok: boolean;
  reason?: Refusal;
  /** С чем именно столкнулись — для подсказки человеку. */
  withSlotId?: string;
}

/** Четыре угла повёрнутого прямоугольника предмета. */
export function corners(b: Pick<Box, "x" | "y" | "rot" | "wCm" | "dCm">): [number, number][] {
  const rad = (b.rot * Math.PI) / 180;
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  const hw = b.wCm / 2;
  const hd = b.dCm / 2;
  const local: [number, number][] = [
    [-hw, -hd],
    [hw, -hd],
    [hw, hd],
    [-hw, hd],
  ];
  return local.map(([dx, dy]) => [b.x + dx * c - dy * s, b.y + dx * s + dy * c] as [number, number]);
}

function project(pts: [number, number][], ax: number, ay: number): [number, number] {
  let min = Infinity;
  let max = -Infinity;
  for (const [x, y] of pts) {
    const v = x * ax + y * ay;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return [min, max];
}

/** Пересекаются ли два повёрнутых прямоугольника (метод разделяющей оси). */
export function overlaps(a: [number, number][], b: [number, number][]): boolean {
  for (const pts of [a, b]) {
    for (let i = 0; i < pts.length; i += 1) {
      const [x1, y1] = pts[i]!;
      const [x2, y2] = pts[(i + 1) % pts.length]!;
      const ax = -(y2 - y1);
      const ay = x2 - x1;
      const len = Math.hypot(ax, ay) || 1;
      const [amin, amax] = project(a, ax / len, ay / len);
      const [bmin, bmax] = project(b, ax / len, ay / len);
      const gap = Math.min(amax, bmax) - Math.max(amin, bmin);
      if (gap <= 0) return false;                      // нашли ось, по которой не пересекаются
      const small = Math.min(amax - amin, bmax - bmin);
      if (small > 0 && gap / small < OVERLAP_TOLERANCE) return false; // касание — не столкновение
    }
  }
  return true;
}

/**
 * Предметы, которые НЕ спорят за место с другими: ковёр лежит ПОД мебелью, а полки, картины и
 * бра висят. Категория слота для этого не годится — у нас всё «furniture»; смотрим на роль и на
 * признак «лежит/висит», который считает вызывающая сторона по ассету и высоте подвеса.
 */
function isFlat(b: Pick<Box, "flat" | "role">): boolean {
  return b.flat === true || b.role === "ковёр";
}

/** Стул под столом — законная расстановка, а не столкновение. */
function chairUnderTable(a: Box, b: Box): boolean {
  const isChair = (r?: string): boolean => !!r && r.startsWith("стул");
  const isTable = (r?: string): boolean => !!r && (r.startsWith("стол") || r === "столик");
  return (isChair(a.role) && isTable(b.role)) || (isTable(a.role) && isChair(b.role));
}

export interface PlacementInput {
  apartment: Apartment;
  /** Все предметы сцены, включая перемещаемый (он исключается по slotId). */
  boxes: Box[];
  slotId: string;
  next: Pick<Placement, "x" | "y" | "rot"> & { wCm: number; dCm: number };
}

/** Главная проверка: можно ли поставить предмет в новую точку. */
export function checkPlacement(input: PlacementInput): PlacementCheck {
  const { apartment, boxes, slotId, next } = input;
  const me = boxes.find((b) => b.slotId === slotId);
  const roomId = me?.slotId ? apartment.slots.find((s) => s.id === slotId)?.roomId : undefined;
  const room = roomId ? findRoom(apartment, roomId) : null;
  if (!room) return { ok: false, reason: "outside-room" };

  const pts = corners(next);
  // 1) внутри комнаты с отступом от стен
  for (const [x, y] of pts) {
    if (
      x < room.x - ROOM_TOLERANCE_CM ||
      x > room.x + room.w + ROOM_TOLERANCE_CM ||
      y < room.y - ROOM_TOLERANCE_CM ||
      y > room.y + room.d + ROOM_TOLERANCE_CM
    ) {
      return { ok: false, reason: "outside-room" };
    }
  }

  // 2) не перекрывает дверной проём
  const flat = me ? isFlat(me) : false;
  if (!flat) {
    for (const p of passages(apartment, 40)) {
      const door: [number, number][] = [
        [p.x0, p.y0],
        [p.x1, p.y0],
        [p.x1, p.y1],
        [p.x0, p.y1],
      ];
      if (overlaps(pts, door)) return { ok: false, reason: "on-door" };
    }
  }

  // 3) не налезает на другие предметы
  if (!flat) {
    for (const other of boxes) {
      if (other.slotId === slotId) continue;
      if (isFlat(other)) continue;
      if (me && chairUnderTable(me, other)) continue;
      if (overlaps(pts, corners(other))) return { ok: false, reason: "overlap", withSlotId: other.slotId };
    }
  }

  return { ok: true };
}
